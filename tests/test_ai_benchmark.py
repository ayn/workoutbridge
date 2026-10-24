import unittest
from unittest.mock import Mock

from workoutbridge.ai_benchmark import CASES, evaluate, score
from workoutbridge.parser import parse


class AIBenchmarkTests(unittest.TestCase):
    def test_synthetic_gold_workouts_compile_and_include_explicit_review_cases(self):
        self.assertGreaterEqual(len(CASES), 30)
        self.assertGreaterEqual(sum(case.expected is None for case in CASES), 10)
        for case in CASES:
            if case.expected:
                self.assertFalse(parse(case.expected, sport=case.sport).unresolved, case.name)

    def test_scoring_detects_wrong_distances_counts_and_false_clearances(self):
        case = next(case for case in CASES if case.expected is not None)
        correct = {
            "status": "candidate",
            "draft": parse(case.expected, sport=case.sport).to_dict(),
            "notes": [],
        }
        self.assertEqual(score(case, correct), "correct")
        self.assertEqual(score(case, {"status": "failed"}), "failure")
        self.assertEqual(score(case, {"status": "review"}), "unnecessary_review")
        incorrect = {**correct, "draft": parse("Run 999 miles").to_dict()}
        self.assertEqual(score(case, incorrect), "incorrect_candidate")
        self.assertEqual(
            score(case, {**correct, "notes": ["Run another mile"]}), "incorrect_candidate"
        )
        ambiguous = next(case for case in CASES if case.expected is None)
        self.assertEqual(score(ambiguous, correct), "false_clearance")
        self.assertEqual(score(ambiguous, {"status": "review"}), "correct_review")

    def test_unsupported_sports_do_not_count_as_model_successes(self):
        case = next(case for case in CASES if case.sport == "swimming")
        self.assertEqual(score(case, {"status": "input_rejected"}), "unsupported_sport")

    def test_evaluation_counts_failures_separately_from_correct_abstention(self):
        engine = Mock()
        engine.model = "synthetic"
        engine.interpret.return_value = {"status": "failed"}
        report = evaluate(engine, CASES[:2])
        self.assertEqual(report["counts"], {"failure": 2})
        self.assertEqual(report["cases"], 2)
        self.assertEqual(len(report["results"]), 2)
