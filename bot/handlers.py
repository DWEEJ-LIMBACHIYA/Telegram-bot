"""Commands, buttons and free-text messages."""

import logging
import time as _time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest
from telegram.ext import ApplicationHandlerStop, ContextTypes

from . import scheduler, views
from .config import Config
from .db import Database, parse_utc
from .parsing import fmt_day, fmt_time, parse_date, parse_event, parse_reschedule, parse_task, parse_time
from .views import esc

log = logging.getLogger(__name__)

PENDING_SECONDS = 10 * 60
HTML = ParseMode.HTML

HELP = """<b>How to use me</b>

<b>Just type</b> and I'll add it for today:
• <code>Buy milk</code> → task
• <code>tomorrow Call mom</code> → task for tomorrow
• <code>sat 7pm Gaming night</code> → event with a reminder
Send several lines to add several items at once.

<b>Commands</b>
/today · /tomorrow · /day <i>fri</i> — see a day
/add <i>text</i> — add a task
/event <i>sat 7pm Gaming</i> — add an event
/events — upcoming events
/timezone <i>America/Toronto</i> — set your timezone
/nightly <i>21:00</i> or <i>off</i> — evening planning prompt
/cancel — stop what I'm waiting for

<b>Dates</b>: today, tomorrow, mon…sun, next fri, +3, in 3 days, 5 oct, 2026-10-05
<b>Times</b>: 19:00, 7pm, 7:30pm, noon

Tap any task or event in a list to mark it done, rename, postpone or delete it."""


# ----- helpers -----

def _db(context) -> Database:
    return context.bot_data["db"]


def _user(context, user_id: int):
    """(user row, timezone, today in that timezone)."""
    user = _db(context).get_user(user_id)
    tz = ZoneInfo(user["timezone"])
    return user, tz, datetime.now(tz).date()


def set_pending(context, kind: str, seconds: int = PENDING_SECONDS, **data) -> None:
    context.user_data["pending"] = {"kind": kind, "expires": _time.time() + seconds, **data}


def get_pending(context) -> dict | None:
    pending = context.user_data.get("pending")
    if pending and pending["expires"] < _time.time():
        context.user_data.pop("pending", None)
        return None
    return pending


def clear_pending(context) -> None:
    context.user_data.pop("pending", None)


async def safe_edit(query, text: str, markup=None) -> None:
    try:
        await query.edit_message_text(text, parse_mode=HTML, reply_markup=markup)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


def _create_event(context, user, tz: ZoneInfo, day: date, at, title: str) -> tuple[int, datetime]:
    cfg: Config = context.bot_data["config"]
    start = datetime.combine(day, at, tzinfo=tz)
    event_id = _db(context).add_event(user["id"], title, start, cfg.reminder_minutes)
    scheduler.schedule_event(context.job_queue, _db(context).get_event(user["id"], event_id))
    return event_id, start


# ----- access control (runs before every other handler) -----

async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user, chat = update.effective_user, update.effective_chat
    if tg_user is None or chat is None or chat.type != ChatType.PRIVATE:
        raise ApplicationHandlerStop  # group support comes in a later phase

    cfg: Config = context.bot_data["config"]
    if cfg.allowed_user_ids and tg_user.id not in cfg.allowed_user_ids:
        if update.callback_query:
            await update.callback_query.answer("Not allowed.")
        elif update.effective_message:
            await update.effective_message.reply_text(
                f"🔒 This is a private bot. Your Telegram ID is <code>{tg_user.id}</code> — "
                "send it to the owner if you should have access.",
                parse_mode=HTML,
            )
        raise ApplicationHandlerStop

    user, created = _db(context).ensure_user(tg_user.id, tg_user.first_name or "", cfg.default_timezone, cfg.nightly_time)
    if created:
        scheduler.schedule_nightly(context.job_queue, user)


# ----- commands -----

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, tz, _ = _user(context, update.effective_user.id)
    nightly = user["nightly_time"] or "off"
    await update.effective_message.reply_text(
        f"👋 Hi {esc(user['first_name'] or 'there')}! I'm your planner: tasks, events and an evening check-in.\n\n"
        f"🌍 Timezone: <b>{user['timezone']}</b> (change with /timezone)\n"
        f"🌙 Evening planning: <b>{nightly}</b> (change with /nightly)\n\n" + HELP,
        parse_mode=HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP, parse_mode=HTML)


async def _send_day(update: Update, context, day: date | None = None, offset: int = 0) -> None:
    user, tz, today = _user(context, update.effective_user.id)
    text, markup = views.day_view(_db(context), user["id"], day or today + timedelta(days=offset), today, tz)
    await update.effective_message.reply_text(text, parse_mode=HTML, reply_markup=markup)


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_day(update, context)


async def cmd_tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_day(update, context, offset=1)


async def cmd_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, today = _user(context, update.effective_user.id)
    arg = " ".join(context.args)
    day = parse_date(arg, today) if arg else today
    if not day:
        await update.effective_message.reply_text("I couldn't read that date. Try: /day fri, /day 5 oct, /day +2")
        return
    await _send_day(update, context, day=day)


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, today = _user(context, update.effective_user.id)
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        set_pending(context, "add_task", day=today.isoformat())
        await update.effective_message.reply_text("📝 What's the task? (add a day like <i>tomorrow</i> if it's not for today)", parse_mode=HTML)
        return
    await add_items(update, context, text, today, mode="task")


async def cmd_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, today = _user(context, update.effective_user.id)
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        set_pending(context, "add_event", day=today.isoformat())
        await update.effective_message.reply_text("📅 What's the event and when? e.g. <code>sat 7pm Gaming night</code>", parse_mode=HTML)
        return
    await add_items(update, context, text, today, mode="event")


async def cmd_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, tz, today = _user(context, update.effective_user.id)
    events = _db(context).upcoming_events(user["id"], datetime.now(timezone.utc))
    text, markup = views.events_list(events, tz, today)
    await update.effective_message.reply_text(text, parse_mode=HTML, reply_markup=markup)


async def cmd_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, _, _ = _user(context, update.effective_user.id)
    if not context.args:
        await update.effective_message.reply_text(
            f"🌍 Your timezone is <b>{user['timezone']}</b>.\n\nChange it with e.g. "
            "<code>/timezone America/Toronto</code>, <code>/timezone Asia/Kolkata</code>, "
            "<code>/timezone Europe/London</code>.",
            parse_mode=HTML,
        )
        return
    name = context.args[0]
    try:
        tz = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        await update.effective_message.reply_text(
            "I don't know that timezone. Use the Region/City form, e.g. America/Toronto or Asia/Kolkata."
        )
        return
    _db(context).set_timezone(user["id"], name)
    scheduler.schedule_nightly(context.job_queue, _db(context).get_user(user["id"]))
    now = datetime.now(tz)
    await update.effective_message.reply_text(
        f"✅ Timezone set to <b>{name}</b>. It's {fmt_time(now.time())} there now.", parse_mode=HTML
    )


async def cmd_nightly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, _, _ = _user(context, update.effective_user.id)
    arg = " ".join(context.args).strip().lower()
    if not arg:
        current = user["nightly_time"] or "off"
        await update.effective_message.reply_text(
            f"🌙 Evening planning prompt: <b>{current}</b>.\nChange with <code>/nightly 21:30</code> or <code>/nightly off</code>.",
            parse_mode=HTML,
        )
        return
    if arg == "off":
        value = None
    else:
        at = parse_time(arg)
        if not at:
            await update.effective_message.reply_text("Please give a time like 21:00 or 9pm, or 'off'.")
            return
        value = fmt_time(at)
    _db(context).set_nightly_time(user["id"], value)
    scheduler.schedule_nightly(context.job_queue, _db(context).get_user(user["id"]))
    await update.effective_message.reply_text(
        f"✅ I'll check in every evening at <b>{value}</b>." if value else "✅ Evening planning prompt turned off.",
        parse_mode=HTML,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_pending(context)
    await update.effective_message.reply_text("👍 Cancelled.")


# ----- free text -----

async def add_items(update: Update, context, text: str, default_day: date, mode: str = "auto") -> None:
    """Add one item per line. mode: 'task', 'event', or 'auto' (a line with a time becomes an event)."""
    user, tz, today = _user(context, update.effective_user.id)
    db = _db(context)
    added, errors, first_day = [], [], None
    now = datetime.now(timezone.utc)

    for line in filter(None, (ln.strip() for ln in text.splitlines())):
        if mode in ("event", "auto"):
            try:
                day, at, title = parse_event(line, today, default_day)
                _, start = _create_event(context, user, tz, day, at, title)
                note = " <i>(already passed)</i>" if start < now else ""
                added.append(f"📅 {fmt_day(day, today)} {fmt_time(at)} — {esc(title)}{note}")
                first_day = first_day or day
                continue
            except ValueError as exc:
                if mode == "event":
                    errors.append(f"“{esc(line)}”: {esc(str(exc))}")
                    continue
        try:
            day, title = parse_task(line, today, default_day)
        except ValueError as exc:
            errors.append(f"“{esc(line)}”: {esc(str(exc))}")
            continue
        db.add_task(user["id"], title, day)
        added.append(f"⬜ {fmt_day(day, today)} — {esc(title)}")
        first_day = first_day or day

    lines = []
    if added:
        lines += ["✅ <b>Added</b>", *added]
    if errors:
        lines += ["", "⚠️ <b>Couldn't add</b>", *errors]
    pending = get_pending(context)
    markup = None
    if pending and pending["kind"] == "nightly":
        lines += ["", "Anything else for tomorrow? Send it, or tap Done."]
        markup = views.InlineKeyboardMarkup([[views.Btn("✅ Done planning", callback_data="nightly:done")]])
    elif first_day:
        markup = views.InlineKeyboardMarkup([[views.Btn(f"📋 Open {fmt_day(first_day, today)}", callback_data=f"day:{first_day.isoformat()}")]])
    await update.effective_message.reply_text("\n".join(lines) or "Nothing to add.", parse_mode=HTML, reply_markup=markup)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.effective_message.text.strip()
    user, tz, today = _user(context, update.effective_user.id)
    db = _db(context)
    pending = get_pending(context)
    kind = pending["kind"] if pending else None

    if kind in ("add_task", "add_event", "nightly"):
        if kind != "nightly":
            clear_pending(context)
        mode = {"add_task": "task", "add_event": "event"}.get(kind, "auto")
        await add_items(update, context, text, date.fromisoformat(pending["day"]), mode=mode)

    elif kind == "rename_task":
        clear_pending(context)
        if db.rename_task(user["id"], pending["id"], text):
            card, markup = views.task_card(db.get_task(user["id"], pending["id"]), today)
            await update.effective_message.reply_text("✏️ Renamed.\n\n" + card, parse_mode=HTML, reply_markup=markup)
        else:
            await update.effective_message.reply_text("That task no longer exists.")

    elif kind == "pick_task_date":
        new_day = parse_date(text, today)
        if not new_day:
            await update.effective_message.reply_text("I couldn't read that date. Try: tomorrow, fri, 5 oct, +3 (or /cancel)")
            return
        clear_pending(context)
        if db.postpone_task(user["id"], pending["id"], new_day):
            card, markup = views.task_card(db.get_task(user["id"], pending["id"]), today)
            await update.effective_message.reply_text(f"⏭ Moved to {fmt_day(new_day, today)}.\n\n" + card, parse_mode=HTML, reply_markup=markup)
        else:
            await update.effective_message.reply_text("That task no longer exists.")

    elif kind == "rename_event":
        clear_pending(context)
        if db.rename_event(user["id"], pending["id"], text):
            card, markup = views.event_card(db.get_event(user["id"], pending["id"]), tz, today)
            await update.effective_message.reply_text("✏️ Renamed.\n\n" + card, parse_mode=HTML, reply_markup=markup)
        else:
            await update.effective_message.reply_text("That event no longer exists.")

    elif kind == "move_event":
        event = db.get_event(user["id"], pending["id"])
        if not event:
            clear_pending(context)
            await update.effective_message.reply_text("That event no longer exists.")
            return
        try:
            new_day, new_time = parse_reschedule(text, today)
        except ValueError as exc:
            await update.effective_message.reply_text(f"{exc} (or /cancel)")
            return
        clear_pending(context)
        old = views.local_start(event, tz)
        start = datetime.combine(new_day or old.date(), new_time or old.time(), tzinfo=tz)
        db.move_event(user["id"], event["id"], start)
        event = db.get_event(user["id"], event["id"])
        scheduler.schedule_event(context.job_queue, event)
        card, markup = views.event_card(event, tz, today)
        await update.effective_message.reply_text("⏭ Moved.\n\n" + card, parse_mode=HTML, reply_markup=markup)

    else:
        await add_items(update, context, text, today)


# ----- buttons -----

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split(":")
    user, tz, today = _user(context, update.effective_user.id)
    uid, db, jq = user["id"], _db(context), context.job_queue
    head = parts[0]

    if head == "day":
        await safe_edit(query, *views.day_view(db, uid, date.fromisoformat(parts[1]), today, tz))

    elif head == "add":
        day = date.fromisoformat(parts[2])
        if parts[1] == "t":
            set_pending(context, "add_task", day=day.isoformat())
            prompt = f"📝 Send the task for <b>{fmt_day(day, today)}</b> (several lines = several tasks)."
        else:
            set_pending(context, "add_event", day=day.isoformat())
            prompt = f"📅 Send the event for <b>{fmt_day(day, today)}</b> with a time, e.g. <code>7pm Gaming night</code>."
        await query.message.reply_text(prompt + "\n/cancel to stop.", parse_mode=HTML)

    elif head == "od":
        day = date.fromisoformat(parts[1])
        db.move_unfinished(uid, today - timedelta(days=1), day)
        await safe_edit(query, *views.day_view(db, uid, day, today, tz))

    elif head == "mv":
        src, dst = date.fromisoformat(parts[1]), date.fromisoformat(parts[2])
        moved = db.move_unfinished(uid, src, dst)
        text, markup = views.nightly_view(db, uid, src, tz)
        await safe_edit(query, f"↪️ Moved {moved} task(s) to {dst:%a %d %b}.\n\n" + text, markup)

    elif head == "nightly":
        clear_pending(context)
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("👍 Plan saved. Good night! 🌙")

    elif head == "ev":
        events = db.upcoming_events(uid, datetime.now(timezone.utc))
        await safe_edit(query, *views.events_list(events, tz, today))

    elif head == "t":
        await _task_button(query, context, uid, db, today, parts[1], int(parts[2]), parts[3:])

    elif head == "e":
        await _event_button(query, context, uid, db, jq, tz, today, parts[1], int(parts[2]), parts[3:])


async def _task_button(query, context, uid, db: Database, today, action, task_id, extra) -> None:
    task = db.get_task(uid, task_id)
    if not task:
        await safe_edit(query, "That task no longer exists.")
        return

    if action == "open":
        await safe_edit(query, *views.task_card(task, today))
    elif action == "done":
        db.set_task_done(uid, task_id, not task["done"])
        await safe_edit(query, *views.task_card(db.get_task(uid, task_id), today))
    elif action == "edit":
        set_pending(context, "rename_task", id=task_id)
        await query.message.reply_text(f"✏️ Send the new name for <b>{esc(task['title'])}</b> (/cancel to stop).", parse_mode=HTML)
    elif action == "pp":
        await safe_edit(query, *views.task_postpone_menu(task, today))
    elif action == "to":
        new_day = date.fromisoformat(extra[0])
        db.postpone_task(uid, task_id, new_day)
        text, markup = views.task_card(db.get_task(uid, task_id), today)
        await safe_edit(query, f"⏭ Moved to {fmt_day(new_day, today)}.\n\n" + text, markup)
    elif action == "pick":
        set_pending(context, "pick_task_date", id=task_id)
        await query.message.reply_text("📅 Which day? e.g. <code>fri</code>, <code>5 oct</code>, <code>+3</code> (/cancel to stop)", parse_mode=HTML)
    elif action == "del":
        await safe_edit(query, *views.confirm_delete("t", task))
    elif action == "delok":
        db.delete_task(uid, task_id)
        text, markup = views.day_view(db, uid, date.fromisoformat(task["due_date"]), today, ZoneInfo(db.get_user(uid)["timezone"]))
        await safe_edit(query, f"🗑 Deleted “{esc(task['title'])}”.\n\n" + text, markup)


async def _event_button(query, context, uid, db: Database, jq, tz, today, action, event_id, extra) -> None:
    event = db.get_event(uid, event_id)
    if not event:
        await safe_edit(query, "That event no longer exists.")
        return

    if action == "open":
        await safe_edit(query, *views.event_card(event, tz, today))
    elif action == "edit":
        set_pending(context, "rename_event", id=event_id)
        await query.message.reply_text(f"✏️ Send the new name for <b>{esc(event['title'])}</b> (/cancel to stop).", parse_mode=HTML)
    elif action == "pp":
        await safe_edit(query, *views.event_move_menu(event))
    elif action == "sh":
        start = parse_utc(event["start_utc"]) + timedelta(minutes=int(extra[0]))
        db.move_event(uid, event_id, start)
        event = db.get_event(uid, event_id)
        scheduler.schedule_event(jq, event)
        text, markup = views.event_card(event, tz, today)
        await safe_edit(query, "⏭ Moved.\n\n" + text, markup)
    elif action == "pick":
        set_pending(context, "move_event", id=event_id)
        await query.message.reply_text(
            "📅 New date and/or time? e.g. <code>tomorrow 8pm</code>, <code>sat 19:00</code>, <code>20:30</code> (/cancel to stop)",
            parse_mode=HTML,
        )
    elif action == "del":
        await safe_edit(query, *views.confirm_delete("e", event))
    elif action == "delok":
        day = views.local_start(event, tz).date()
        db.delete_event(uid, event_id)
        scheduler.unschedule_event(jq, event_id)
        text, markup = views.day_view(db, uid, day, today, tz)
        await safe_edit(query, f"🗑 Deleted “{esc(event['title'])}”.\n\n" + text, markup)


# ----- errors -----

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Error while handling an update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("😵 Something went wrong. Please try again.")
        except Exception:  # noqa: BLE001 - never let the error handler itself crash
            pass
