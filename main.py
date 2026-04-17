import logging
import os
from dotenv import load_dotenv

# Load .env BEFORE importing any module that reads env vars at import time
load_dotenv()

from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)

import db
import bot
import scheduler
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    db.init_db()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()

    # ── Commands ──────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",       bot.start))
    app.add_handler(CommandHandler("help",        bot.help_cmd))
    app.add_handler(CommandHandler("today",       bot.today))
    app.add_handler(CommandHandler("log",         bot.log_cmd))
    app.add_handler(CommandHandler("weight",      bot.weight_cmd))
    app.add_handler(CommandHandler("water",       bot.water_cmd))
    app.add_handler(CommandHandler("sleep",       bot.sleep_cmd))
    app.add_handler(CommandHandler("supplements", bot.supplements))
    app.add_handler(CommandHandler("progress",    bot.progress))
    app.add_handler(CommandHandler("report",      bot.report))
    app.add_handler(CommandHandler("streak",      bot.streak))
    app.add_handler(CommandHandler("plan",        bot.plan))
    app.add_handler(CommandHandler("slept",       bot.slept))
    app.add_handler(CommandHandler("woke",        bot.woke))
    # Phase 2 new commands
    app.add_handler(CommandHandler("goal",        bot.goal))
    app.add_handler(CommandHandler("mood",        bot.mood_cmd))
    app.add_handler(CommandHandler("workout",     bot.workout_cmd))
    app.add_handler(CommandHandler("measure",     bot.measure_cmd))
    app.add_handler(CommandHandler("deficit",     bot.deficit_cmd))
    app.add_handler(CommandHandler("fasting",     bot.fasting_cmd))
    app.add_handler(CommandHandler("insights",    bot.insights_cmd))
    app.add_handler(CommandHandler("milestones",  bot.milestones_cmd))
    app.add_handler(CommandHandler("undo",        bot.undo_cmd))

    # ── Message + callback handlers ───────────────────────────────────────────
    app.add_handler(MessageHandler(filters.PHOTO, bot.handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    app.add_handler(CallbackQueryHandler(bot.handle_callback))

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler.register_all_jobs(app)

    logger.info("Bot polling started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
