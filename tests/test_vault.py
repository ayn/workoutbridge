import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from workoutbridge.vault import SessionVault


class VaultTests(unittest.TestCase):
    def test_sessions_are_encrypted_at_rest_and_restore_only_inside_tenant_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = Fernet.generate_key()
            vault = SessionVault(root / "sealed", root / "runtime", key)
            session = vault.new_path("garmin")
            session.mkdir(parents=True)
            (session / "token.json").write_text("PRIVATE-SESSION-TOKEN")
            vault.save(session)
            self.assertNotIn(
                b"PRIVATE-SESSION-TOKEN", next((root / "sealed").glob("*.sealed")).read_bytes()
            )
            (session / "token.json").unlink()
            session.rmdir()
            vault.restore(session)
            self.assertEqual((session / "token.json").read_text(), "PRIVATE-SESSION-TOKEN")
            self.assertEqual((session / "token.json").stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                vault.restore(root / "other-user/session")
            (session / "symlink").symlink_to(root / "other-user")
            with self.assertRaises(ValueError):
                vault.save(session)

    def test_corruption_does_not_create_plaintext_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = SessionVault(root / "sealed", root / "runtime", Fernet.generate_key())
            (root / "sealed/synthetic.sealed").write_text("not-encrypted")
            with self.assertRaises(ValueError):
                vault.restore(root / "runtime/synthetic")
            self.assertFalse((root / "runtime/synthetic").exists())
