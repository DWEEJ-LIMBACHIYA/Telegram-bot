"""Message text and inline keyboards. No Telegram calls happen here.

Callback data formats (Telegram allows 64 bytes):
  day:<iso>              show the day view
  add:t:<iso> / add:e:<iso>   ask for a new task / event on that day
  od:<iso>               move overdue tasks to that day
  mv:<from_iso>:<to_iso> move unfinished tasks (up to from) to another day
  t:<action>:<id>[:arg]  task actions (open, done, edit, pp, to, pick, del, delok)
  e:<action>:<id>[:arg]  event actions (open, edit, pp, sh, pick, del, delok)
  ev:list                upcoming events
  nightly:done           finish the evening planning session
"""

import html
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup

from .db import Database, parse_utc
from .parsing import fmt_day, fmt_time


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def short(text: str, n: int = 40) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    return start, datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz)


def local_start(event, tz: ZoneInfo) -> datetime:
    return parse_utc(event["start_utc"]).astimezone(tz)


def day_view(db: Database, user_id: int, day: date, today: date, tz: ZoneInfo) -> tuple[str, InlineKeyboardMarkup]:
    tasks = db.tasks_on(user_id, day)
    events = db.events_between(user_id, *day_bounds(day, tz))
    overdue = db.overdue_tasks(user_id, today) if day == today else []

    lines = [f"📋 <b>{fmt_day(day, today)}</b> · {day:%a %d %b}"]
    if events:
        lines.append("")
        for ev in events:
            lines.append(f"🕒 {fmt_time(local_start(ev, tz).time())}  {esc(ev['title'])}")
    lines.append("")
    if tasks:
        done = sum(t["done"] for t in tasks)
        lines.append(f"<i>Tasks: {done}/{len(tasks)} done</i>")
        for t in tasks:
            mark = "✅" if t["done"] else "⬜"
            title = f"<s>{esc(t['title'])}</s>" if t["done"] else esc(t["title"])
            lines.append(f"{mark} {title}")
    else:
        lines.append("<i>No tasks.</i>")
    if overdue:
        lines.append(f"\n⚠️ {len(overdue)} unfinished task(s) from earlier days.")
    lines.append("\nTap an item to edit, postpone or delete it.")

    rows = []
    for ev in events:
        rows.append([Btn(f"🕒 {fmt_time(local_start(ev, tz).time())} {short(ev['title'], 34)}", callback_data=f"e:open:{ev['id']}")])
    for t in tasks:
        rows.append([Btn(f"{'✅' if t['done'] else '⬜'} {short(t['title'])}", callback_data=f"t:open:{t['id']}")])
    if overdue:
        rows.append([Btn(f"↪️ Move {len(overdue)} overdue to today", callback_data=f"od:{day.isoformat()}")])
    rows.append([
        Btn("➕ Task", callback_data=f"add:t:{day.isoformat()}"),
        Btn("➕ Event", callback_data=f"add:e:{day.isoformat()}"),
    ])
    rows.append([
        Btn("◀", callback_data=f"day:{(day - timedelta(days=1)).isoformat()}"),
        Btn("Today", callback_data=f"day:{today.isoformat()}"),
        Btn("▶", callback_data=f"day:{(day + timedelta(days=1)).isoformat()}"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def task_card(task, today: date) -> tuple[str, InlineKeyboardMarkup]:
    due = date.fromisoformat(task["due_date"])
    status = "✅ Done" if task["done"] else "⬜ Not done"
    lines = [f"<b>{esc(task['title'])}</b>", "", f"📅 {fmt_day(due, today)} ({due:%a %d %b})", status]
    if task["postponed_count"]:
        lines.append(f"⏭ Postponed {task['postponed_count']}×")
    tid = task["id"]
    rows = [
        [Btn("↩️ Mark not done" if task["done"] else "✅ Done", callback_data=f"t:done:{tid}")],
        [Btn("✏️ Rename", callback_data=f"t:edit:{tid}"), Btn("⏭ Postpone", callback_data=f"t:pp:{tid}")],
        [Btn("🗑 Delete", callback_data=f"t:del:{tid}"), Btn("⬅️ Back", callback_data=f"day:{due.isoformat()}")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def task_postpone_menu(task, today: date) -> tuple[str, InlineKeyboardMarkup]:
    tid = task["id"]
    due = date.fromisoformat(task["due_date"])
    base = max(due, today)
    opts = [("Tomorrow", today + timedelta(days=1)), ("In 2 days", base + timedelta(days=2)), ("Next week", base + timedelta(days=7))]
    rows = [[Btn(f"{label} ({d:%a %d %b})", callback_data=f"t:to:{tid}:{d.isoformat()}")] for label, d in opts]
    rows.append([Btn("📅 Pick a date…", callback_data=f"t:pick:{tid}")])
    rows.append([Btn("⬅️ Back", callback_data=f"t:open:{tid}")])
    return f"⏭ Postpone <b>{esc(task['title'])}</b> to…", InlineKeyboardMarkup(rows)


def confirm_delete(kind: str, item) -> tuple[str, InlineKeyboardMarkup]:
    rows = [[
        Btn("🗑 Yes, delete", callback_data=f"{kind}:delok:{item['id']}"),
        Btn("Cancel", callback_data=f"{kind}:open:{item['id']}"),
    ]]
    return f"Delete <b>{esc(item['title'])}</b>?", InlineKeyboardMarkup(rows)


def event_card(event, tz: ZoneInfo, today: date) -> tuple[str, InlineKeyboardMarkup]:
    start = local_start(event, tz)
    passed = start < datetime.now(timezone.utc)
    lines = [
        f"<b>{esc(event['title'])}</b>",
        "",
        f"📅 {fmt_day(start.date(), today)} ({start:%a %d %b}) at {fmt_time(start.time())}",
        f"⏰ Reminder {event['remind_minutes']} min before" if event["remind_minutes"] else "⏰ No reminder",
    ]
    if passed:
        lines.append("<i>This event is in the past.</i>")
    eid = event["id"]
    rows = [
        [Btn("✏️ Rename", callback_data=f"e:edit:{eid}"), Btn("⏭ Move", callback_data=f"e:pp:{eid}")],
        [Btn("🗑 Delete", callback_data=f"e:del:{eid}"), Btn("⬅️ Back", callback_data=f"day:{start.date().isoformat()}")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def event_move_menu(event) -> tuple[str, InlineKeyboardMarkup]:
    eid = event["id"]
    rows = [
        [Btn("+1 hour", callback_data=f"e:sh:{eid}:60"), Btn("+1 day", callback_data=f"e:sh:{eid}:1440")],
        [Btn("+1 week", callback_data=f"e:sh:{eid}:10080")],
        [Btn("📅 Pick new date/time…", callback_data=f"e:pick:{eid}")],
        [Btn("⬅️ Back", callback_data=f"e:open:{eid}")],
    ]
    return f"⏭ Move <b>{esc(event['title'])}</b>…", InlineKeyboardMarkup(rows)


def events_list(events, tz: ZoneInfo, today: date) -> tuple[str, InlineKeyboardMarkup]:
    if not events:
        return "📅 No upcoming events.\n\nAdd one with e.g. <code>/event sat 7pm Gaming night</code>", InlineKeyboardMarkup(
            [[Btn("➕ Event", callback_data=f"add:e:{today.isoformat()}")]]
        )
    lines = ["📅 <b>Upcoming events</b>", ""]
    rows = []
    for ev in events:
        start = local_start(ev, tz)
        when = f"{fmt_day(start.date(), today)} {fmt_time(start.time())}"
        lines.append(f"• {when} — {esc(ev['title'])}")
        rows.append([Btn(f"{when} · {short(ev['title'], 30)}", callback_data=f"e:open:{ev['id']}")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def nightly_view(db: Database, user_id: int, today: date, tz: ZoneInfo) -> tuple[str, InlineKeyboardMarkup]:
    tomorrow = today + timedelta(days=1)
    todays = db.tasks_on(user_id, today)
    unfinished = [t for t in todays if not t["done"]] + list(db.overdue_tasks(user_id, today))
    events = db.events_between(user_id, *day_bounds(tomorrow, tz))
    planned = db.tasks_on(user_id, tomorrow)

    lines = [f"🌙 <b>Planning for tomorrow</b> · {tomorrow:%a %d %b}", ""]
    if todays:
        lines.append(f"Today you finished {sum(t['done'] for t in todays)}/{len(todays)} tasks.")
    if unfinished:
        lines.append("Still open: " + ", ".join(esc(short(t["title"], 30)) for t in unfinished[:5]) + ("…" if len(unfinished) > 5 else ""))
    lines.append("")
    if events or planned:
        lines.append("<b>Tomorrow so far</b>")
        lines += [f"🕒 {fmt_time(local_start(e, tz).time())}  {esc(e['title'])}" for e in events]
        lines += [f"⬜ {esc(t['title'])}" for t in planned]
    else:
        lines.append("<i>Nothing planned for tomorrow yet.</i>")
    lines += [
        "",
        "Anything to add? Just send it — one item per line.",
        "Include a time (e.g. <code>8pm gym</code>) to make it an event with a reminder.",
    ]

    rows = []
    if unfinished:
        rows.append([Btn(f"↪️ Move {len(unfinished)} unfinished to tomorrow", callback_data=f"mv:{today.isoformat()}:{tomorrow.isoformat()}")])
    rows.append([Btn("📋 See tomorrow", callback_data=f"day:{tomorrow.isoformat()}"), Btn("✅ Done planning", callback_data="nightly:done")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)
