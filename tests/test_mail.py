import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from workoutbridge.mail import CloudflareMail


class MailTests(unittest.TestCase):
    def test_sender_reply_to_and_token_file_not_args_and_errors_are_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text("synthetic-secret")
            path.chmod(0o600)
            mail = CloudflareMail("a" * 32, path, "https://bridge.example")
            with patch(
                "workoutbridge.mail.urlopen",
                return_value=BytesIO(
                    json.dumps(
                        {"success": True, "result": {"queued": ["member@example.invalid"]}}
                    ).encode()
                ),
            ) as send:
                mail("member@example.invalid", "https://bridge.example/#verify=synthetic")
            request = send.call_args.args[0]
            payload = json.loads(request.data)
            self.assertEqual(payload["from"], "Prescribed <notifications@bridge.example>")
            self.assertEqual(payload["reply_to"], "support@bridge.example")
            self.assertNotIn("synthetic-secret", str(payload))
            with patch("workoutbridge.mail.urlopen", side_effect=ValueError("synthetic-secret")):
                with self.assertRaises(ValueError) as error:
                    mail("member@example.invalid", "https://bridge.example/#verify=synthetic")
                self.assertNotIn("synthetic-secret", str(error.exception))
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                mail("member@example.invalid", "https://bridge.example/#verify=synthetic")
