import unittest
from datetime import date, time

from bot.parsing import (
    fmt_day,
    parse_date,
    parse_event,
    parse_reschedule,
    parse_task,
    parse_time,
)

TODAY = date(2026, 10, 1)  # a Thursday


class TimeTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_time("19:00"), time(19, 0))
        self.assertEqual(parse_time("7pm"), time(19, 0))
        self.assertEqual(parse_time("7:30pm"), time(19, 30))
        self.assertEqual(parse_time("7 pm"), time(19, 0))
        self.assertEqual(parse_time("12am"), time(0, 0))
        self.assertEqual(parse_time("12pm"), time(12, 0))
        self.assertEqual(parse_time("noon"), time(12, 0))

    def test_rejects_ambiguous_or_invalid(self):
        self.assertIsNone(parse_time("7"))
        self.assertIsNone(parse_time("25:00"))
        self.assertIsNone(parse_time("13pm"))
        self.assertIsNone(parse_time("soon"))


class DateTests(unittest.TestCase):
    def test_words(self):
        self.assertEqual(parse_date("today", TODAY), TODAY)
        self.assertEqual(parse_date("tmrw", TODAY), date(2026, 10, 2))
        self.assertEqual(parse_date("+3", TODAY), date(2026, 10, 4))
        self.assertEqual(parse_date("in 10 days", TODAY), date(2026, 10, 11))
        self.assertEqual(parse_date("next week", TODAY), date(2026, 10, 8))

    def test_weekdays(self):
        self.assertEqual(parse_date("sat", TODAY), date(2026, 10, 3))
        self.assertEqual(parse_date("thursday", TODAY), TODAY)  # today counts
        self.assertEqual(parse_date("next thu", TODAY), date(2026, 10, 8))
        self.assertEqual(parse_date("next sat", TODAY), date(2026, 10, 3))

    def test_calendar_dates(self):
        self.assertEqual(parse_date("2026-12-25", TODAY), date(2026, 12, 25))
        self.assertEqual(parse_date("5 oct", TODAY), date(2026, 10, 5))
        self.assertEqual(parse_date("Oct 5th", TODAY), date(2026, 10, 5))
        self.assertEqual(parse_date("3 jan", TODAY), date(2027, 1, 3))  # already past -> next year
        self.assertIsNone(parse_date("31 feb", TODAY))
        self.assertIsNone(parse_date("someday", TODAY))


class TaskTests(unittest.TestCase):
    def test_default_today(self):
        self.assertEqual(parse_task("Buy milk", TODAY), (TODAY, "Buy milk"))

    def test_date_first_or_last(self):
        self.assertEqual(parse_task("tomorrow Buy milk", TODAY), (date(2026, 10, 2), "Buy milk"))
        self.assertEqual(parse_task("Buy milk tomorrow", TODAY), (date(2026, 10, 2), "Buy milk"))
        self.assertEqual(parse_task("Pay rent on 5 oct", TODAY), (date(2026, 10, 5), "Pay rent"))

    def test_empty(self):
        with self.assertRaises(ValueError):
            parse_task("   ", TODAY)


class EventTests(unittest.TestCase):
    def test_orders(self):
        expected = (date(2026, 10, 3), time(19, 0), "Gaming night")
        self.assertEqual(parse_event("sat 7pm Gaming night", TODAY), expected)
        self.assertEqual(parse_event("7pm sat Gaming night", TODAY), expected)
        self.assertEqual(parse_event("sat at 7pm Gaming night", TODAY), expected)
        self.assertEqual(parse_event("Gaming night sat at 7pm", TODAY), expected)
        self.assertEqual(parse_event("Gaming night 7 pm sat", TODAY), expected)

    def test_defaults_to_today(self):
        self.assertEqual(parse_event("18:30 Gym", TODAY), (TODAY, time(18, 30), "Gym"))

    def test_needs_time(self):
        with self.assertRaises(ValueError):
            parse_event("sat Gaming", TODAY)


class RescheduleTests(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(parse_reschedule("tomorrow 8pm", TODAY), (date(2026, 10, 2), time(20, 0)))
        self.assertEqual(parse_reschedule("20:30", TODAY), (None, time(20, 30)))
        self.assertEqual(parse_reschedule("sat", TODAY), (date(2026, 10, 3), None))
        with self.assertRaises(ValueError):
            parse_reschedule("whenever", TODAY)


class FormatTests(unittest.TestCase):
    def test_fmt_day(self):
        self.assertEqual(fmt_day(TODAY, TODAY), "Today")
        self.assertEqual(fmt_day(date(2026, 10, 2), TODAY), "Tomorrow")
        self.assertEqual(fmt_day(date(2026, 10, 5), TODAY), "Mon 5 Oct")
        self.assertEqual(fmt_day(date(2027, 1, 3), TODAY), "Sun 3 Jan 2027")


if __name__ == "__main__":
    unittest.main()
