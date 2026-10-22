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

    def test_explicit_structured_block_separates_steps_from_preserved_notes(self):
        from workoutbridge.cli import review_item
        from workoutbridge.prescriptions import normalize_workout

        description = "Coach guidance: walking is fine.\n[WorkoutBridge]\nRun 12 min easy\n[/WorkoutBridge]\nStop if uncomfortable."
        event = self.load(
            calendar(
                "UID:synthetic-structured\r\nDTSTART;VALUE=DATE:20270105\r\n"
                "SUMMARY:Training\r\nDESCRIPTION:" + description.replace("\n", "\\n")
            )
        )[0]
        normalized = normalize_workout(event)
        self.assertEqual(normalized.structured_text, "Run 12 min easy")
        self.assertEqual(normalized.description, description)
        result = review_item("synthetic", normalized)
        self.assertNotIn("error", result)
        self.assertEqual(result["payload"]["description"], description)
        self.assertEqual(
            result["payload"]["workoutSegments"][0]["workoutSteps"][0]["endConditionValue"], 720
        )

    def test_malformed_or_ambiguous_structured_blocks_require_review(self):
        from workoutbridge.cli import review_item
        from workoutbridge.prescriptions import normalize_workout

        for block in (
            "[WorkoutBridge]\nRun 12 min easy",
            "[WorkoutBridge]\nRun 10-15 min easy\n[/WorkoutBridge]",
            "[WorkoutBridge]\nRun 12 min easy\n[/WorkoutBridge]\n[WorkoutBridge]\nRun 3 min\n[/WorkoutBridge]",
            "[WorkoutBridge]\nRun 12 min easy\n[/WorkoutBridge]\n[WorkoutBridge]",
            "[WorkoutBridge]\n\n[/WorkoutBridge]",
        ):
            with self.subTest(block=block):
                event = self.load(
                    calendar(
                        "UID:synthetic-invalid\r\nDTSTART;VALUE=DATE:20270105\r\nDESCRIPTION:"
                        + block.replace("\n", "\\n")
                    )
                )[0]
                self.assertIn("error", review_item("synthetic", normalize_workout(event)))

    def test_utc_date_converted_to_athlete_timezone(self):
        event = self.load(calendar("UID:a\r\nDTSTART:20270105T180000Z\r\nSUMMARY:Run 15 min"))[0]
        self.assertEqual(event.date, "2027-01-06")
        self.assertEqual(event.prescription, "Run 15 min")

    def test_floating_time_uses_explicit_timezone(self):
        event = self.load(calendar("UID:a\r\nDTSTART:20270105T230000"))[0]
        self.assertEqual(event.date, "2027-01-05")

    def test_unknown_explicit_timezone_is_not_floating(self):
        with self.assertRaises(ValueError):
            self.load(calendar("UID:a\r\nDTSTART;TZID=Not/AZone:20270105T230000"))

    def test_unknown_exclusion_timezone_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load(
                calendar(
                    "UID:a\r\nDTSTART;TZID=America/New_York:20270105T230000"
                    "\r\nRRULE:FREQ=WEEKLY;COUNT=2"
                    "\r\nEXDATE;TZID=Not/AZone:20270112T230000"
                )
            )

    def test_unknown_recurrence_identity_timezone_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load(
                calendar(
                    "UID:a\r\nDTSTART;TZID=America/New_York:20270106T230000"
                    "\r\nRECURRENCE-ID;TZID=Not/AZone:20270105T230000"
                )
            )

    def test_valid_named_timezone_preserved(self):
        event = self.load(calendar("UID:a\r\nDTSTART;TZID=America/New_York:20270105T230000"))[0]
        self.assertEqual(event.date, "2027-01-06")

    def test_custom_vtimezone_preserved(self):
        data = calendar("UID:a\r\nDTSTART;TZID=Synthetic/Eastern:20270105T230000").replace(
            b"BEGIN:VEVENT",
            (
                b"BEGIN:VTIMEZONE\r\nTZID:Synthetic/Eastern\r\nBEGIN:STANDARD\r\n"
                b"DTSTART:19700101T000000\r\nTZOFFSETFROM:-0500\r\nTZOFFSETTO:-0500\r\n"
                b"END:STANDARD\r\nEND:VTIMEZONE\r\nBEGIN:VEVENT"
            ),
        )
        self.assertEqual(self.load(data)[0].date, "2027-01-06")

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
