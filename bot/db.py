"""SQLite storage for users, tasks and events.

Tasks are tied to a calendar date in the user's own timezone (stored as
YYYY-MM-DD). Events have an exact start time, stored in UTC as ISO text.
Every query that touches a task or event is scoped by user_id, so one user
can never read or change another user's items.
"""

import os
import sqlite3
from datetime import date, datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,          -- Telegram user id
    first_name    TEXT,
    timezone      TEXT NOT NULL,
    nightly_time  TEXT,                         -- "HH:MM" local, NULL = off
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    title            TEXT NOT NULL,
    due_date         TEXT NOT NULL,             -- YYYY-MM-DD, user's timezone
    done             INTEGER NOT NULL DEFAULT 0,
    postponed_count  INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_user_date ON tasks(user_id, due_date);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    title           TEXT NOT NULL,
    start_utc       TEXT NOT NULL,              -- ISO 8601, UTC
    remind_minutes  INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_user_start ON events(user_id, start_utc);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utc_text(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text)


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    # ----- users -----

    def ensure_user(self, user_id: int, first_name: str, tz: str, nightly_time: str) -> tuple[sqlite3.Row, bool]:
        """Return (user, created). Updates the stored first name if it changed."""
        row = self.get_user(user_id)
        if row:
            if row["first_name"] != first_name:
                self._exec("UPDATE users SET first_name = ? WHERE id = ?", (first_name, user_id))
                row = self.get_user(user_id)
            return row, False
        self._exec(
            "INSERT INTO users (id, first_name, timezone, nightly_time, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, first_name, tz, nightly_time, _now()),
        )
        return self.get_user(user_id), True

    def get_user(self, user_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def all_users(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM users").fetchall()

    def set_timezone(self, user_id: int, tz: str) -> None:
        self._exec("UPDATE users SET timezone = ? WHERE id = ?", (tz, user_id))

    def set_nightly_time(self, user_id: int, hhmm: str | None) -> None:
        self._exec("UPDATE users SET nightly_time = ? WHERE id = ?", (hhmm, user_id))

    # ----- tasks -----

    def add_task(self, user_id: int, title: str, due: date) -> int:
        cur = self._exec(
            "INSERT INTO tasks (user_id, title, due_date, created_at) VALUES (?, ?, ?, ?)",
            (user_id, title, due.isoformat(), _now()),
        )
        return cur.lastrowid

    def get_task(self, user_id: int, task_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
        ).fetchone()

    def tasks_on(self, user_id: int, day: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE user_id = ? AND due_date = ? ORDER BY done, id",
            (user_id, day.isoformat()),
        ).fetchall()

    def overdue_tasks(self, user_id: int, before: date) -> list[sqlite3.Row]:
        """Unfinished tasks whose date is earlier than `before`."""
        return self.conn.execute(
            "SELECT * FROM tasks WHERE user_id = ? AND due_date < ? AND done = 0 ORDER BY due_date, id",
            (user_id, before.isoformat()),
        ).fetchall()

    def rename_task(self, user_id: int, task_id: int, title: str) -> bool:
        cur = self._exec("UPDATE tasks SET title = ? WHERE id = ? AND user_id = ?", (title, task_id, user_id))
        return cur.rowcount > 0

    def postpone_task(self, user_id: int, task_id: int, new_due: date) -> bool:
        cur = self._exec(
            "UPDATE tasks SET due_date = ?, postponed_count = postponed_count + 1 WHERE id = ? AND user_id = ?",
            (new_due.isoformat(), task_id, user_id),
        )
        return cur.rowcount > 0

    def move_unfinished(self, user_id: int, up_to: date, new_due: date) -> int:
        """Move every unfinished task dated on or before `up_to` to `new_due`."""
        cur = self._exec(
            "UPDATE tasks SET due_date = ?, postponed_count = postponed_count + 1 "
            "WHERE user_id = ? AND done = 0 AND due_date <= ?",
            (new_due.isoformat(), user_id, up_to.isoformat()),
        )
        return cur.rowcount

    def set_task_done(self, user_id: int, task_id: int, done: bool) -> bool:
        cur = self._exec(
            "UPDATE tasks SET done = ? WHERE id = ? AND user_id = ?", (int(done), task_id, user_id)
        )
        return cur.rowcount > 0

    def delete_task(self, user_id: int, task_id: int) -> bool:
        cur = self._exec("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        return cur.rowcount > 0

    # ----- events -----

    def add_event(self, user_id: int, title: str, start: datetime, remind_minutes: int) -> int:
        cur = self._exec(
            "INSERT INTO events (user_id, title, start_utc, remind_minutes, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, title, _utc_text(start), remind_minutes, _now()),
        )
        return cur.lastrowid

    def get_event(self, user_id: int, event_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM events WHERE id = ? AND user_id = ?", (event_id, user_id)
        ).fetchone()

    def events_between(self, user_id: int, start: datetime, end: datetime) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events WHERE user_id = ? AND start_utc >= ? AND start_utc < ? ORDER BY start_utc",
            (user_id, _utc_text(start), _utc_text(end)),
        ).fetchall()

    def upcoming_events(self, user_id: int, after: datetime, limit: int = 15) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events WHERE user_id = ? AND start_utc >= ? ORDER BY start_utc LIMIT ?",
            (user_id, _utc_text(after), limit),
        ).fetchall()

    def all_future_events(self, after: datetime) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events WHERE start_utc >= ? ORDER BY start_utc", (_utc_text(after),)
        ).fetchall()

    def rename_event(self, user_id: int, event_id: int, title: str) -> bool:
        cur = self._exec("UPDATE events SET title = ? WHERE id = ? AND user_id = ?", (title, event_id, user_id))
        return cur.rowcount > 0

    def move_event(self, user_id: int, event_id: int, start: datetime) -> bool:
        cur = self._exec(
            "UPDATE events SET start_utc = ? WHERE id = ? AND user_id = ?", (_utc_text(start), event_id, user_id)
        )
        return cur.rowcount > 0

    def delete_event(self, user_id: int, event_id: int) -> bool:
        cur = self._exec("DELETE FROM events WHERE id = ? AND user_id = ?", (event_id, user_id))
        return cur.rowcount > 0
