"""
Scheduler — all proactive daily jobs.
All jobs check is_sleeping state and notification preferences before sending.
Weekend jobs shift 90 minutes later.
"""
import os
import logging
import datetime as dt

from telegram.ext import Application, ContextTypes

import db
import ai
import memory
import milestones
import charts
from config import (
    CALORIE_GOAL, PROTEIN_GOAL, WATER_GOAL, TARGET_WEIGHT, STARTING_WEIGHT,
    SUPPLEMENTS,
)

logger = logging.getLogger(__name__)


def _chat_id() -> int | None:
    cid = os.getenv("TELEGRAM_CHAT_ID")
    return int(cid) if cid else None


def _is_paused() -> bool:
    paused_until = db.get_state("notifications_paused_until")
    if not paused_until:
        return False
    try:
        return dt.datetime.now() < dt.datetime.fromisoformat(paused_until)
    except ValueError:
        return False


def _notification_level() -> str:
    return db.get_state("notification_level") or "normal"


async def _send(context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode: str = "Markdown"):
    chat_id = _chat_id()
    if not chat_id:
        return
    if db.get_state("is_sleeping") == "1":
        return
    if _is_paused():
        return
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)


# ── Job 1: Midnight reset (00:01) ─────────────────────────────────────────────

async def midnight_reset(context: ContextTypes.DEFAULT_TYPE):
    db.set_state("first_food_today", "")
    # Auto-start fasting session at midnight if window is closed
    db.start_fast()
    logger.info("Midnight reset done")


# ── Job 2: Morning greeting ───────────────────────────────────────────────────

async def morning_greeting(context: ContextTypes.DEFAULT_TYPE):
    chat_id = _chat_id()
    if not chat_id or _is_paused():
        return

    weight = db.get_latest_weight()
    avg = db.get_7day_weight_average()
    streak = db.get_streak()
    name = db.get_state("user_name") or "there"

    lost = STARTING_WEIGHT - weight
    remaining = weight - TARGET_WEIGHT

    msg = (
        f"☀️ *Good morning, {name}!*\n\n"
        f"📊 *Quick status:*\n"
        f"• Current weight: {weight} kg"
    )
    if avg:
        msg += f" _(7-day avg: {avg} kg)_"
    msg += (
        f"\n• Lost so far: {lost:.1f} kg | {remaining:.1f} kg to go"
        f"\n• Streak: 🔥 {streak} days\n\n"
        f"🎯 *Today's targets:*\n"
        f"• {CALORIE_GOAL} kcal · {PROTEIN_GOAL}g protein · {WATER_GOAL} glasses water\n"
        f"• Eating window opens at *1:30 PM*\n\n"
        f"💊 Take supplements with your first meal."
    )

    # Plateau check
    if db.is_plateau(days=5):
        msg += (
            "\n\n⚠️ *Weight has been stable for 5 days.* This is a plateau.\n"
            "Try: drink an extra 4 glasses of water, add a 15-min walk today, "
            "or try a refeed day (eat up to 1800 kcal — mostly carbs)."
        )

    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")


# ── Job 3: Eating window opens (1:25 PM) ──────────────────────────────────────

async def window_opening(context: ContextTypes.DEFAULT_TYPE):
    if _notification_level() == "low":
        return
    await _send(context, "🍽 *Eating window opens in 5 min* (1:30 PM). Plan your first meal!")


# ── Job 4: Midday check-in (1:30 PM) — only if nothing logged ────────────────

async def midday_checkin(context: ContextTypes.DEFAULT_TYPE):
    if _notification_level() == "low":
        return
    food = db.get_today_food()
    if not food:
        await _send(
            context,
            "📋 Haven't seen your first meal yet. What did you eat today?\n"
            "_Just type it — e.g. 'dal chawal, 1 plate'_"
        )


# ── Job 5: 9 PM — 30 min window warning + protein check ──────────────────────

async def window_closing_warning(context: ContextTypes.DEFAULT_TYPE):
    t = db.get_today_totals()
    cal = int(t["calories"])
    prot = int(t["protein"])

    msg = f"⏰ *30 min left in eating window* (closes at 9:30 PM)\n\n"
    msg += f"🔥 Calories: {cal} / {CALORIE_GOAL} kcal\n"
    msg += f"💪 Protein: {prot}g / {PROTEIN_GOAL}g\n"

    protein_gap = PROTEIN_GOAL - prot
    if protein_gap > 30:
        msg += (
            f"\n⚠️ *You need {protein_gap}g more protein before 9:30 PM!*\n"
            f"Quick options: 3 eggs ({protein_gap // 2}g), 100g paneer (18g), "
            f"or a whey shake (25g)"
        )

    # Magnesium reminder (B6 fix)
    taken = db.get_today_supplements()
    taken_lower = [s.lower() for s in taken]
    mag_taken = any("magnesium" in t for t in taken_lower)
    if not mag_taken:
        msg += "\n\n💊 *Don't forget Magnesium Glycinate* — take 30 min before sleep."

    await _send(context, msg)


# ── Job 6: 9:30 PM — window closed + fasting started ────────────────────────

async def window_closed(context: ContextTypes.DEFAULT_TYPE):
    t = db.get_today_totals()
    cal = int(t["calories"])
    prot = int(t["protein"])
    water = db.get_today_water()

    db.start_fast()

    grade = "✅ Great day" if cal <= CALORIE_GOAL and prot >= PROTEIN_GOAL * 0.8 else "📋 Day logged"
    msg = (
        f"🌙 *Eating window closed.* Fast started.\n\n"
        f"{grade}:\n"
        f"• Calories: {cal} / {CALORIE_GOAL} kcal\n"
        f"• Protein: {prot}g / {PROTEIN_GOAL}g\n"
        f"• Water: {water} / {WATER_GOAL} glasses\n\n"
        f"⏱ Next window opens at *1:30 PM tomorrow* (16 hours)."
    )

    # Caloric floor check
    if cal < 1200:
        msg += f"\n\n⚠️ _Only {cal} kcal today — that's too low. Undereating slows metabolism._"

    await _send(context, msg)


# ── Job 7: 10 PM — nightly AI coaching ───────────────────────────────────────

async def nightly_coaching(context: ContextTypes.DEFAULT_TYPE):
    if _notification_level() == "low":
        return
    t = db.get_today_totals()
    water = db.get_today_water()
    streak = db.get_streak()
    weight = db.get_latest_weight()

    day_data = {
        "calories": int(t["calories"]),
        "protein": int(t["protein"]),
        "water_glasses": water,
        "streak": streak,
        "weight": weight,
        "calorie_goal": CALORIE_GOAL,
        "protein_goal": PROTEIN_GOAL,
    }
    mem_ctx = memory.get_context_for_prompt("general")

    try:
        msg = await ai.generate_nightly_coaching(day_data, mem_ctx)
        await _send(context, f"🌙 {msg}")
    except Exception:
        logger.exception("Nightly coaching failed")


# ── Job 8: Water nudge (every 2 hours, 1–9 PM, max twice/day) ───────────────

_water_nudge_count_today = {"date": "", "count": 0}

async def water_nudge(context: ContextTypes.DEFAULT_TYPE):
    if _notification_level() == "low":
        return
    today = str(db.date.today())
    if _water_nudge_count_today["date"] != today:
        _water_nudge_count_today["date"] = today
        _water_nudge_count_today["count"] = 0

    if _water_nudge_count_today["count"] >= 2:
        return

    water = db.get_today_water()
    if water >= 8:
        return

    _water_nudge_count_today["count"] += 1
    remaining = WATER_GOAL - water
    await _send(
        context,
        f"💧 *Water check:* {water}/{WATER_GOAL} glasses so far.\n"
        f"_{remaining} more to go. Just type '2 glass pani piya' to log._"
    )


# ── Job 9: Streak protection (8 PM, only if streak > 3) ─────────────────────

async def streak_protection(context: ContextTypes.DEFAULT_TYPE):
    streak = db.get_streak()
    if streak < 3:
        return
    food = db.get_today_food()
    if not food:
        await _send(
            context,
            f"⚠️ *Your {streak}-day streak is at risk!*\n"
            "You haven't logged anything today. "
            "Log something quick to save it — even a glass of chai counts."
        )


# ── Job 10: Weight log reminder (8 AM, if no weight in 2 days) ───────────────

async def weight_reminder(context: ContextTypes.DEFAULT_TYPE):
    history = db.get_weight_history(3)
    if not history:
        await _send(context, "⚖️ Log your weight today — just type *89.5 kg*")
        return
    last_date = db.date.fromisoformat(history[-1]["date"])
    if (db.date.today() - last_date).days >= 2:
        avg = db.get_7day_weight_average()
        msg = "⚖️ Haven't seen a weight log in 2 days. Weigh in today!"
        if avg:
            msg += f"\n_Your 7-day avg: {avg} kg_"
        await _send(context, msg)


# ── Job 11: Sunday weekly report ──────────────────────────────────────────────

async def weekly_report(context: ContextTypes.DEFAULT_TYPE):
    chat_id = _chat_id()
    if not chat_id:
        return

    stats = db.get_weekly_stats()
    streak = db.get_streak()
    adherence = db.get_weekly_adherence_score()
    water_compliance = db.get_water_compliance_week()
    name = db.get_state("user_name") or "there"

    # Update AI memory from logs
    memory.update_from_logs()

    lines = [f"📈 *Week in Review, {name}*\n"]
    lines.append(f"🔥 Avg calories: {stats['avg_calories']} kcal/day")
    lines.append(f"💪 Avg protein: {stats['avg_protein']}g/day")
    lines.append(f"💧 Water: hit goal {water_compliance}")

    if stats["weight_change"] is not None:
        emoji = "📉" if stats["weight_change"] < 0 else "📈"
        lines.append(
            f"{emoji} Weight: {stats['weight_start']} → {stats['weight_end']} kg "
            f"({stats['weight_change']:+.1f} kg)"
        )

    lines.append(f"\n🔥 Streak: {streak} days")
    score = adherence.get("score", 0)
    lines.append(f"⭐ *Weekly score: {score}/100*")
    lines.append(f"  • Calorie days: {adherence.get('calorie_days','?')}")
    lines.append(f"  • Protein days: {adherence.get('protein_days','?')}")
    lines.append(f"  • Log days: {adherence.get('log_days','?')}")

    # Check behavior milestone
    prot_days = int(adherence.get("protein_days", "0/7").split("/")[0])
    water_days = int(adherence.get("water_days", "0/7").split("/")[0])
    behavior_milestone = milestones.check_behavior_milestone(streak, prot_days, water_days)
    if behavior_milestone:
        lines.append(f"\n{behavior_milestone}")

    # AI insights
    weekly_data = {**stats, "streak": streak, "adherence_score": score,
                   "water_compliance": water_compliance}
    mem_ctx = memory.get_context_for_prompt("general")
    try:
        insights = await ai.generate_insights(weekly_data, mem_ctx)
        lines.append(f"\n🧠 *AI Coach:*\n{insights}")
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown"
    )

    # Send shareable weekly card
    try:
        history = db.get_weight_history(30)
        if history:
            card_bytes = charts.generate_weekly_card({
                "week_number": db.date.today().isocalendar()[1],
                "weight_change": stats.get("weight_change"),
                "weight_current": history[-1]["weight"],
                "total_lost": round(STARTING_WEIGHT - history[-1]["weight"], 1),
                "streak": streak,
                "score": score,
            })
            if card_bytes:
                await context.bot.send_photo(chat_id=chat_id, photo=card_bytes)
    except Exception:
        logger.exception("Weekly card failed")


# ── Job 12: Friday weekend alert ─────────────────────────────────────────────

async def weekend_alert(context: ContextTypes.DEFAULT_TYPE):
    if _notification_level() == "low":
        return
    t = db.get_today_totals()
    remaining_cal = max(CALORIE_GOAL - int(t["calories"]), 0)
    msg = (
        "📅 *Weekend starts. Most weight loss fails happen Fri–Sun.*\n\n"
        "Quick plan:\n"
        "• Keep eating window: 1:30–9:30 PM\n"
        "• At parties/dinners: eat dal/sabzi/raita, avoid fried items\n"
        "• One heavy meal won't ruin progress — logging it will keep you honest\n\n"
        f"_You have {remaining_cal} kcal left today._"
    )
    await _send(context, msg)


# ── Registration ──────────────────────────────────────────────────────────────

def register_all_jobs(app: Application):
    jq = app.job_queue

    today = db.date.today()
    is_weekend = today.weekday() >= 5  # 5=Sat, 6=Sun

    # Recurring daily jobs — use run_daily (survive restarts)
    morning_time = dt.time(8, 30, 0) if is_weekend else dt.time(7, 0, 0)
    jq.run_daily(midnight_reset,        time=dt.time(0, 1, 0))
    jq.run_daily(morning_greeting,      time=morning_time)
    jq.run_daily(window_opening,        time=dt.time(13, 25, 0))
    jq.run_daily(midday_checkin,        time=dt.time(13, 35, 0))
    jq.run_daily(window_closing_warning, time=dt.time(21, 0, 0))
    jq.run_daily(window_closed,         time=dt.time(21, 30, 0))
    jq.run_daily(nightly_coaching,      time=dt.time(22, 0, 0))
    jq.run_daily(streak_protection,     time=dt.time(20, 0, 0))
    jq.run_daily(weight_reminder,       time=dt.time(8, 0, 0))

    # Water nudge every 2 hours between 1 PM and 9 PM
    for hour in range(13, 21, 2):
        jq.run_daily(water_nudge, time=dt.time(hour, 0, 0))

    # Weekly jobs
    jq.run_daily(weekly_report,  time=dt.time(20, 0, 0), days=(6,))   # Sunday
    jq.run_daily(weekend_alert,  time=dt.time(18, 0, 0), days=(4,))   # Friday

    # Restart recovery: re-schedule supplement reminder if within window
    first_food_ts = db.get_state("first_food_today")
    if first_food_ts:
        try:
            import datetime
            elapsed = (datetime.datetime.now() - datetime.datetime.fromisoformat(first_food_ts)).seconds
            if elapsed < 1800:
                from bot import _supplement_reminder_job
                jq.run_once(_supplement_reminder_job, when=1800 - elapsed)
        except Exception:
            pass

    logger.info("All scheduler jobs registered")
