import unittest
from datetime import date

from workoutbridge.calendar import import_calendar


def calendar(*events):
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//WorkoutBridge//Tests//EN\r\n"
        + "".join("BEGIN:VEVENT\r\n" + e + "\r\nEND:VEVENT\r\n" for e in events)
        + "END:VCALENDAR\r\n"
    ).encode()


class CalendarTests(unittest.TestCase):
    def load(self, data, **kwargs):
        return import_calendar(
            data,
            source="synthetic",
            timezone="Asia/Taipei",
            start=date(2027, 1, 1),
            end=date(2027, 2, 1),
            **kwargs,
        )

    def test_all_day_and_description_preserved(self):
        events = self.load(
            calendar(
                "UID:a\r\nDTSTART;VALUE=DATE:20270105\r\nSUMMARY:Easy run"
                "\r\nDESCRIPTION:Run 15 min easy"
            )
        )
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.uid, "a")
        self.assertEqual(event.date, "2027-01-05")
        self.assertEqual(event.title, "Easy run")
        self.assertEqual(event.prescription, "Run 15 min easy")
        self.assertEqual(event.source, "synthetic")

    def test_utc_date_converted_to_athlete_timezone(self):
        event = self.load(calendar("UID:a\r\nDTSTART:20270105T180000Z\r\nSUMMARY:Run 15 min"))[0]
        self.assertEqual(event.date, "2027-01-06")
        self.assertEqual(event.prescription, "Run 15 min")

    def test_floating_time_uses_explicit_timezone(self):
        event = self.load(calendar("UID:a\r\nDTSTART:20270105T230000"))[0]
        self.assertEqual(event.date, "2027-01-05")

    def test_recurrence_exclusion_and_moved_exception(self):
        events = self.load(
            calendar(
                "UID:r\r\nDTSTART;VALUE=DATE:20270105\r\nRRULE:FREQ=WEEKLY;COUNT=3"
                "\r\nEXDATE;VALUE=DATE:20270112\r\nSUMMARY:Run 10 min",
                "UID:r\r\nRECURRENCE-ID;VALUE=DATE:20270119"
                "\r\nDTSTART;VALUE=DATE:20270120\r\nSUMMARY:Run 12 min",
            )
        )
        self.assertEqual([e.date for e in events], ["2027-01-05", "2027-01-20"])
        self.assertEqual(events[1].recurrence_id, "2027-01-19")

    def test_cancelled_is_retained_for_review_not_published(self):
        event = self.load(calendar("UID:a\r\nDTSTART;VALUE=DATE:20270105\r\nSTATUS:CANCELLED"))[0]
        self.assertTrue(event.cancelled)

    def test_duplicate_source_identity_rejected(self):
        event = "UID:a\r\nDTSTART;VALUE=DATE:20270105"
        with self.assertRaises(ValueError):
            self.load(calendar(event, event))

    def test_invalid_or_unbounded_inputs(self):
        with self.assertRaises(ValueError):
            self.load(b"not a calendar")
        with self.assertRaises(ValueError):
            self.load(calendar("DTSTART;VALUE=DATE:20270105"))
        with self.assertRaises(ValueError):
            self.load(calendar("UID:a\r\nDTSTART;VALUE=DATE:20270105"), max_events=0)
        with self.assertRaises(ValueError):
            import_calendar(
                calendar(),
                source="s",
                timezone="UTC",
                start=date(2027, 1, 1),
                end=date(2030, 1, 1),
            )
