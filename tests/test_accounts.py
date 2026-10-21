import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from workoutbridge.accounts import Accounts


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1900000000.0
        self.store = Accounts(Path(self.tmp.name), clock=lambda: self.now)
        self.a = self.store.create_user("one@example.invalid")
        self.b = self.store.create_user("two@example.invalid")

    def test_free_and_expiring_gifts_and_audit(self):
        self.assertEqual(self.store.entitlements(self.a)["interval"], 10800)
        with self.assertRaises(PermissionError):
            self.store.gift(self.b, self.a, days=30, reason="test")
        self.store.set_admin(self.a, True)
        grant = self.store.gift(self.a, self.b, days=30, reason="Early tester")
        self.assertEqual(self.store.entitlements(self.b)["interval"], 900)
        self.now += 31 * 86400
        self.assertEqual(self.store.entitlements(self.b)["plan"], "free")
        self.store.gift(self.a, self.b, days=None, reason="Lifetime tester")
        self.now += 1000 * 86400
        self.assertEqual(self.store.entitlements(self.b)["plan"], "supporter")
        self.assertEqual(len(self.store.admin_users(self.a)["audit"]), 2)
        with self.assertRaises(PermissionError):
            self.store.revoke(self.b, grant)

    def test_referral_needs_verified_identity_and_real_activation_and_awards_once(self):
        code = self.store.invite(self.a)
        self.store.accept_invite(self.b, code)
        self.assertFalse(
            self.store.activate(self.b, source=True, destination=True, publication=True)
        )
        self.store.verify_email(self.b)
        self.store.add_credential(self.b, "synthetic-credential", b"public-key", 0)
        self.assertFalse(
            self.store.activate(self.b, source=True, destination=True, publication=False)
        )
        self.assertTrue(
            self.store.activate(self.b, source=True, destination=True, publication=True)
        )
        self.assertFalse(
            self.store.activate(self.b, source=True, destination=True, publication=True)
        )
        for user in (self.a, self.b):
            self.assertEqual(self.store.entitlements(user)["plan"], "supporter")
            self.assertEqual(self.store.entitlements(user)["until"], self.now + 30 * 86400)

    def test_self_invite_and_existing_referral_are_rejected(self):
        code = self.store.invite(self.a)
        with self.assertRaises(ValueError):
            self.store.accept_invite(self.a, code)
        self.store.accept_invite(self.b, code)
        with self.assertRaises(ValueError):
            self.store.accept_invite(self.b, code)

    def test_sessions_and_email_tokens_expire_are_hashed_and_one_use(self):
        token = self.store.email_token(self.a)
        self.store.consume_email_token(token)
        with self.assertRaises(ValueError):
            self.store.consume_email_token(token)
        session = self.store.new_session(self.a)
        self.assertEqual(self.store.session_user(session), self.a)
        self.assertNotIn(session.encode(), self.store.database.read_bytes())
        self.store.logout(session)
        self.assertIsNone(self.store.session_user(session))
        session = self.store.new_session(self.a)
        self.now += 31 * 86400
        self.assertIsNone(self.store.session_user(session))

    def test_parallel_rewards_do_not_duplicate_and_other_users_cannot_read_admin(self):
        self.store.accept_invite(self.b, self.store.invite(self.a))
        self.store.verify_email(self.b)
        self.store.add_credential(self.b, "credential", b"public", 0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda _: self.store.activate(
                        self.b, source=True, destination=True, publication=True
                    ),
                    range(4),
                )
            )
        self.assertEqual(sum(results), 1)
        with self.assertRaises(PermissionError):
            self.store.admin_users(self.b)

    def test_destination_ownership_is_global_and_free_provider_limit_is_explicit(self):
        self.store.claim_destination(self.a, "garmin", "123")
        with self.assertRaises(ValueError):
            self.store.claim_destination(self.b, "garmin", "123")
        with self.assertRaises(PermissionError):
            self.store.claim_destination(self.a, "coros", "coros:us:synthetic")
        self.store.set_admin(self.a, True)
        grant = self.store.gift(self.a, self.a, days=None, reason="Owner")
        self.store.claim_destination(self.a, "coros", "coros:us:synthetic")
        self.store.revoke(self.a, grant)
        self.assertFalse(self.store.provider_allowed(self.a, "coros"))
        self.assertTrue(self.store.provider_allowed(self.a, "garmin"))
        self.store.choose_provider(self.a, "coros")
        self.assertTrue(self.store.provider_allowed(self.a, "coros"))

    def test_challenges_are_bound_to_purpose_and_consumed_before_verification(self):
        key = self.store.challenge("register", {"user": self.a, "challenge": "synthetic"})
        with self.assertRaises(ValueError):
            self.store.take_challenge(key, "login")
        self.assertEqual(self.store.take_challenge(key, "register")["user"], self.a)
        with self.assertRaises(ValueError):
            self.store.take_challenge(key, "register")

    def test_diy_multiuser_has_no_commercial_gate_but_still_claims_destination_ownership(self):
        store = Accounts(Path(self.tmp.name) / "diy", plans=False)
        a, b = store.create_user("a@example.invalid"), store.create_user("b@example.invalid")
        store.claim_destination(a, "garmin", "123")
        store.claim_destination(a, "coros", "coros:us:synthetic")
        self.assertTrue(store.provider_allowed(a, "coros"))
        with self.assertRaises(ValueError):
            store.claim_destination(b, "garmin", "123")

    def test_enrollment_proof_can_be_read_for_retry_but_initial_credential_is_atomic(self):
        key = self.store.challenge("enrollment", {"user": self.b})
        self.assertEqual(self.store.read_challenge(key, "enrollment")["user"], self.b)
        self.assertEqual(self.store.read_challenge(key, "enrollment")["user"], self.b)
        self.store.add_credential(self.b, "first", b"public", 0, initial=True)
        with self.assertRaises(ValueError):
            self.store.add_credential(self.b, "second", b"public", 0, initial=True)

    def test_session_reads_do_not_renew_until_success_and_revocation_is_not_undone(self):
        token = self.store.new_session(self.a)
        self.now += 29 * 86400
        self.assertEqual(self.store.session_user(token), self.a)
        self.assertTrue(self.store.renew_session(token))
        self.now += 29 * 86400
        self.assertEqual(self.store.session_user(token), self.a)
        self.store.logout(token)
        self.assertFalse(self.store.renew_session(token))
