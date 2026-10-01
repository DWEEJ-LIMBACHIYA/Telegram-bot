"""End-to-end checks: real handlers, a fake Telegram API (no network)."""

import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone

try:
    from telegram import Update
    from telegram.request import BaseRequest
except ImportError:  # library not installed
    Update = None
    BaseRequest = object

ME = {"id": 999, "is_bot": True, "first_name": "Planner", "username": "planner_bot"}
USER = {"id": 42, "is_bot": False, "first_name": "Dee"}
CHAT = {"id": 42, "type": "private", "first_name": "Dee"}


class FakeTelegram(BaseRequest):
    """Records every Bot API call and returns plausible responses."""

    def __init__(self):
        self.calls = []
        self._msg_id = 100

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    @property
    def read_timeout(self):
        return 1

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        params = request_data.json_parameters if request_data else {}
        self.calls.append((endpoint, params))
        if endpoint == "getMe":
            result = ME
        elif endpoint in ("sendMessage", "editMessageText", "editMessageReplyMarkup"):
            self._msg_id += 1
            result = {"message_id": self._msg_id, "date": 0, "chat": CHAT, "from": ME, "text": params.get("text", "")}
        else:
            result = True
        return 200, json.dumps({"ok": True, "result": result}).encode()

    def texts(self, endpoint=("sendMessage", "editMessageText")):
        return [p.get("text", "") for e, p in self.calls if e in endpoint]

    def buttons(self):
        """callback_data of the most recent message's keyboard."""
        for e, p in reversed(self.calls):
            if "reply_markup" in p and p["reply_markup"]:
                markup = json.loads(p["reply_markup"])
                return [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
        return []


@unittest.skipIf(Update is None, "python-telegram-bot not installed")
class BotFlowTests(unittest.TestCase):
    def setUp(self):
        os.environ.update(BOT_TOKEN="123:TEST", DEFAULT_TIMEZONE="America/Toronto", DB_PATH=":memory:", ALLOWED_USER_IDS="")
        from bot import __main__ as entry

        self.fake = FakeTelegram()
        self.entry = entry
        self.loop = asyncio.new_event_loop()
        self.app = entry.build_app(request=self.fake)
        self.loop.run_until_complete(self.app.initialize())
        self.loop.run_until_complete(entry.post_init(self.app))
        self._uid = 0

    def tearDown(self):
        self.loop.run_until_complete(self.app.shutdown())
        self.loop.close()

    def _update(self, payload):
        self._uid += 1
        update = Update.de_json({"update_id": self._uid, **payload}, self.app.bot)
        self.loop.run_until_complete(self.app.process_update(update))

    def send(self, text, user=USER):
        msg = {"message_id": self._uid + 1, "date": 0, "chat": {**CHAT, "id": user["id"]}, "from": user, "text": text}
        if text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        self._update({"message": msg})
        return self.fake.texts()[-1]

    def tap(self, data):
        self._update({"callback_query": {
            "id": str(self._uid), "from": USER, "chat_instance": "x", "data": data,
            "message": {"message_id": 1, "date": 0, "chat": CHAT, "from": ME, "text": "old"},
        }})
        return self.fake.texts()[-1]

    @property
    def db(self):
        return self.app.bot_data["db"]

    def test_start_registers_user_and_nightly_job(self):
        reply = self.send("/start")
        self.assertIn("America/Toronto", reply)
        self.assertIsNotNone(self.db.get_user(42))
        self.assertTrue(self.app.job_queue.get_jobs_by_name("night:42"))

    def test_free_text_adds_tasks_and_events(self):
        reply = self.send("Buy milk\ntomorrow Call mom\nsat 7pm Gaming night")
        self.assertIn("Buy milk", reply)
        self.assertIn("Call mom", reply)
        self.assertIn("19:00", reply)
        events = self.db.all_future_events(datetime.now(timezone.utc) - timedelta(days=1))
        self.assertEqual([e["title"] for e in events], ["Gaming night"])
        self.assertTrue(self.app.job_queue.get_jobs_by_name(f"ev:{events[0]['id']}"))

    def test_task_buttons(self):
        self.send("/add Write report")
        reply = self.send("/today")
        self.assertIn("Write report", reply)
        open_btn = next(b for b in self.fake.buttons() if b.startswith("t:open:"))
        tid = int(open_btn.split(":")[2])

        self.tap(open_btn)
        self.tap(f"t:done:{tid}")
        self.assertEqual(self.db.get_task(42, tid)["done"], 1)

        self.tap(f"t:edit:{tid}")
        self.send("Write final report")
        self.assertEqual(self.db.get_task(42, tid)["title"], "Write final report")

        self.tap(f"t:pp:{tid}")
        to_btn = next(b for b in self.fake.buttons() if b.startswith(f"t:to:{tid}:"))
        self.tap(to_btn)
        self.assertEqual(self.db.get_task(42, tid)["postponed_count"], 1)

        self.tap(f"t:pick:{tid}")
        self.send("not a date")
        self.assertIn("couldn't read", self.fake.texts()[-1])
        self.send("+5")
        self.assertEqual(self.db.get_task(42, tid)["postponed_count"], 2)

        self.tap(f"t:del:{tid}")
        self.tap(f"t:delok:{tid}")
        self.assertIsNone(self.db.get_task(42, tid))

    def test_event_buttons(self):
        self.send("/event tomorrow 10am Dentist")
        eid = self.db.all_future_events(datetime.now(timezone.utc) - timedelta(days=1))[0]["id"]
        before = self.db.get_event(42, eid)["start_utc"]

        self.tap(f"e:sh:{eid}:60")
        after = self.db.get_event(42, eid)["start_utc"]
        self.assertEqual(datetime.fromisoformat(after) - datetime.fromisoformat(before), timedelta(hours=1))

        self.tap(f"e:pick:{eid}")
        self.send("15:30")
        self.assertIn("15:30", self.fake.texts()[-1])

        self.tap(f"e:delok:{eid}")
        self.assertIsNone(self.db.get_event(42, eid))
        self.assertFalse(self.app.job_queue.get_jobs_by_name(f"ev:{eid}"))

    def test_nightly_prompt_collects_items_for_tomorrow(self):
        self.send("/start")
        self.send("Unfinished thing")
        job = self.app.job_queue.get_jobs_by_name("night:42")[0]
        self.loop.run_until_complete(job.run(self.app))
        prompt = self.fake.texts()[-1]
        self.assertIn("Planning for tomorrow", prompt)
        self.assertIn("Unfinished thing", prompt)

        self.send("Gym")
        tomorrow = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("America/Toronto")).date() + timedelta(days=1)
        self.assertEqual([t["title"] for t in self.db.tasks_on(42, tomorrow)], ["Gym"])

        self.tap("nightly:done")
        self.send("Back to normal")
        self.assertEqual(len(self.db.tasks_on(42, tomorrow)), 1)

    def test_settings(self):
        self.send("/timezone Asia/Kolkata")
        self.assertEqual(self.db.get_user(42)["timezone"], "Asia/Kolkata")
        self.send("/timezone Mars/Base")
        self.assertIn("don't know", self.fake.texts()[-1])
        self.send("/nightly 9:30pm")
        self.assertEqual(self.db.get_user(42)["nightly_time"], "21:30")
        self.send("/nightly off")
        self.assertIsNone(self.db.get_user(42)["nightly_time"])
        self.assertFalse(self.app.job_queue.get_jobs_by_name("night:42"))

    def test_allow_list_blocks_strangers(self):
        self.app.bot_data["config"] = self.app.bot_data["config"].__class__(
            **{**self.app.bot_data["config"].__dict__, "allowed_user_ids": frozenset({1})}
        )
        reply = self.send("hello")
        self.assertIn("private bot", reply)
        self.assertIn("42", reply)
        self.assertIsNone(self.db.get_user(42))


if __name__ == "__main__":
    unittest.main()
