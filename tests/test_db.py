import unittest
from datetime import date, datetime, timedelta, timezone

from bot.db import Database, parse_utc

DAY = date(2026, 10, 1)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.db.ensure_user(1, "Me", "America/Toronto", "21:00")
        self.db.ensure_user(2, "Friend", "UTC", "21:00")

    def test_ensure_user_is_idempotent(self):
        user, created = self.db.ensure_user(1, "Me again", "UTC", "22:00")
        self.assertFalse(created)
        self.assertEqual(user["timezone"], "America/Toronto")
        self.assertEqual(user["first_name"], "Me again")

    def test_task_lifecycle(self):
        tid = self.db.add_task(1, "Buy milk", DAY)
        self.assertEqual([t["title"] for t in self.db.tasks_on(1, DAY)], ["Buy milk"])

        self.assertTrue(self.db.rename_task(1, tid, "Buy oat milk"))
        self.assertTrue(self.db.set_task_done(1, tid, True))
        self.assertEqual(self.db.get_task(1, tid)["done"], 1)

        self.assertTrue(self.db.postpone_task(1, tid, DAY + timedelta(days=1)))
        task = self.db.get_task(1, tid)
        self.assertEqual(task["due_date"], "2026-10-02")
        self.assertEqual(task["postponed_count"], 1)

        self.assertTrue(self.db.delete_task(1, tid))
        self.assertIsNone(self.db.get_task(1, tid))

    def test_users_cannot_touch_each_others_tasks(self):
        tid = self.db.add_task(1, "Private", DAY)
        self.assertIsNone(self.db.get_task(2, tid))
        self.assertFalse(self.db.delete_task(2, tid))
        self.assertFalse(self.db.rename_task(2, tid, "hacked"))
        self.assertEqual(self.db.get_task(1, tid)["title"], "Private")

    def test_move_unfinished(self):
        self.db.add_task(1, "old", DAY - timedelta(days=2))
        self.db.add_task(1, "today", DAY)
        done = self.db.add_task(1, "finished", DAY)
        self.db.set_task_done(1, done, True)
        self.db.add_task(2, "friend's", DAY)

        moved = self.db.move_unfinished(1, DAY, DAY + timedelta(days=1))
        self.assertEqual(moved, 2)
        self.assertEqual(len(self.db.tasks_on(1, DAY + timedelta(days=1))), 2)
        self.assertEqual(len(self.db.tasks_on(2, DAY)), 1)

    def test_overdue(self):
        self.db.add_task(1, "late", DAY - timedelta(days=1))
        self.db.add_task(1, "now", DAY)
        self.assertEqual([t["title"] for t in self.db.overdue_tasks(1, DAY)], ["late"])

    def test_events_stored_in_utc(self):
        start = datetime(2026, 10, 3, 19, 0, tzinfo=timezone(timedelta(hours=-4)))
        eid = self.db.add_event(1, "Gaming", start, 30)
        stored = parse_utc(self.db.get_event(1, eid)["start_utc"])
        self.assertEqual(stored, start)
        self.assertEqual(stored.utcoffset(), timedelta(0))

        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.assertEqual(len(self.db.upcoming_events(1, now)), 1)
        self.assertEqual(len(self.db.upcoming_events(2, now)), 0)
        self.assertEqual(len(self.db.all_future_events(now)), 1)

        later = start + timedelta(days=1)
        self.assertTrue(self.db.move_event(1, eid, later))
        self.assertEqual(parse_utc(self.db.get_event(1, eid)["start_utc"]), later)
        self.assertFalse(self.db.delete_event(2, eid))
        self.assertTrue(self.db.delete_event(1, eid))


if __name__ == "__main__":
    unittest.main()
