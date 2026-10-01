"""Settings read from environment variables (see .env.example)."""

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Config:
    token: str
    allowed_user_ids: frozenset[int]  # empty = anyone may use the bot
    default_timezone: str
    db_path: str
    nightly_time: str  # "HH:MM" in each user's own timezone
    reminder_minutes: int


def load_config() -> Config:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN is not set. Get one from @BotFather and put it in the environment.")

    raw_ids = os.environ.get("ALLOWED_USER_IDS", "")
    try:
        allowed = frozenset(int(part) for part in raw_ids.replace(" ", "").split(",") if part)
    except ValueError:
        raise SystemExit("ALLOWED_USER_IDS must be a comma-separated list of numeric Telegram user IDs.")

    tz = os.environ.get("DEFAULT_TIMEZONE", "UTC").strip() or "UTC"
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise SystemExit(f"DEFAULT_TIMEZONE '{tz}' is not a valid timezone (example: America/Toronto).")

    return Config(
        token=token,
        allowed_user_ids=allowed,
        default_timezone=tz,
        db_path=os.environ.get("DB_PATH", "data/bot.db"),
        nightly_time=os.environ.get("NIGHTLY_TIME", "21:00"),
        reminder_minutes=int(os.environ.get("REMINDER_MINUTES", "30")),
    )
