"""Nightly planning prompts and event reminders.

PTB's JobQueue only lives in memory, so everything here is rebuilt from the
database at startup (see schedule_all) and whenever an item changes.
"""

import logging
import time as _time
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram.constants import ParseMode
from telegram.error import Forbidden
from telegram.ext import Application, ContextTypes, JobQueue

from .db import Database, parse_utc
from .parsing import fmt_time
from .views import esc, nightly_view

log = logging.getLogger(__name__)

NIGHTLY_PENDING_HOURS = 6


def _remove(jq: JobQueue, name: str) -> None:
    for job in jq.get_jobs_by_name(name):
        job.schedule_removal()


def schedule_nightly(jq: JobQueue, user) -> None:
    name = f"night:{user['id']}"
    _remove(jq, name)
    if not user["nightly_time"]:
        return
    hour, minute = map(int, user["nightly_time"].split(":"))
    jq.run_daily(
        nightly_job,
        time=time(hour, minute, tzinfo=ZoneInfo(user["timezone"])),
        name=name,
        chat_id=user["id"],
        user_id=user["id"],
    )


def schedule_event(jq: JobQueue, event) -> None:
    name = f"ev:{event['id']}"
    _remove(jq, name)
    if not event["remind_minutes"]:
        return
    start = parse_utc(event["start_utc"])
    when = start - timedelta(minutes=event["remind_minutes"])
    if when <= datetime.now(timezone.utc):
        return
    jq.run_once(
        event_reminder_job,
        when=when,
        name=name,
        chat_id=event["user_id"],
        user_id=event["user_id"],
        data=(event["id"], event["start_utc"]),
    )


def unschedule_event(jq: JobQueue, event_id: int) -> None:
    _remove(jq, f"ev:{event_id}")


def schedule_all(app: Application) -> None:
    db: Database = app.bot_data["db"]
    users = db.all_users()
    for user in users:
        schedule_nightly(app.job_queue, user)
    events = db.all_future_events(datetime.now(timezone.utc))
    for event in events:
        schedule_event(app.job_queue, event)
    log.info("Scheduled nightly prompts for %d users and reminders for %d events", len(users), len(events))


async def event_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    event_id, start_utc = context.job.data
    event = db.get_event(context.job.user_id, event_id)
    if not event or event["start_utc"] != start_utc:
        return  # deleted or moved since this reminder was scheduled
    user = db.get_user(event["user_id"])
    start = parse_utc(event["start_utc"]).astimezone(ZoneInfo(user["timezone"]))
    text = f"⏰ In {event['remind_minutes']} min: <b>{esc(event['title'])}</b> at {fmt_time(start.time())}"
    try:
        await context.bot.send_message(event["user_id"], text, parse_mode=ParseMode.HTML)
    except Forbidden:
        log.warning("User %s blocked the bot; skipping reminder", event["user_id"])


async def nightly_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    user = db.get_user(context.job.user_id)
    if not user:
        return
    tz = ZoneInfo(user["timezone"])
    today = datetime.now(tz).date()
    text, markup = nightly_view(db, user["id"], today, tz)
    try:
        await context.bot.send_message(user["id"], text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Forbidden:
        log.warning("User %s blocked the bot; skipping nightly prompt", user["id"])
        return
    # Until they tap "Done planning" (or a few hours pass), plain messages become items for tomorrow.
    context.user_data["pending"] = {
        "kind": "nightly",
        "day": (today + timedelta(days=1)).isoformat(),
        "expires": _time.time() + NIGHTLY_PENDING_HOURS * 3600,
    }
