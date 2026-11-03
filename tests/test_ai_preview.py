import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

from workoutbridge.calendar import Event
from workoutbridge.cli import review_item
from workoutbridge.web import create_app


class AIPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.event = Event(
            "source", "synthetic", "", "2030-01-01", "Run: Morning", "Easy for half an hour"
        )
        self.candidate = replace(self.event, structured_text="Run 30 min easy")

    def resolver(self, plan):
        item = review_item(plan["account"], self.candidate)
        item["interpretation"] = {"model": "synthetic"}
        return {**plan, "items": [item]}

    def app(self, resolver, allowed=lambda: True):
        app = create_app(
            self.root,
            "https://bridge.example",
            "a" * 40,
            poll=False,
            resolve_plan=resolver,
            authorize_interpretation=allowed,
        )
        self.addCleanup(app.state.close)
        with sqlite3.connect(self.root / "web.sqlite") as db:
            for kind, value in (
                (
                    "source",
                    {
                        "id": "source",
                        "url": "https://example.invalid/feed.ics",
                        "timezone": "UTC",
                        "format": "generic",
                    },
                ),
                (
                    "sync",
                    {
                        "id": "sync",
                        "source": "source",
                        "profile": "synthetic",
                        "automatic": True,
                        "auto_account": "123",
                    },
                ),
            ):
                db.execute(
                    "INSERT INTO objects VALUES (?,?,?)", (kind, value["id"], json.dumps(value))
                )
        return app

    def patches(self):
        return (
            patch("workoutbridge.web.read_calendar", return_value=b"synthetic"),
            patch("workoutbridge.web.import_calendar", return_value=[self.event]),
            patch("workoutbridge.web.normalize_workout", side_effect=lambda event, **_: event),
            patch(
                "workoutbridge.web.load_profile",
                return_value={
                    "account_id": "123",
                    "session_dir": "/private/session",
                    "state_db": str(self.root / "ledger.sqlite"),
                },
            ),
        )

    def test_resolution_is_persisted_before_automatic_publishing(self):
        app = self.app(self.resolver)
        a, b, c, d = self.patches()
        with (
            a,
            b,
            c,
            d,
            patch("workoutbridge.web.GarminProvider.connect"),
            patch("workoutbridge.web.Publisher") as publisher,
        ):
            publisher.return_value.publish.return_value = "synthetic-id"
            app.state.poll_once("sync")
        publisher.return_value.publish.assert_called_once()
        self.assertEqual(publisher.return_value.publish.call_args.args[0], self.candidate)
        with sqlite3.connect(self.root / "web.sqlite") as db:
            plan = json.loads(
                db.execute("SELECT body FROM objects WHERE kind='plan'").fetchone()[0]
            )
        self.assertIn("hash", plan)
        self.assertNotIn("error", plan["items"][0])

    def test_expired_entitlement_blocks_publishing_an_ai_preview(self):
        allowed = Mock(return_value=True)
        app = self.app(self.resolver, allowed)
        a, b, c, d = self.patches()
        with a, b, c, d:
            plan = app.state.run_action("preview", "sync", {})
            allowed.return_value = False
            with patch("workoutbridge.web.GarminProvider.connect") as provider:
                with self.assertRaises(HTTPException) as error:
                    app.state.run_action("publish", "sync", {"hash": plan["hash"], "selected": [0]})
                self.assertEqual(error.exception.status_code, 403)
                provider.assert_not_called()

    def test_resolver_failure_keeps_the_original_unresolved_preview(self):
        def broken(plan):
            plan["items"].clear()
            raise RuntimeError("upstream failure")

        app = self.app(broken)
        a, b, c, d = self.patches()
        with a, b, c, d:
            plan = app.state.run_action("preview", "sync", {})
        self.assertEqual(len(plan["items"]), 1)
        self.assertIn("error", plan["items"][0])
