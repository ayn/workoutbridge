import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock

import httpx

from workoutbridge.ai import Interpreter, OpenAIClient
from workoutbridge.calendar import Event

USER = "a" * 32
OTHER = "b" * 32


def proposal(**updates):
    return {
        "structured_text": "Run 35 min easy",
        "notes": [],
        "unresolved": [],
        "assumptions": [],
        "evidence": ["35 minutes easy"],
        **updates,
    }


class AITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.event = Event(
            "private-feed", "private-uid", "", "2030-01-01", "Morning run", "35 minutes easy"
        )
        self.client = Mock(return_value=(proposal(), {"input_tokens": 2000, "output_tokens": 1000}))
        self.engine = Interpreter(self.root / USER, self.client, budget_root=self.root)

    def other(self, engine):
        return Interpreter(
            self.root / OTHER,
            self.client,
            budget_root=self.root,
            model=engine.model,
            monthly_budget=str(engine.budget / 1_000_000_000),
            clock=engine.clock,
        )

    def test_candidate_is_separate_and_cached_without_changing_the_event(self):
        before = asdict(self.event)
        result = self.engine.interpret(self.event)
        self.assertEqual(result["status"], "candidate")
        self.assertTrue(result["requires_review"])
        self.assertEqual(result["draft"]["steps"][0]["duration"], 2100)
        self.assertEqual(
            result["usage"],
            {"input_tokens": 2000, "output_tokens": 1000, "cost_nanodollars": 750000},
        )
        self.assertEqual(asdict(self.event), before)
        self.assertEqual(
            self.engine.interpret(replace(self.event, uid="other", date="2030-01-02")), result
        )
        self.client.assert_called_once()
        request = self.client.call_args.args[0]
        self.assertEqual(set(request), {"sport", "title", "prescription"})
        self.assertNotIn("private-", json.dumps(request))

    def test_tenant_model_and_prescription_isolation(self):
        self.engine.interpret(self.event)
        self.other(self.engine).interpret(self.event)
        self.engine.interpret(replace(self.event, description="40 minutes easy"))
        Interpreter(
            self.root / USER, self.client, budget_root=self.root, model="gpt-6.1-sol"
        ).interpret(self.event)
        self.assertEqual(self.client.call_count, 4)
        self.assertEqual(len(self.other(self.engine).results()), 1)

    def test_evidence_may_wrap_a_verbatim_quote_but_may_not_change_its_words(self):
        value = self.engine.request_value(self.event)
        for quote in ('"35 minutes easy"', "“35 minutes easy”", "'35 minutes easy'"):
            result = self.engine.validate(proposal(evidence=[quote]), value)
            self.assertEqual(result["status"], "candidate")
            self.assertEqual(result["evidence"], ["35 minutes easy"])
        with self.assertRaises(ValueError):
            self.engine.validate(proposal(evidence=['"35 minutes hard"']), value)

    def test_unknown_text_assumptions_and_invalid_generated_steps_stay_blocked(self):
        for output in (
            proposal(unresolved=["Choose bike or run"]),
            proposal(assumptions=["Assumed ten minute recovery"]),
            proposal(structured_text="Run 35 min; invent another step"),
            proposal(evidence=["not in the input"]),
            proposal(structured_text="Run 0 min"),
            {"structured_text": "Run 35 min"},
        ):
            with self.subTest(output=output), tempfile.TemporaryDirectory() as directory:
                engine = Interpreter(Path(directory), Mock(return_value=(output, {})))
                self.assertNotEqual(engine.interpret(self.event)["status"], "candidate")

    def test_atomic_cache_claim_avoids_duplicate_requests(self):
        entered, release = threading.Event(), threading.Event()

        def slow(*_):
            entered.set()
            self.assertTrue(release.wait(5))
            return proposal(), {}

        self.client.side_effect = slow
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.engine.interpret, self.event)
            self.assertTrue(entered.wait(5))
            try:
                second = pool.submit(
                    Interpreter(self.root / USER, self.client, budget_root=self.root).interpret,
                    self.event,
                )
                self.assertEqual(second.result(5)["status"], "pending")
            finally:
                release.set()
            self.assertEqual(first.result(5)["status"], "candidate")
        self.client.assert_called_once()

    def test_shared_budget_reserves_before_request_and_counts_all_models_and_tenants(self):
        engine = Interpreter(
            self.root / USER, self.client, budget_root=self.root, monthly_budget="0.006"
        )
        self.assertEqual(engine.interpret(self.event)["status"], "candidate")
        # Upper estimate permits the input cache-write premium; Sol still exceeds the budget.
        sol = Interpreter(
            self.root / USER,
            self.client,
            budget_root=self.root,
            model="gpt-6.1-sol",
            monthly_budget="0.006",
        )
        self.assertEqual(self.other(sol).interpret(self.event)["status"], "budget_exhausted")
        self.client.assert_called_once()

    def test_timeout_is_not_retried_or_leaked_and_retains_full_reservation(self):
        self.client.side_effect = RuntimeError("secret-token private-feed-url")
        engine = Interpreter(
            self.root / USER, self.client, budget_root=self.root, monthly_budget="0.006"
        )
        result = engine.interpret(self.event)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("secret-token", json.dumps(result))
        self.assertEqual(engine.interpret(self.event), result)
        self.assertEqual(self.other(engine).interpret(self.event)["status"], "budget_exhausted")
        self.client.assert_called_once()

    def test_budget_resets_at_utc_month_boundary(self):
        clock = Mock(return_value=1893456000)  # January 2030
        self.client.return_value = (proposal(), {})
        engine = Interpreter(
            self.root / USER,
            self.client,
            budget_root=self.root,
            monthly_budget="0.006",
            clock=clock,
        )
        engine.interpret(self.event)
        self.assertEqual(self.other(engine).interpret(self.event)["status"], "budget_exhausted")
        clock.return_value = 1896134400  # February 2030
        self.assertEqual(self.other(engine).interpret(self.event)["status"], "candidate")

    def test_unsupported_sports_cancelled_and_oversized_inputs_do_not_call_api(self):
        for event in (
            replace(self.event, cancelled=True),
            replace(self.event, sport="ambiguous"),
            replace(self.event, sport="swimming"),
            replace(self.event, description="x" * 9000),
        ):
            self.assertEqual(self.engine.interpret(event)["status"], "input_rejected")
        self.client.assert_not_called()

    def test_private_cache_and_redacted_request(self):
        event = replace(
            self.event,
            title="Run",
            description="35 minutes easy; see https://private.example/secret or coach@example.invalid",
        )
        self.engine.interpret(event)
        sent = json.dumps(self.client.call_args.args[0])
        self.assertNotIn("private.example", sent)
        self.assertNotIn("coach@example.invalid", sent)
        self.assertEqual((self.root / USER / "ai.sqlite").stat().st_mode & 0o777, 0o600)

    def test_private_subscription_schemes_are_redacted(self):
        event = replace(
            self.event,
            description="35 minutes easy; webcals://calendar.example/token caldav://calendar.example/secret",
        )
        self.engine.interpret(event)
        self.assertNotIn("calendar.example", json.dumps(self.client.call_args.args[0]))

    def test_observer_only_sends_unresolved_workouts_and_never_edits_plan(self):
        plan = {
            "items": [
                {"event": asdict(self.event), "error": "Review"},
                {"event": asdict(replace(self.event, uid="good"))},
            ]
        }
        before = json.dumps(plan)
        self.engine.observe_plan(plan)
        self.assertEqual(json.dumps(plan), before)
        self.client.assert_called_once()

    def test_next_refresh_does_not_starve_workouts_after_cached_proposals(self):
        plan = {
            "items": [
                {"event": asdict(replace(self.event, title=f"Run {i}")), "error": "Review"}
                for i in range(4)
            ]
        }
        self.engine.observe_plan(plan)
        self.assertEqual(self.client.call_count, 3)
        self.engine.observe_plan(plan)
        self.assertEqual(self.client.call_count, 4)

    def test_unsupported_inputs_do_not_starve_supported_workouts(self):
        plan = {
            "items": [
                {"event": asdict(replace(self.event, sport="swimming")), "error": "Review"}
                for _ in range(3)
            ]
            + [{"event": asdict(self.event), "error": "Review"}]
        }
        self.engine.observe_plan(plan)
        self.client.assert_called_once()


class OpenAIClientTests(unittest.TestCase):
    def test_strict_schema_no_storage_no_tools_and_bounded_response(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key"
            key.write_text("synthetic-api-key")
            key.chmod(0o600)
            requests = []

            def handle(request):
                requests.append(request)
                return httpx.Response(
                    200,
                    json={
                        "status": "completed",
                        "usage": {"input_tokens": 100, "output_tokens": 50},
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {"type": "output_text", "text": json.dumps(proposal())}
                                ],
                            }
                        ],
                    },
                )

            with httpx.Client(transport=httpx.MockTransport(handle)) as http:
                client = OpenAIClient(key, http=http)
                output, usage = client(
                    {"sport": "running", "title": "Run", "prescription": "35 minutes easy"},
                    "gpt-6-luna",
                )
            self.assertEqual(output, proposal())
            self.assertEqual(usage["output_tokens"], 50)
            request = requests[0]
            body = json.loads(request.content)
            self.assertEqual(str(request.url), "https://api.openai.com/v1/responses")
            self.assertFalse(body["store"])
            self.assertNotIn("tools", body)
            self.assertTrue(body["text"]["format"]["strict"])
            self.assertLessEqual(body["max_output_tokens"], 4096)

    def test_refusal_incomplete_error_and_oversized_reply_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key"
            key.write_text("synthetic-api-key")
            key.chmod(0o600)
            for reply in (
                httpx.Response(429, text="sensitive provider error"),
                httpx.Response(200, json={"status": "incomplete", "output": []}),
                httpx.Response(
                    200,
                    json={
                        "status": "completed",
                        "output": [
                            {"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}
                        ],
                    },
                ),
                httpx.Response(200, content=b"x" * 70000),
            ):
                with (
                    self.subTest(reply=reply),
                    httpx.Client(transport=httpx.MockTransport(lambda _: reply)) as http,
                ):
                    with self.assertRaises(ValueError):
                        OpenAIClient(key, http=http)({}, "gpt-6-luna")
