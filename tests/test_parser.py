import json
import subprocess
import sys
import unittest

from workoutbridge.parser import parse


class ParserTests(unittest.TestCase):
    def test_units_and_effort(self):
        draft = parse("Warm up 1 mi easy; Run 600 m hard; Cool down 5 min")
        self.assertEqual([s.duration for s in draft.steps], [1609.344, 600, 300])
        self.assertEqual(draft.steps[1].label, "hard")
        self.assertTrue(draft.requires_review)
        self.assertFalse(draft.unresolved)

    def test_lap(self):
        self.assertEqual(parse("Run until lap").steps[0].unit, "lap_button")

    def test_no_invented_steps(self):
        self.assertEqual(len(parse("Run 15 min easy").steps), 1)

    def test_unknown_repeats_are_not_partially_parsed(self):
        text = "4 x 200 m in 62-64 sec; 2 min walk/jog recovery"
        draft = parse(text)
        self.assertFalse(draft.steps)
        self.assertEqual(len(draft.unresolved), 2)
        self.assertEqual(draft.original_text, text)

    def test_explicit_easy_run_is_not_rest(self):
        step = parse("Run 2 min easy").steps[0]
        self.assertEqual(step.kind, "run")

    def test_invalid_duration(self):
        for text in ("Run 0 min", "Run -2 min", "Run nan min"):
            with self.subTest(text=text):
                self.assertTrue(parse(text).unresolved)

    def test_trailing_instructions_not_dropped(self):
        self.assertTrue(parse("Run 15 min unless injured").unresolved)

    def test_blank(self):
        self.assertTrue(parse(" ; ").unresolved)

    def test_cli(self):
        for text, code in (("Run 10 min", 0), ("unknown", 2)):
            result = subprocess.run(
                [sys.executable, "-m", "workoutbridge.cli"],
                input=text, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, code)
            self.assertTrue(json.loads(result.stdout)["requires_review"])
