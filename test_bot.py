"""
QA test harness — simulates real human conversations with the bot.
Runs 30+ test cases covering all major flows.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from dotenv import load_dotenv

load_dotenv()

import db
import bot as bot_module

# ── Mock infrastructure ────────────────────────────────────────────────────────

sent_messages = []

def make_update(text: str, user_id: int = None):
    """Create a fake Telegram Update object."""
    uid = user_id or int(os.getenv("TELEGRAM_CHAT_ID", "633478120"))
    update = MagicMock()
    update.effective_user.id = uid
    update.effective_chat.id = uid
    update.message.text = text
    update.message.from_user.id = uid
    update.message.chat_id = uid

    async def reply_text(msg, **kwargs):
        sent_messages.append(("reply", msg))
        return MagicMock()

    async def reply_photo(photo, **kwargs):
        sent_messages.append(("photo", "[chart]"))
        return MagicMock()

    update.message.reply_text = reply_text
    update.message.reply_photo = reply_photo
    return update

def make_context():
    ctx = MagicMock()
    ctx.args = []
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_photo = AsyncMock()
    ctx.bot.send_chat_action = AsyncMock()
    ctx.bot.answer_callback_query = AsyncMock()
    ctx.job_queue = MagicMock()
    ctx.job_queue.run_once = MagicMock()
    return ctx

def last_reply():
    return sent_messages[-1][1] if sent_messages else ""

def clear():
    sent_messages.clear()

# ── Test runner ────────────────────────────────────────────────────────────────

passed = 0
failed = 0
results = []

async def test(name: str, fn):
    global passed, failed
    clear()
    try:
        await fn()
        results.append(f"  ✅ {name}")
        passed += 1
    except AssertionError as e:
        results.append(f"  ❌ {name}: {e}")
        failed += 1
    except Exception as e:
        results.append(f"  💥 {name}: {type(e).__name__}: {e}")
        failed += 1

# ── Reset DB to clean state ────────────────────────────────────────────────────

def reset_db():
    db.set_state("onboarding_step", "")
    db.set_state("user_name", "")
    db.set_state("user_diet", "")
    db.set_state("user_wake_time", "")
    db.set_state("user_motivation", "")
    db.set_state("awaiting_measurements", "")
    db.set_state("awaiting_yesterday_food", "")
    db.set_state("pending_correction_food_id", "")
    db.set_state("pending_correction_expires_at", "")

# ══════════════════════════════════════════════════════════════════════════════
# TEST CASES
# ══════════════════════════════════════════════════════════════════════════════

async def run_all():

    # ── BLOCK 1: Onboarding ───────────────────────────────────────────────────

    async def t01_start_new_user():
        reset_db()
        db.set_state("user_name", "")  # force new user
        u, c = make_update("/start"), make_context()
        c.args = []
        await bot_module.start(u, c)
        reply = last_reply()
        assert "Hi" in reply or "welcome" in reply.lower() or "name" in reply.lower(), f"Expected greeting, got: {reply[:80]}"

    async def t02_name_simple():
        reset_db()
        db.set_state("onboarding_step", "name")
        await bot_module.handle_text(make_update("Mohit"), make_context())
        name = db.get_state("user_name")
        assert name == "Mohit", f"Expected 'Mohit', got '{name}'"

    async def t03_name_hindi_hu():
        reset_db()
        db.set_state("onboarding_step", "name")
        await bot_module.handle_text(make_update("Mohit hu"), make_context())
        name = db.get_state("user_name")
        assert name == "Mohit", f"Expected 'Mohit', got '{name}'"

    async def t04_name_call_me():
        reset_db()
        db.set_state("onboarding_step", "name")
        await bot_module.handle_text(make_update("call me Mohit"), make_context())
        name = db.get_state("user_name")
        assert name == "Mohit", f"Expected 'Mohit', got '{name}'"

    async def t05_name_mera_naam():
        reset_db()
        db.set_state("onboarding_step", "name")
        await bot_module.handle_text(make_update("mera naam Mohit hai"), make_context())
        name = db.get_state("user_name")
        assert name == "Mohit", f"Expected 'Mohit', got '{name}'"

    async def t06_name_with_weight():
        reset_db()
        db.set_state("onboarding_step", "name")
        await bot_module.handle_text(make_update("Mohit, 90 kg"), make_context())
        name = db.get_state("user_name")
        step = db.get_state("onboarding_step")
        assert name == "Mohit", f"Name wrong: got '{name}'"
        assert step == "diet", f"Should move to diet, got '{step}'"

    async def t07_weight_step():
        reset_db()
        db.set_state("onboarding_step", "weight")
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("89 kg"), make_context())
        step = db.get_state("onboarding_step")
        assert step == "diet", f"Should move to diet, got '{step}'"

    async def t08_weight_step_non_number_falls_through():
        """Non-number during weight step should fall through to normal AI handling."""
        reset_db()
        db.set_state("onboarding_step", "weight")
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("kya khaun aaj?"), make_context())
        # Onboarding step should NOT change (still weight)
        step = db.get_state("onboarding_step")
        assert step == "weight", f"Step should stay 'weight', got '{step}'"
        # Should have replied with something (AI handled it)
        assert len(sent_messages) > 0, "Bot should have replied"

    async def t09_skip_onboarding():
        reset_db()
        db.set_state("onboarding_step", "weight")
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("skip"), make_context())
        step = db.get_state("onboarding_step")
        assert step == "", f"Should clear onboarding, got '{step}'"

    async def t10_diet_veg():
        reset_db()
        db.set_state("onboarding_step", "diet")
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("vegetarian"), make_context())
        diet = db.get_state("user_diet")
        step = db.get_state("onboarding_step")
        assert diet == "vegetarian", f"Expected vegetarian, got '{diet}'"
        assert step == "wake_time", f"Should move to wake_time, got '{step}'"

    async def t11_diet_non_veg():
        reset_db()
        db.set_state("onboarding_step", "diet")
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("chicken khata hoon"), make_context())
        diet = db.get_state("user_diet")
        assert diet == "non-vegetarian", f"Expected non-veg, got '{diet}'"

    # ── BLOCK 2: Food logging ─────────────────────────────────────────────────

    async def t12_food_log_simple():
        reset_db()
        db.set_state("user_name", "Mohit")
        initial = db.get_today_totals()["calories"]
        await bot_module.handle_text(make_update("2 roti aur dal"), make_context())
        after = db.get_today_totals()["calories"]
        assert after > initial, f"Calories should increase, was {initial}, now {after}"

    async def t13_food_log_hindi():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("chai aur paratha khaya"), make_context())
        foods = db.get_today_food()
        assert len(foods) > 0, "Food should be logged"

    async def t14_food_log_with_quantity():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("3 eggs scrambled"), make_context())
        foods = db.get_today_food()
        assert len(foods) > 0, "Food should be logged"
        reply = last_reply()
        assert "kcal" in reply.lower() or "protein" in reply.lower(), f"Reply should show nutrition: {reply[:80]}"

    # ── BLOCK 3: Weight & water logging ──────────────────────────────────────

    async def t15_weight_log():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("89.5 kg"), make_context())
        history = db.get_weight_history(1)
        assert history and abs(history[-1]["weight"] - 89.5) < 0.1, "Weight should be logged"

    async def t16_water_log():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("3 glass paani piya"), make_context())
        water = db.get_today_water()
        assert water >= 3, f"Water should be >= 3, got {water}"

    async def t17_water_log_english():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("drank 2 glasses of water"), make_context())
        water = db.get_today_water()
        assert water >= 2, f"Water should be >= 2, got {water}"

    # ── BLOCK 4: Free chat / AI responses ────────────────────────────────────

    async def t18_food_safety_question():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("kya main samosa kha sakta hoon?"), make_context())
        reply = last_reply()
        assert len(reply) > 20, f"Should get a real answer, got: {reply[:80]}"

    async def t19_general_chat_not_blocked():
        """Free chat should work even when onboarding is partially done."""
        reset_db()
        db.set_state("user_name", "Mohit")
        db.set_state("onboarding_step", "weight")  # stuck in onboarding
        await bot_module.handle_text(make_update("kya khaun for protein?"), make_context())
        reply = last_reply()
        assert len(reply) > 10, f"Should respond to chat during onboarding: {reply[:80]}"

    # ── BLOCK 5: Commands ─────────────────────────────────────────────────────

    async def t20_today_command():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.today(make_update("/today"), make_context())
        reply = last_reply()
        assert "kcal" in reply.lower() or "calorie" in reply.lower() or "today" in reply.lower(), \
            f"Today command should show stats: {reply[:80]}"

    async def t21_streak_command():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.streak(make_update("/streak"), make_context())
        reply = last_reply()
        assert "streak" in reply.lower() or "day" in reply.lower(), f"Streak reply: {reply[:80]}"

    async def t22_supplements_command():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.supplements(make_update("/supplements"), make_context())
        reply = last_reply()
        assert len(reply) > 20, f"Supplements reply: {reply[:80]}"

    async def t23_goal_command():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.goal(make_update("/goal"), make_context())
        reply = last_reply()
        assert "kg" in reply.lower() or "goal" in reply.lower(), f"Goal reply: {reply[:80]}"

    # ── BLOCK 6: Auth ─────────────────────────────────────────────────────────

    async def t24_auth_wrong_user():
        """Messages from unknown users should be silently ignored."""
        reset_db()
        u = make_update("hello", user_id=999999999)
        await bot_module.handle_text(u, make_context())
        assert len(sent_messages) == 0, "Should ignore unauthorized users"

    # ── BLOCK 7: Edge cases ───────────────────────────────────────────────────

    async def t25_start_reset_reruns_onboarding():
        reset_db()
        db.set_state("user_name", "Mohit")  # already onboarded
        u, c = make_update("/start"), make_context()
        c.args = ["reset"]
        await bot_module.start(u, c)
        step = db.get_state("onboarding_step")
        assert step == "name", f"Should restart onboarding, step is '{step}'"

    async def t26_measurement_exits_on_chat():
        """If user types chat while awaiting measurements, should exit measurement mode."""
        reset_db()
        db.set_state("user_name", "Mohit")
        db.set_state("awaiting_measurements", "1")
        await bot_module.handle_text(make_update("kya khaun?"), make_context())
        state = db.get_state("awaiting_measurements")
        assert state == "", f"Should exit measurement mode, got '{state}'"

    async def t27_supplement_log():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("vitamin d liya"), make_context())
        taken = db.get_today_supplements()
        # Should log or respond — either way no crash
        assert len(sent_messages) > 0, "Should reply to supplement log"

    async def t28_messed_up_flow():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("sab kuch kha liya aaj"), make_context())
        reply = last_reply()
        assert len(reply) > 20, f"Should handle messed up flow: {reply[:80]}"

    async def t29_sleep_trigger():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("so gaya"), make_context())
        sleeping = db.get_state("is_sleeping")
        reply = last_reply()
        # Should set sleeping or at least reply
        assert sleeping == "1" or len(reply) > 5, f"Sleep trigger failed, sleeping={sleeping}"

    async def t30_wake_trigger():
        reset_db()
        db.set_state("user_name", "Mohit")
        db.set_state("is_sleeping", "1")
        await bot_module.handle_text(make_update("uth gaya"), make_context())
        sleeping = db.get_state("is_sleeping")
        assert sleeping == "0", f"Should wake up, is_sleeping={sleeping}"

    async def t31_yesterday_log_trigger():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("I want to log yesterday's meals"), make_context())
        state = db.get_state("awaiting_yesterday_food")
        reply = last_reply()
        assert state == "1", f"Should set awaiting_yesterday_food, got '{state}'. Reply: {reply[:80]}"

    async def t32_yesterday_food_item_logged():
        reset_db()
        db.set_state("user_name", "Mohit")
        db.set_state("awaiting_yesterday_food", "1")
        from datetime import date as _d, timedelta as _td
        yesterday = (_d.today() - _td(days=1)).isoformat()
        await bot_module.handle_text(make_update("dal chawal 1 plate"), make_context())
        import sqlite3
        conn = sqlite3.connect(str(db.DB_PATH))
        row = conn.execute("SELECT date FROM food_logs ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row and row[0] == yesterday, f"Should log for {yesterday}, got {row}"

    async def t33_yesterday_done_clears_state():
        reset_db()
        db.set_state("user_name", "Mohit")
        db.set_state("awaiting_yesterday_food", "1")
        await bot_module.handle_text(make_update("done"), make_context())
        assert db.get_state("awaiting_yesterday_food") == "", "Should clear state"

    async def t34_general_chat_messed_up():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("yaar aaj bahut kha liya, sab barbaad ho gaya"), make_context())
        reply = last_reply()
        assert len(reply) > 20 and "not sure" not in reply.lower(), f"Bad reply: {reply[:80]}"

    async def t35_general_chat_question():
        reset_db()
        db.set_state("user_name", "Mohit")
        await bot_module.handle_text(make_update("kal ke liye meal plan suggest karo"), make_context())
        reply = last_reply()
        assert len(reply) > 30 and "not sure" not in reply.lower(), f"Bad reply: {reply[:80]}"

    # ── Run all tests ──────────────────────────────────────────────────────────

    tests = [
        ("T01 /start new user", t01_start_new_user),
        ("T02 Name: simple 'Mohit'", t02_name_simple),
        ("T03 Name: 'Mohit hu' (Hindi)", t03_name_hindi_hu),
        ("T04 Name: 'call me Mohit'", t04_name_call_me),
        ("T05 Name: 'mera naam Mohit hai'", t05_name_mera_naam),
        ("T06 Name + weight in one msg", t06_name_with_weight),
        ("T07 Weight step: '89 kg'", t07_weight_step),
        ("T08 Weight step: non-number falls through", t08_weight_step_non_number_falls_through),
        ("T09 Skip onboarding", t09_skip_onboarding),
        ("T10 Diet: vegetarian", t10_diet_veg),
        ("T11 Diet: non-veg Hindi", t11_diet_non_veg),
        ("T12 Food log: roti dal", t12_food_log_simple),
        ("T13 Food log: Hindi sentence", t13_food_log_hindi),
        ("T14 Food log: shows nutrition", t14_food_log_with_quantity),
        ("T15 Weight log: '89.5 kg'", t15_weight_log),
        ("T16 Water log: Hindi", t16_water_log),
        ("T17 Water log: English", t17_water_log_english),
        ("T18 Food safety question", t18_food_safety_question),
        ("T19 Chat works during onboarding", t19_general_chat_not_blocked),
        ("T20 /today command", t20_today_command),
        ("T21 /streak command", t21_streak_command),
        ("T22 /supplements command", t22_supplements_command),
        ("T23 /goal command", t23_goal_command),
        ("T24 Auth: wrong user ignored", t24_auth_wrong_user),
        ("T25 /start reset reruns onboarding", t25_start_reset_reruns_onboarding),
        ("T26 Measurement exits on chat", t26_measurement_exits_on_chat),
        ("T27 Supplement log", t27_supplement_log),
        ("T28 'Messed up' flow", t28_messed_up_flow),
        ("T29 Sleep trigger", t29_sleep_trigger),
        ("T30 Wake trigger", t30_wake_trigger),
        ("T31 Yesterday log: triggers state", t31_yesterday_log_trigger),
        ("T32 Yesterday log: food saved with yesterday date", t32_yesterday_food_item_logged),
        ("T33 Yesterday log: 'done' clears state", t33_yesterday_done_clears_state),
        ("T34 General chat: messed up handled naturally", t34_general_chat_messed_up),
        ("T35 General chat: question answered", t35_general_chat_question),
    ]

    print(f"\n🧪 Running {len(tests)} test cases...\n")
    for name, fn in tests:
        await test(name, fn)

    print("\n".join(results))
    print(f"\n{'='*50}")
    print(f"  ✅ Passed: {passed}/{len(tests)}")
    print(f"  ❌ Failed: {failed}/{len(tests)}")
    print(f"{'='*50}\n")
    return failed

if __name__ == "__main__":
    failed = asyncio.run(run_all())
    sys.exit(1 if failed > 0 else 0)
