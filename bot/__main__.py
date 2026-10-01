"""Entry point: python -m bot"""

import logging

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from . import handlers, scheduler
from .config import load_config
from .db import Database

COMMANDS = [
    BotCommand("today", "Today's tasks and events"),
    BotCommand("tomorrow", "Tomorrow's plan"),
    BotCommand("add", "Add a task"),
    BotCommand("event", "Add an event"),
    BotCommand("events", "Upcoming events"),
    BotCommand("day", "See a specific day"),
    BotCommand("nightly", "Evening planning time"),
    BotCommand("timezone", "Set your timezone"),
    BotCommand("cancel", "Cancel what I'm waiting for"),
    BotCommand("help", "How to use the bot"),
]


async def post_init(app: Application) -> None:
    scheduler.schedule_all(app)
    await app.bot.set_my_commands(COMMANDS)


def build_app(request=None) -> Application:
    """Create the bot. `request` lets tests swap in a fake Telegram API."""
    config = load_config()
    builder = ApplicationBuilder().token(config.token).post_init(post_init)
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    app = builder.build()
    app.bot_data["config"] = config
    app.bot_data["db"] = Database(config.db_path)

    app.add_handler(TypeHandler(Update, handlers.gate), group=-1)
    for name, callback in [
        ("start", handlers.cmd_start),
        ("help", handlers.cmd_help),
        ("today", handlers.cmd_today),
        ("tomorrow", handlers.cmd_tomorrow),
        ("day", handlers.cmd_day),
        ("add", handlers.cmd_add),
        ("event", handlers.cmd_event),
        ("events", handlers.cmd_events),
        ("timezone", handlers.cmd_timezone),
        ("nightly", handlers.cmd_nightly),
        ("cancel", handlers.cmd_cancel),
    ]:
        app.add_handler(CommandHandler(name, callback, filters=filters.UpdateType.MESSAGE))
    app.add_handler(CallbackQueryHandler(handlers.on_button))
    app.add_handler(MessageHandler(filters.UpdateType.MESSAGE & filters.TEXT & ~filters.COMMAND, handlers.on_text))
    app.add_error_handler(handlers.on_error)
    return app


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log every poll (the URL contains the token)

    app = build_app()
    if not app.bot_data["config"].allowed_user_ids:
        logging.warning("ALLOWED_USER_IDS is empty: anyone who finds the bot can use it.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
