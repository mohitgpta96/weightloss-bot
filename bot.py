import os
import re
import logging
from datetime import datetime, date, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import db
import ai
import charts
from config import (
    CALORIE_GOAL, PROTEIN_GOAL, CARB_GOAL, FAT_GOAL, WATER_GOAL,
    EATING_WINDOW_START, EATING_WINDOW_END,
    SUPPLEMENTS, FASTING_SAFE_ITEMS, SLEEP_TRIGGERS, WAKE_TRIGGERS,
    STARTING_WEIGHT, TARGET_WEIGHT,
)

logger = logging.getLogger(__name__)

WATER_KEYWORDS = ("water", "pani", "paani", "glass", "glasses")
FOOD_QUESTION_PREFIXES = (
    "kya main",
    "can i eat",
    "can i have",
    "should i eat",
    "is it okay to eat",
)
FOOD_HINTS = {
    "roti", "chapati", "dal", "rice", "chawal", "egg", "eggs", "omelette",
    "chai", "tea", "coffee", "paratha", "paneer", "chicken", "sabzi",
    "salad", "milk", "oats", "banana", "apple", "pizza", "burger", "poha",
    "idli", "dosa", "upma", "shake", "whey", "curd", "dahi", "rajma",
    "chole", "sandwich", "biryani", "wrap", "roll", "khichdi",
}

# B12: auth helper — single-user bot
def _is_authorized(update: Update) -> bool:
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        return True  # not configured — allow all (dev mode)
    return str(update.effective_user.id) == chat_id


# B11: correction state persisted to DB via bot_state (no longer in-memory dict)
_CORRECTION_TTL_SECS = 300  # 5 minutes

def _get_pending_correction() -> dict | None:
    food_id_str = db.get_state("pending_correction_food_id")
    expires_str = db.get_state("pending_correction_expires_at")
    if not food_id_str or not expires_str:
        return None
    if datetime.now() > datetime.fromisoformat(expires_str):
        db.set_state("pending_correction_food_id", "")
        db.set_state("pending_correction_expires_at", "")
        return None
    return {"food_id": int(food_id_str)}

def _set_pending_correction(food_id: int):
    expires = (datetime.now() + timedelta(seconds=_CORRECTION_TTL_SECS)).isoformat()
    db.set_state("pending_correction_food_id", str(food_id))
    db.set_state("pending_correction_expires_at", expires)

def _clear_pending_correction():
    db.set_state("pending_correction_food_id", "")
    db.set_state("pending_correction_expires_at", "")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _bar(current: float, total: float, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    filled = min(int((current / total) * width), width)
    return "█" * filled + "░" * (width - filled)


def _weight_from_text(text: str) -> float | None:
    match = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*kg\b", text.lower())
    if not match:
        stripped = text.strip()
        if re.fullmatch(r"\d{2,3}(?:\.\d+)?", stripped):
            value = float(stripped)
            return value if 40 <= value <= 200 else None
        return None
    value = float(match.group(1))
    return value if 40 <= value <= 200 else None


def _water_from_text(text: str) -> int | None:
    lower = text.lower()
    if not any(word in lower for word in WATER_KEYWORDS):
        return None
    match = re.search(r"\b(\d{1,2})\b", lower)
    if match:
        return max(1, int(match.group(1)))
    if lower in {"water", "pani", "paani", "glass water", "glass pani"}:
        return 1
    return None


def _is_food_question(text: str) -> bool:
    lower = text.lower().strip()
    return "?" in lower or any(lower.startswith(prefix) for prefix in FOOD_QUESTION_PREFIXES)


def _looks_like_yesterday_food_log(text: str) -> bool:
    lower = text.lower().strip()
    if "yesterday" not in lower and "kal" not in lower:
        return False
    return any(word in lower for word in FOOD_HINTS) or any(
        verb in lower for verb in ("khaya", "khaaya", "ate", "had", "piya", "drank")
    )


def _looks_like_food_log(text: str) -> bool:
    lower = text.lower().strip()
    if not lower or "?" in lower:
        return False
    if any(trigger in lower for trigger in SLEEP_TRIGGERS + WAKE_TRIGGERS):
        return False
    if _weight_from_text(lower) is not None or _water_from_text(lower) is not None:
        return False
    food_verbs = ("ate", "had", "khaya", "kha liya", "piya", "drank", "lunch", "dinner", "breakfast")
    if any(verb in lower for verb in food_verbs):
        return True
    words = re.findall(r"[a-zA-Z]+", lower)
    if len(words) <= 8 and any(word in FOOD_HINTS for word in words):
        return True
    if re.match(r"^\d", lower) and len(words) <= 8:
        return True
    return False


def _overage_msg(calories_today: int) -> str:
    over = calories_today - CALORIE_GOAL
    if over <= 300:
        per_meal = over // 2
        return (
            f"📌 You're at {calories_today} kcal — {over} over. "
            f"Subtract ~{per_meal} kcal from tomorrow's Meal 2 and 3. Easy fix."
        )
    return (
        f"📌 Heavy day at {calories_today} kcal. Reset tomorrow. "
        "One day doesn't break 7 months."
    )


def _dashboard_text() -> str:
    t = db.get_today_totals()
    water = db.get_today_water()
    taken = db.get_today_supplements()

    cal, prot, carbs, fat = t["calories"], t["protein"], t["carbs"], t["fat"]

    now = datetime.now()
    ws = datetime.strptime(EATING_WINDOW_START, "%H:%M").replace(
        year=now.year, month=now.month, day=now.day
    )
    we = datetime.strptime(EATING_WINDOW_END, "%H:%M").replace(
        year=now.year, month=now.month, day=now.day
    )
    win_open = ws <= now <= we
    win_emoji = "🟢" if win_open else "🔴"
    win_status = "OPEN" if win_open else "CLOSED"

    prot_warn = " ⚠️" if prot < PROTEIN_GOAL * 0.5 else ""

    lines = [
        f"📊 *Today — {date.today().strftime('%b %d')}*",
        "",
        f"🔥 Calories: {cal} / {CALORIE_GOAL} kcal [{_bar(cal, CALORIE_GOAL)}] {int(cal/CALORIE_GOAL*100)}%",
        f"💪 Protein:  {prot:.0f}g / {PROTEIN_GOAL}g   [{_bar(prot, PROTEIN_GOAL)}] {int(prot/PROTEIN_GOAL*100)}%{prot_warn}",
        f"🍞 Carbs:    {carbs:.0f}g / {CARB_GOAL}g    [{_bar(carbs, CARB_GOAL)}]",
        f"🧈 Fat:      {fat:.0f}g / {FAT_GOAL}g     [{_bar(fat, FAT_GOAL)}]",
        f"💧 Water:    {water} / {WATER_GOAL} glasses  [{_bar(water, WATER_GOAL)}]",
        "",
        f"{win_emoji} Eating window: 1:30 PM – 9:30 PM ({win_status})",
        f"💊 Supplements: {len(taken)} / {len(SUPPLEMENTS)} taken",
    ]

    food_today = db.get_today_food()
    if food_today:
        last = food_today[-1]
        lines.append(f"\n_Last: {last['food_name']} at {last['time']}_")

    return "\n".join(lines)


# ── Scheduled job ──────────────────────────────────────────────────────────────

async def _supplement_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Fires 30 min after first food log. Silenced if sleeping."""
    if db.get_state("is_sleeping") == "1":
        return
    taken = db.get_today_supplements()
    if len(taken) >= len(SUPPLEMENTS):
        return

    taken_lower = [s.lower() for s in taken]
    pending = []
    for s in SUPPLEMENTS:
        if not any(s["name"].lower() in t or t in s["name"].lower() for t in taken_lower):
            timing = s["timing"].lower()
            if any(kw in timing for kw in ("first meal", "morning", "with meal")):
                pending.append(f"• {s['name']} — {s['dose']}")

    if not pending:
        return

    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        return

    msg = "💊 *Supplement reminder* — 30 min since your first meal.\n\nTake now:\n" + "\n".join(pending[:5])
    await context.bot.send_message(chat_id=int(chat_id), text=msg, parse_mode="Markdown")


# ── Auth decorator helper ──────────────────────────────────────────────────────

async def _auth_check(update: Update) -> bool:
    """Returns True if authorized. Silently ignores unauthorized users."""
    if not _is_authorized(update):
        return False
    return True


# ── Commands ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    name = db.get_state("user_name") or "there"
    # If already onboarded AND not being forced to re-run, show quick status
    args = context.args or []
    if name != "there" and "reset" not in args:
        text = (
            f"👋 *Welcome back, {name}!*\n\n"
            f"📋 *Commands:*\n"
            "/today · /log · /weight · /water · /sleep · /progress · /report\n"
            "/help · /supplements · /streak · /goal · /insights\n"
            "/mood · /workout · /measure · /undo · /slept · /woke\n\n"
            "_Use commands for tracking. You can also send a food photo or ask 'kya main X kha sakta hoon?'_\n\n"
            "_To update your name or profile: /start reset_"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
        return
    # New user or explicit reset — start conversational onboarding
    db.set_state("onboarding_step", "name")
    await update.message.reply_text(
        "👋 *Hi! I'm your personal weight loss buddy.*\n\n"
        "I'll track your food, water, sleep, and supplements — and coach you every day.\n\n"
        "Let's get started. *What should I call you, and roughly what do you weigh right now?*\n"
        "_e.g. 'Mohit, 90 kg'_",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    text = (
        "📘 *Core Commands*\n\n"
        "/today - today's calories, protein, water, and supplements\n"
        "/log <food> - log a meal with AI calorie estimate\n"
        "/weight <kg> - log today's weight\n"
        "/water [glasses] - log water, default is 1 glass\n"
        "/sleep <hours> - log last night's sleep duration\n"
        "/progress - weight chart\n"
        "/report - weekly summary\n\n"
        "*Extras*\n"
        "/supplements, /streak, /goal, /insights, /mood, /workout, /measure, /undo\n\n"
        "_Free text still works for simple things like '2 roti aur dal', '89.5 kg', or '3 glass pani'._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    await update.message.reply_text(_dashboard_text(), parse_mode="Markdown")


async def log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: `/log 2 roti aur dal`", parse_mode="Markdown")
        return
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        food_data = await ai.analyze_food_text(text)
        await _process_food(update, context, food_data, raw_text=text)
    except Exception:
        logger.exception("Food analysis failed for /log")
        await update.message.reply_text("Couldn't estimate that meal right now. Try a simpler description.")


async def weight_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    text = " ".join(context.args).strip()
    value = _weight_from_text(text)
    if value is None:
        await update.message.reply_text("Usage: `/weight 89.5 kg`", parse_mode="Markdown")
        return
    db.log_weight(value)
    lost = STARTING_WEIGHT - value
    remaining = value - TARGET_WEIGHT
    await update.message.reply_text(
        f"⚖️ Logged: *{value:.1f} kg*\nLost: {lost:.1f} kg | Remaining: {remaining:.1f} kg",
        parse_mode="Markdown",
    )


async def water_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    text = " ".join(context.args).strip()
    glasses = 1
    if text:
        match = re.search(r"\d+", text)
        if not match:
            await update.message.reply_text("Usage: `/water` or `/water 3`", parse_mode="Markdown")
            return
        glasses = max(1, int(match.group()))
    total = db.log_water(glasses)
    await update.message.reply_text(
        f"💧 Logged {glasses} glass{'es' if glasses != 1 else ''}. Today: *{total}/{WATER_GOAL}*",
        parse_mode="Markdown",
    )


async def sleep_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    text = " ".join(context.args).strip()
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        await update.message.reply_text("Usage: `/sleep 7.5`", parse_mode="Markdown")
        return
    hours = float(match.group())
    db.log_sleep_duration(hours)
    await update.message.reply_text(f"😴 Logged sleep: *{hours:.1f} hours*", parse_mode="Markdown")


async def supplements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    taken = db.get_today_supplements()
    taken_lower = [s.lower() for s in taken]

    lines = ["💊 *Supplement Tracker*\n"]
    for s in SUPPLEMENTS:
        is_taken = any(
            s["name"].lower() in t or t in s["name"].lower() for t in taken_lower
        )
        icon = "✅" if is_taken else "⬜"
        lines.append(f"{icon} *{s['name']}* — {s['dose']}")
        lines.append(f"   ⏰ {s['timing']}")
        lines.append(f"   📝 {s['note']}\n")

    lines += [
        f"\n✅ Taken today: {len(taken)} / {len(SUPPLEMENTS)}\n",
        "⏱ *Realistic results timeline:*",
        "• ⚡ Energy — 2–4 weeks (D3 + B12)",
        "• ✨ Skin glow — 4–6 weeks (Omega-3 + Zinc)",
        "• 💇 Hair fall REDUCTION — 8–12 weeks",
        "• 💅 Nails + hair thickness — 3–5 months",
        "• 🧔 Beard patches — 3–6 months",
        "",
        "_Quitting early is the #1 mistake. Results happen inside before they show outside._",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    history = db.get_weight_history(30)
    if not history:
        await update.message.reply_text("No weight logged yet. Just type your weight: *90.2 kg*", parse_mode="Markdown")
        return

    chart_bytes = charts.generate_weight_chart(history, target_weight=TARGET_WEIGHT)
    current = history[-1]["weight"]
    lost = STARTING_WEIGHT - current
    remaining = current - TARGET_WEIGHT

    caption = (
        f"📊 *{current} kg*  |  Lost: {lost:.1f} kg  |  {remaining:.1f} kg to goal"
    )
    await update.message.reply_photo(
        photo=chart_bytes, caption=caption, parse_mode="Markdown"
    )


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    stats = db.get_weekly_stats()
    streak = db.get_streak()
    sleep_history = db.get_sleep_history(7)

    lines = ["📈 *Weekly Report*\n"]
    lines.append(f"🔥 Avg calories: {stats['avg_calories']} kcal/day (goal: {CALORIE_GOAL})")
    lines.append(f"💪 Avg protein: {stats['avg_protein']}g/day (goal: {PROTEIN_GOAL}g)")

    if stats["weight_change"] is not None:
        emoji = "📉" if stats["weight_change"] < 0 else "📈"
        lines.append(
            f"{emoji} Weight: {stats['weight_start']} → {stats['weight_end']} kg "
            f"({stats['weight_change']:+.1f} kg)"
        )

    if sleep_history:
        lines.append("\n😴 *Sleep log (last 7 days):*")
        for entry in sleep_history[-7:]:
            if entry.get("hours") is not None:
                lines.append(f"  {entry['date']}: {entry['hours']:.1f} hours")
                continue
            wake = entry["wake_time"] or "—"
            sleep = entry["sleep_time"] or "—"
            lines.append(f"  {entry['date']}: slept {sleep}, woke {wake}")

    lines.append(f"\n🔥 Streak: {streak} days")

    if stats["avg_protein"] < PROTEIN_GOAL * 0.7:
        lines.append(
            f"\n⚠️ Protein avg ({stats['avg_protein']}g) is below target. "
            "Add: eggs, paneer, chicken, dal."
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def streak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    s = db.get_streak()
    if s == 0:
        msg = "No streak yet. Log your first meal to start the streak."
    elif s < 3:
        msg = f"🔥 *{s}-day streak.* Keep going."
    elif s < 7:
        msg = f"🔥 *{s}-day streak!* Don't break it now."
    elif s < 30:
        msg = f"🔥🔥 *{s}-day streak!* You're in a groove."
    else:
        msg = f"🏆 *{s}-day streak!* Legendary consistency."
    await update.message.reply_text(msg, parse_mode="Markdown")


async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    text = (
        "📋 *Your 90-Day Plan*\n\n"
        "🎯 *Goal: 90 kg → 70 kg in 7 months*\n\n"
        "*Phase 1 (Months 1–2): Fix deficiencies + habits*\n"
        "• All 8 supplements daily\n"
        "• 1500 kcal/day, 150g protein\n"
        "• 14 glasses water\n"
        "• Sleep: push back 30 min every 3 days\n\n"
        "*Phase 2 (Months 3–4): Add movement*\n"
        "• 30-min walk daily\n"
        "• Bodyweight exercises 3×/week\n\n"
        "*Phase 3 (Months 5–7): Accelerate*\n"
        "• Increase protein to 160g\n"
        "• Track measurements (waist, arms)\n\n"
        "*Eating window: 1:30 PM – 9:30 PM*\n\n"
        "✅ *Fasting-safe items (zero budget impact):*\n"
        "• Black coffee (5 kcal)\n"
        "• Green tea (2 kcal)\n"
        "• Chaach/buttermilk (50 kcal)\n"
        "• Cucumber (16 kcal)\n"
        "• Water (0 kcal)"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def slept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    db.log_sleep()
    db.set_state("is_sleeping", "1")
    await update.message.reply_text("😴 Sleep logged. Good night. I'll be quiet until you wake up.")


async def woke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    db.log_wake()
    db.set_state("is_sleeping", "0")
    db.set_state("first_food_today", "")
    await _send_morning_summary(update.message, context)


# ── Morning summary ────────────────────────────────────────────────────────────

async def _send_morning_summary(message_or_none, context: ContextTypes.DEFAULT_TYPE):
    name = db.get_state("user_name") or "there"
    weight = db.get_latest_weight()
    avg = db.get_7day_weight_average()
    water = db.get_today_water()
    streak_val = db.get_streak()
    t = db.get_today_totals()

    text = (
        f"☀️ *Good morning, {name}!*\n\n"
        f"📊 *Quick status:*\n"
        f"• Latest weight: {weight} kg"
    )
    if avg:
        text += f" _(7-day avg: {avg} kg)_"
    text += (
        f"\n• Today's calories logged: {t['calories']} kcal\n"
        f"• Water so far: {water} / {WATER_GOAL} glasses\n"
        f"• Streak: 🔥 {streak_val} days\n\n"
        f"🎯 *Today's targets:*\n"
        f"• {CALORIE_GOAL} kcal · {PROTEIN_GOAL}g protein · {WATER_GOAL} glasses water\n"
        f"• Eating window opens at 1:30 PM\n\n"
        f"💊 Take supplements with your first meal."
    )

    if message_or_none:
        await message_or_none.reply_text(text, parse_mode="Markdown")
    else:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if chat_id:
            await context.bot.send_message(
                chat_id=int(chat_id), text=text, parse_mode="Markdown"
            )


# ── New commands ───────────────────────────────────────────────────────────────

async def goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    weight = db.get_latest_weight()
    lost = STARTING_WEIGHT - weight
    remaining = weight - TARGET_WEIGHT
    pct = int((lost / (STARTING_WEIGHT - TARGET_WEIGHT)) * 100)
    text = (
        f"🎯 *Your Goals*\n\n"
        f"🔥 Calories: {CALORIE_GOAL} kcal/day\n"
        f"💪 Protein: {PROTEIN_GOAL}g/day\n"
        f"💧 Water: {WATER_GOAL} glasses/day\n"
        f"⏰ Eating window: 1:30 PM – 9:30 PM\n\n"
        f"⚖️ *Weight progress:*\n"
        f"Start: {STARTING_WEIGHT} kg → Current: {weight} kg → Target: {TARGET_WEIGHT} kg\n"
        f"Lost: {lost:.1f} kg | Remaining: {remaining:.1f} kg\n"
        f"Progress: {_bar(lost, STARTING_WEIGHT - TARGET_WEIGHT)} {pct}%"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def mood_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    args = context.args
    if not args:
        keyboard = [[InlineKeyboardButton(str(i), callback_data=f"mood_{i}") for i in range(1, 6)],
                    [InlineKeyboardButton(str(i), callback_data=f"mood_{i}") for i in range(6, 11)]]
        await update.message.reply_text(
            "How are you feeling today? (1 = terrible, 10 = amazing)",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return
    try:
        score = int(args[0])
        note = " ".join(args[1:]) if len(args) > 1 else ""
        db.log_mood(score, note)
        emoji = "😊" if score >= 7 else "😐" if score >= 4 else "😔"
        await update.message.reply_text(f"{emoji} Mood {score}/10 logged.")
    except ValueError:
        await update.message.reply_text("Usage: /mood 7 (optional note)")


async def workout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/workout walk 45` or `/workout gym 60`\n"
            "Types: walk, run, gym, yoga, cycling, swim, other",
            parse_mode="Markdown",
        )
        return
    workout_type = args[0].lower()
    try:
        duration = int(args[1])
    except ValueError:
        await update.message.reply_text("Duration must be a number of minutes.")
        return
    # Estimate calories burned
    burn_rates = {"walk": 5, "run": 10, "gym": 7, "yoga": 3, "cycling": 8, "swim": 9}
    burn = duration * burn_rates.get(workout_type, 5)
    db.log_workout(workout_type, duration, burn)
    t = db.get_today_totals()
    total_burn = db.get_today_workout_burn()
    effective_deficit = CALORIE_GOAL - int(t["calories"]) + total_burn
    await update.message.reply_text(
        f"💪 *{workout_type.capitalize()}* — {duration} min, ~{burn} kcal burned\n"
        f"Today's effective deficit: {effective_deficit} kcal",
        parse_mode="Markdown",
    )


async def measure_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    await update.message.reply_text(
        "📏 Log your measurements.\nReply with: `waist chest arms` in cm\n"
        "_e.g. '86 92 34'_",
        parse_mode="Markdown",
    )
    db.set_state("awaiting_measurements", "1")


async def deficit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    t = db.get_today_totals()
    cal = int(t["calories"])
    burn = db.get_today_workout_burn()
    deficit = CALORIE_GOAL - cal + burn
    remaining = max(CALORIE_GOAL - cal, 0)
    msg = (
        f"📉 *Today's Deficit*\n\n"
        f"Calories eaten: {cal} kcal\n"
        f"Workout burn: +{burn} kcal\n"
        f"Goal: {CALORIE_GOAL} kcal\n\n"
        f"Net deficit: *{deficit} kcal*"
    )
    if remaining > 0:
        msg += f"\nCalories remaining: {remaining} kcal"
    if deficit > 0:
        weekly_fat = round(deficit * 7 / 7700, 2)
        msg += f"\n\n_At this rate: ~{weekly_fat} kg fat loss this week_"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def fasting_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    duration_mins = db.get_current_fast_duration()
    if duration_mins is None:
        db.start_fast()
        await update.message.reply_text("⏱ Fast started. I'll track it for you.")
    else:
        hours = duration_mins // 60
        mins = duration_mins % 60
        window_opens_in = max(0, 16 * 60 - duration_mins)
        wh, wm = window_opens_in // 60, window_opens_in % 60
        await update.message.reply_text(
            f"⏱ *Fasting: {hours}h {mins}m*\n"
            f"Eating window opens in {wh}h {wm}m\n\n"
            "_Type /fasting again to end the fast_",
            parse_mode="Markdown",
        )


async def insights_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    stats = db.get_weekly_stats()
    adherence = db.get_weekly_adherence_score()
    weekly_data = {**stats, "adherence": adherence}
    import memory as mem
    mem_ctx = mem.get_context_for_prompt("general")
    try:
        insights = await ai.generate_insights(weekly_data, mem_ctx)
        await update.message.reply_text(f"🧠 *Weekly Insights*\n\n{insights}", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Couldn't generate insights right now. Try again later.")


async def milestones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    all_milestones = db.get_milestones()
    if not all_milestones:
        await update.message.reply_text(
            "No milestones yet. Keep logging — your first one is coming!\n"
            "_Tip: log your weight to start tracking progress._"
        )
        return
    lines = ["🏆 *Your Milestones*\n"]
    type_emoji = {"weight": "⚖️", "streak": "🔥", "protein": "💪", "water": "💧"}
    for m in all_milestones:
        emoji = type_emoji.get(m["type"], "🎯")
        lines.append(f"{emoji} {m['message']} — _{m['date']}_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def undo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    food = db.get_today_food()
    if not food:
        await update.message.reply_text("Nothing logged today to undo.")
        return
    last = food[-1]
    keyboard = [[
        InlineKeyboardButton("Yes, remove it", callback_data=f"undo_{last['id']}"),
        InlineKeyboardButton("Keep it", callback_data="undo_cancel"),
    ]]
    await update.message.reply_text(
        f"Remove the last entry?\n*{last['food_name']}* — {last['calories']} kcal at {last['time']}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Food processing ────────────────────────────────────────────────────────────

async def _process_food(update: Update, context: ContextTypes.DEFAULT_TYPE, food_data: dict, raw_text: str = ""):
    """Shared logic for text + photo food logging."""
    is_restaurant = food_data.get("is_restaurant", False)
    cal = food_data.get("calories", 0)
    protein = food_data.get("protein", 0.0)
    carbs = food_data.get("carbs", 0.0)
    fat = food_data.get("fat", 0.0)
    food_name = food_data.get("food_name", "Unknown food")
    components = food_data.get("components", [])
    serving_notes = food_data.get("serving_notes") or food_data.get("portion_notes", "")
    confidence = food_data.get("confidence", "medium")

    buffer_note = ""
    if is_restaurant:
        original_cal = cal
        cal = int(cal * 1.2)
        buffer_note = f"\n_+20% restaurant buffer: {original_cal} → {cal} kcal_"

    food_id = db.log_food(food_name, cal, protein, carbs, fat, is_restaurant, raw_text)

    # First food of day → schedule supplement reminder
    if not db.get_state("first_food_today"):
        db.set_state("first_food_today", datetime.now().isoformat())
        context.job_queue.run_once(
            _supplement_reminder_job,
            when=30 * 60,
            name="supplement_reminder",
        )

    totals = db.get_today_totals()

    conf_icon = {"high": "✅", "medium": "📊", "low": "🔍"}.get(confidence, "📊")

    lines = [f"{conf_icon} *{food_name}*"]
    if components:
        lines.append(f"_{', '.join(components)}_")
    if serving_notes:
        lines.append(f"_{serving_notes}_")
    lines.append("")
    lines.append(
        f"🔥 {cal} kcal  |  💪 {protein:.0f}g protein  |  🍞 {carbs:.0f}g carbs  |  🧈 {fat:.0f}g fat"
    )
    lines.append(buffer_note)
    lines.append("")
    lines.append(f"📊 *Today: {totals['calories']} / {CALORIE_GOAL} kcal*")
    lines.append(f"💪 Protein: {totals['protein']:.0f}g / {PROTEIN_GOAL}g")

    # B7: eating window violation warning
    now = datetime.now()
    ws = datetime.strptime(EATING_WINDOW_START, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
    we = datetime.strptime(EATING_WINDOW_END, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
    if not (ws <= now <= we):
        lines.append("\n⚠️ _Eating window is closed. This breaks your fast — logged anyway._")

    if totals["protein"] < PROTEIN_GOAL * 0.4 and totals["calories"] > CALORIE_GOAL * 0.4:
        lines.append("⚠️ Protein is low. Next meal: eggs, paneer, chicken, dal.")

    # Caloric floor alert
    if totals["calories"] < 1200 and now > we:
        lines.append("\n⚠️ _You've eaten very little today. Make sure you're not undereating._")

    if totals["calories"] > 2100:
        lines.append("")
        lines.append(_overage_msg(int(totals["calories"])))
    elif totals["calories"] > CALORIE_GOAL:
        lines.append("")
        lines.append(_overage_msg(int(totals["calories"])))

    keyboard = [[
        InlineKeyboardButton("✅ Correct", callback_data=f"ok_{food_id}"),
        InlineKeyboardButton("✏️ Fix", callback_data=f"fix_{food_id}"),
    ]]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Message handlers ───────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        food_data = await ai.analyze_food_photo(bytes(photo_bytes))  # B10: await
        await _process_food(update, context, food_data, raw_text="photo")
    except Exception:
        logger.exception("Photo analysis failed")
        await update.message.reply_text(
            "Photo analysis failed. Describe what you ate instead: e.g. *dal chawal, 1 plate*",
            parse_mode="Markdown",
        )


async def _execute_actions(update: Update, context: ContextTypes.DEFAULT_TYPE, actions: list[dict]):
    """Execute actions returned by the AI (log food, water, weight, etc.)."""
    from datetime import date as _date, timedelta as _td
    yesterday = (_date.today() - _td(days=1)).isoformat()

    for action in actions:
        atype = action.get("type", "")
        try:
            if atype == "log_food":
                food_id = db.log_food(
                    action.get("food_name", "Unknown"),
                    int(action.get("calories", 0)),
                    float(action.get("protein", 0)),
                    float(action.get("carbs", 0)),
                    float(action.get("fat", 0)),
                    bool(action.get("is_restaurant", False)),
                )
                # First food of day → schedule supplement reminder
                if not db.get_state("first_food_today"):
                    db.set_state("first_food_today", datetime.now().isoformat())
                    context.job_queue.run_once(_supplement_reminder_job, when=1800)
                # Milestone check
                import milestones as _m
                t = db.get_today_totals()
                if int(t["calories"]) > 2100:  # cheat day threshold
                    pass  # AI already handles this in its reply

            elif atype == "log_food_past":
                log_date = action.get("date", yesterday)
                # Validate date — AI sometimes returns placeholder strings
                try:
                    from datetime import date as _d
                    _d.fromisoformat(str(log_date))
                except (ValueError, TypeError):
                    log_date = yesterday
                db.log_food(
                    action.get("food_name", "Unknown"),
                    int(action.get("calories", 0)),
                    float(action.get("protein", 0)),
                    float(action.get("carbs", 0)),
                    float(action.get("fat", 0)),
                    bool(action.get("is_restaurant", False)),
                    for_date=log_date,
                )

            elif atype == "log_water":
                db.log_water(int(action.get("glasses", 0)))

            elif atype == "log_weight":
                w = float(action.get("weight", 0))
                if 40 <= w <= 200:
                    db.log_weight(w)
                    import milestones as _m
                    _m.check_weight_milestone(w)

            elif atype == "log_supplement":
                db.log_supplement(action.get("name", ""))

            elif atype == "log_sleep":
                db.log_sleep()
                db.set_state("is_sleeping", "1")

            elif atype == "log_wake":
                db.log_wake()
                db.set_state("is_sleeping", "0")
                db.set_state("first_food_today", "")

        except Exception as e:
            logger.warning(f"Action {atype} failed: {e}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth_check(update):
        return

    text = update.message.text.strip()
    text_lower = text.lower()

    pending_correction = _get_pending_correction()
    if pending_correction:
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        try:
            food_data = await ai.analyze_food_text(text)
            db.update_food_correction(
                pending_correction["food_id"],
                food_data.get("food_name", "Corrected food"),
                int(food_data.get("calories", 0)),
                float(food_data.get("protein", 0)),
                float(food_data.get("carbs", 0)),
                float(food_data.get("fat", 0)),
            )
            _clear_pending_correction()
            await update.message.reply_text(
                f"✏️ Updated entry to *{food_data.get('food_name', 'Corrected food')}* — "
                f"{int(food_data.get('calories', 0))} kcal",
                parse_mode="Markdown",
            )
        except Exception:
            logger.exception("Food correction failed")
            await update.message.reply_text("Couldn't update that entry right now. Try again in a simpler format.")
        return

    # ── Awaiting measurements (/measure command) — keep as structured input ──
    if db.get_state("awaiting_measurements") == "1":
        parts = text_lower.split()
        nums = [float(p) for p in parts if p.replace(".", "").isdigit()]
        if len(nums) >= 3:
            db.log_measurement(waist=nums[0], chest=nums[1], arms=nums[2])
            db.set_state("awaiting_measurements", "")
            await update.message.reply_text(
                f"📏 Logged — Waist: {nums[0]} cm | Chest: {nums[1]} cm | Arms: {nums[2]} cm"
            )
            return
        elif nums:
            await update.message.reply_text("Need 3 numbers: waist chest arms. e.g. '86 92 34'")
            return
        else:
            db.set_state("awaiting_measurements", "")

    # ── Onboarding ── (only runs once for new users)
    onboarding_step = db.get_state("onboarding_step")
    if onboarding_step:
        if await _handle_onboarding(update, context, text, onboarding_step):
            return

    # ── Show typing indicator ──
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    # ── Save user message to history ──
    db.save_message("user", text)
    weight = _weight_from_text(text)
    if weight is not None:
        db.log_weight(weight)
        reply = (
            f"⚖️ Logged: *{weight:.1f} kg*\n"
            f"Lost: {STARTING_WEIGHT - weight:.1f} kg | Remaining: {weight - TARGET_WEIGHT:.1f} kg"
        )
        await update.message.reply_text(reply, parse_mode="Markdown")
        db.save_message("assistant", reply)
        return

    water = _water_from_text(text)
    if water is not None:
        total = db.log_water(water)
        reply = f"💧 Logged {water} glass{'es' if water != 1 else ''}. Today: *{total}/{WATER_GOAL}*"
        await update.message.reply_text(reply, parse_mode="Markdown")
        db.save_message("assistant", reply)
        return

    if any(trigger in text_lower for trigger in SLEEP_TRIGGERS):
        db.log_sleep()
        db.set_state("is_sleeping", "1")
        reply = "😴 Sleep logged. Good night."
        await update.message.reply_text(reply)
        db.save_message("assistant", reply)
        return

    if any(trigger in text_lower for trigger in WAKE_TRIGGERS):
        db.log_wake()
        db.set_state("is_sleeping", "0")
        db.set_state("first_food_today", "")
        await _send_morning_summary(update.message, context)
        return

    if _looks_like_yesterday_food_log(text):
        try:
            food_data = await ai.analyze_food_text(text)
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            db.log_food(
                food_data.get("food_name", "Yesterday meal"),
                int(food_data.get("calories", 0)),
                float(food_data.get("protein", 0)),
                float(food_data.get("carbs", 0)),
                float(food_data.get("fat", 0)),
                bool(food_data.get("is_restaurant", False)),
                raw_text=text,
                for_date=yesterday,
            )
            reply = f"🗓 Logged for yesterday: *{food_data.get('food_name', 'Meal')}*"
            await update.message.reply_text(reply, parse_mode="Markdown")
            db.save_message("assistant", reply)
            return
        except Exception:
            logger.exception("Yesterday food analysis failed")

    if _is_food_question(text):
        totals = db.get_today_totals()
        remaining_calories = max(CALORIE_GOAL - int(totals["calories"]), 0)
        remaining_protein = max(PROTEIN_GOAL - int(totals["protein"]), 0)
        try:
            result = await ai.check_food_safety(text, remaining_calories, remaining_protein)
            status = "✅ Fits today" if result.get("is_safe") else "⚠️ Use caution"
            lines = [
                f"{status}: *{result.get('food', 'That food')}*",
                f"Estimated: {result.get('estimated_calories', 0)} kcal, {result.get('estimated_protein', 0)}g protein",
                result.get("reason", ""),
                result.get("recommendation", ""),
            ]
            alternatives = result.get("alternatives", [])[:3]
            if alternatives:
                lines.append("")
                lines.append("*Better options:*")
                for alt in alternatives:
                    lines.append(
                        f"• {alt.get('name', 'Option')} — {alt.get('calories', 0)} kcal, "
                        f"{alt.get('protein', 0)}g protein"
                    )
            reply = "\n".join(line for line in lines if line)
            await update.message.reply_text(reply, parse_mode="Markdown")
            db.save_message("assistant", reply)
            return
        except Exception:
            logger.exception("Food safety check failed")

    if _looks_like_food_log(text):
        try:
            food_data = await ai.analyze_food_text(text)
            await _process_food(update, context, food_data, raw_text=text)
            return
        except Exception:
            logger.exception("Text food analysis failed")

    t = db.get_today_totals()
    user_ctx = {
        "name": db.get_state("user_name") or "",
        "calories_today": int(t["calories"]),
        "protein_today": int(t["protein"]),
        "water_today": db.get_today_water(),
        "streak": db.get_streak(),
        "weight": db.get_latest_weight(),
    }
    try:
        reply = await ai.general_chat(text, user_ctx)
    except Exception:
        logger.exception("general_chat failed")
        reply = "Use /log, /weight, /water, /sleep, or /today."
    await update.message.reply_text(reply)
    db.save_message("assistant", reply)


# ── Onboarding helpers ─────────────────────────────────────────────────────────

_SKIP_WORDS = ("skip", "baad mein", "later", "abhi nahi", "nahi", "cancel")



# ── Onboarding flow ────────────────────────────────────────────────────────────

async def _handle_onboarding(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, step: str
) -> bool:
    """Handle one onboarding step. Returns True if message was consumed, False to fall through."""
    text_lower = text.lower()

    # Universal skip — user can bail out of onboarding at any point
    if any(w in text_lower for w in _SKIP_WORDS):
        db.set_state("onboarding_step", "")
        name = db.get_state("user_name") or ""
        msg = f"No worries, {name}! " if name else "No worries! "
        await update.message.reply_text(
            msg + "You can chat normally now. I'll finish setup when you're ready.",
            parse_mode="Markdown",
        )
        return True

    if step == "name":
        weight_match = re.search(r"\b(\d{2,3}(?:\.\d)?)\s*kg\b", text_lower)
        name = await ai.extract_name(text)
        db.set_state("user_name", name)
        if weight_match:
            w = float(weight_match.group(1))
            db.log_weight(w)
            db.set_state("onboarding_step", "diet")
            await update.message.reply_text(
                f"Nice to meet you, *{name}!* {w} kg noted — {w - TARGET_WEIGHT:.0f} kg to go.\n\n"
                "Are you *vegetarian*, or do you eat everything (eggs, chicken, etc.)?",
                parse_mode="Markdown",
            )
        else:
            db.set_state("onboarding_step", "weight")
            await update.message.reply_text(
                f"Nice to meet you, *{name}!*\n\nWhat do you weigh right now? _(e.g. 90 kg)_",
                parse_mode="Markdown",
            )
        return True

    elif step == "weight":
        weight_match = re.search(r"\b(\d{2,3}(?:\.\d)?)\s*kg?\b", text_lower)
        if weight_match:
            w = float(weight_match.group(1))
            db.log_weight(w)
            db.set_state("onboarding_step", "diet")
            name = db.get_state("user_name") or "there"
            await update.message.reply_text(
                f"Got it — {w} kg. {w - TARGET_WEIGHT:.0f} kg to your goal.\n\n"
                "Are you *vegetarian*, or do you eat everything?",
                parse_mode="Markdown",
            )
            return True
        else:
            # No number — let the message fall through to normal handling
            return False

    elif step == "diet":
        if any(w in text_lower for w in ("veg", "vegetarian", "no meat", "no chicken", "paneer", "sabzi")):
            diet = "vegetarian"
        elif any(w in text_lower for w in ("non", "chicken", "egg", "meat", "fish", "everything", "sab")):
            diet = "non-vegetarian"
        else:
            # Unclear answer — fall through to normal handling
            return False
        db.set_state("user_diet", diet)
        db.set_state("onboarding_step", "wake_time")
        await update.message.reply_text(
            f"Got it — *{diet}*. I'll suggest only appropriate meals.\n\n"
            "What time do you usually wake up? _(e.g. 7 AM, 8:30)_",
            parse_mode="Markdown",
        )
        return True

    elif step == "wake_time":
        time_match = re.search(r"\b(\d{1,2}(?::\d{2})?)\s*(?:am|pm|baje)?\b", text_lower)
        if time_match:
            db.set_state("user_wake_time", text.strip())
            db.set_state("onboarding_step", "motivation")
            await update.message.reply_text(
                "Perfect — I'll adjust my check-ins to match your schedule.\n\n"
                "Last question: *what's your main reason for starting today?*\n"
                "_I'll use this to motivate you on hard days._",
                parse_mode="Markdown",
            )
            return True
        else:
            return False

    elif step == "motivation":
        db.set_state("user_motivation", text.strip())
        db.set_state("onboarding_step", "")
        name = db.get_state("user_name") or "there"
        await update.message.reply_text(
            f"All set, *{name}!* Your goal is locked in.\n\n"
            "I'll check in 3 times a day. Say *'less messages'* anytime if that's too much.\n\n"
            "📌 _This journey takes 9–12 months at a healthy pace. Every logged meal is a step forward._\n\n"
            "To start: *tell me what you had for your last meal.*",
            parse_mode="Markdown",
        )
        return True

    return False


# ── Callback handler ───────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("ok_"):
        await query.edit_message_reply_markup(reply_markup=None)

    elif data.startswith("fix_"):
        food_id = int(data.split("_")[1])
        _set_pending_correction(food_id)  # B11: persist to DB
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "✏️ Tell me what it actually was:\n_e.g. '2 rotis and dal, no butter'_",
            parse_mode="Markdown",
        )

    elif data.startswith("recipe_"):
        # recipe_<cal>_<protein>_<carbs>_<fat>_<name>
        parts = data.split("_", 6)
        try:
            cal, protein, carbs, fat, name = int(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]), parts[5]
            food_id = db.log_food(name, cal, protein, carbs, fat, False, "recipe")
            await query.edit_message_reply_markup(reply_markup=None)
            t = db.get_today_totals()
            await query.message.reply_text(
                f"✅ *{name}* logged — {cal} kcal, {protein:.0f}g protein\n"
                f"📊 Today: {t['calories']} / {CALORIE_GOAL} kcal",
                parse_mode="Markdown",
            )
        except Exception:
            await query.message.reply_text("Couldn't log that recipe. Try typing the meal name instead.")

    elif data.startswith("undo_"):
        food_id = int(data.split("_")[1])
        today_food = db.get_today_food()
        entry = next((f for f in today_food if f["id"] == food_id), None)
        if entry:
            db.delete_food_log(food_id)
            t = db.get_today_totals()
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"✅ Removed *{entry['food_name']}* ({entry['calories']} kcal)\n"
                f"📊 Today: {t['calories']} / {CALORIE_GOAL} kcal",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("Entry not found — may have already been removed.")

    elif data == "undo_cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Kept.")

    elif data.startswith("mood_"):
        score = int(data.split("_")[1])
        db.log_mood(score)
        emoji = "😊" if score >= 7 else "😐" if score >= 4 else "😔"
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"{emoji} Mood {score}/10 logged.")
