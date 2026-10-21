import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/do_deploy.py"


class DoDeployTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("do_deploy", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        (self.root / "deploy.json").write_text(
            json.dumps(
                {
                    "docker": "/home/service/bin/docker",
                    "socket": "unix:///run/user/1001/docker.sock",
                    "compose": "/opt/workoutbridge/compose.do.yaml",
                    "env_file": str(self.root / "runtime.env"),
                }
            )
        )
        (self.root / "runtime.env").write_text("WORKOUTBRIDGE_ORIGIN=http://localhost:1879\n")
        (self.root / "runtime.env").chmod(0o600)
        self.payload = {
            "revision": "a" * 40,
            "digest": "sha256:" + "b" * 64,
            "registry_user": "synthetic",
            "registry_token": "synthetic-secret-token",
        }
        self.calls = []
        self.fail = None
        self.label_revision = self.payload["revision"]

    def fake_run(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.fail and self.fail in args:
            return CompletedProcess(args, 1, stdout="", stderr="synthetic-secret-token")
        if "inspect" in args:
            output = json.dumps(
                {
                    "org.opencontainers.image.revision": self.label_revision,
                    "org.opencontainers.image.source": "https://github.com/ayn/workoutbridge",
                }
            )
        else:
            output = ""
        return CompletedProcess(args, 0, stdout=output, stderr="")

    def test_pull_and_verify_digest_before_up_then_record_healthy_revision(self):
        self.module.deploy(self.root, self.payload, run=self.fake_run)
        commands = [args for args, _ in self.calls]
        self.assertTrue(any("login" in args for args in commands))
        pull = next(i for i, args in enumerate(commands) if "pull" in args)
        inspect = next(i for i, args in enumerate(commands) if "inspect" in args)
        up = next(i for i, args in enumerate(commands) if "up" in args)
        self.assertLess(pull, inspect)
        self.assertLess(inspect, up)
        self.assertIn("ghcr.io/ayn/workoutbridge@" + self.payload["digest"], commands[pull])
        self.assertIn("--wait", commands[up])
        self.assertIn("--no-build", commands[up])
        self.assertEqual(json.loads((self.root / "current.json").read_text())["revision"], "a" * 40)
        self.assertEqual((self.root / "current.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.payload["registry_token"], json.dumps(commands))
        auth_dir = Path(commands[0][commands[0].index("--config") + 1])
        self.assertFalse(auth_dir.exists())

    def test_invalid_revision_digest_and_registry_user_do_not_run_commands(self):
        for field, value in [
            ("revision", "main"),
            ("digest", "latest"),
            ("digest", "sha256:" + "x" * 64),
            ("registry_user", "--password"),
        ]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.module.deploy(self.root, {**self.payload, field: value}, run=self.fake_run)
        self.assertEqual(self.calls, [])

    def test_wrong_revision_or_failed_pull_never_replaces_running_container(self):
        for failure in ("pull", "label"):
            with self.subTest(failure=failure):
                self.calls.clear()
                self.fail = "pull" if failure == "pull" else None
                self.label_revision = "c" * 40
                with self.assertRaises(ValueError) as raised:
                    self.module.deploy(self.root, self.payload, run=self.fake_run)
                self.assertNotIn(self.payload["registry_token"], str(raised.exception))
                self.assertFalse(any("up" in args for args, _ in self.calls))
                self.assertFalse((self.root / "current.json").exists())

    def test_failed_health_check_preserves_previous_receipt_and_cleans_credentials(self):
        previous = {"revision": "c" * 40, "digest": "sha256:" + "d" * 64}
        (self.root / "current.json").write_text(json.dumps(previous))
        self.fail = "up"
        with self.assertRaises(ValueError):
            self.module.deploy(self.root, self.payload, run=self.fake_run)
        self.assertEqual(json.loads((self.root / "current.json").read_text()), previous)
        self.assertFalse(list(self.root.glob("registry-*")))

    def test_compose_never_publishes_a_public_port_or_builds_on_server(self):
        compose = (SCRIPT.parent / "compose.do.yaml").read_text()
        self.assertIn("127.0.0.1:1879:8000", compose)
        self.assertNotIn("build:", compose)
        for setting in (
            "read_only: true",
            "unless-stopped",
            "max-size:",
            "mem_limit:",
            "cap_drop: [ALL]",
            "no-new-privileges:true",
        ):
            self.assertIn(setting, compose)

    def test_local_multiuser_override_is_applied_without_building_on_server(self):
        path = self.root / "deploy.json"
        config = json.loads(path.read_text())
        config["overrides"] = ["/opt/workoutbridge/compose.multiuser.yaml"]
        path.write_text(json.dumps(config))
        self.module.deploy(self.root, self.payload, run=self.fake_run)
        command = next(args for args, _ in self.calls if "up" in args)
        self.assertEqual(command.count("-f"), 2)
        self.assertIn(config["overrides"][0], command)

    def test_ci_builds_on_hosted_runner_and_deploys_only_tested_main(self):
        workflow = (SCRIPT.parent.parent / ".github/workflows/deploy-do.yml").read_text()
        for guard in (
            "workflow_run:",
            "branches: [main]",
            "== 'success'",
            "== 'push'",
            "== github.repository",
            "DO_DEPLOY_ENABLED == 'true'",
            "runs-on: ubuntu-latest",
            "platforms: linux/amd64",
            "packages: write",
            "packages: read",
            "workoutbridge-deploy",
            "environment: private-do",
            "head_sha",
        ):
            self.assertIn(guard, workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("StrictHostKeyChecking=no", workflow)


class DoPushTests(unittest.TestCase):
    def test_ssh_checks_host_key_and_sends_credentials_only_on_stdin(self):
        spec = importlib.util.spec_from_file_location("do_push", SCRIPT.parent / "do_push.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return CompletedProcess(args, 0, stdout="a" * 40 + "\trefs/heads/main\n", stderr="")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {
                    "REVISION": "a" * 40,
                    "IMAGE_DIGEST": "sha256:" + "b" * 64,
                    "REGISTRY_USER": "synthetic",
                    "REGISTRY_TOKEN": "private-synthetic",
                },
            ),
        ):
            config = Path(directory) / "target.json"
            config.write_text(
                json.dumps(
                    {
                        "host": "example.invalid",
                        "user": "service",
                        "key": "/private/key",
                        "known_hosts": "/private/hosts",
                    }
                )
            )
            config.chmod(0o600)
            module.push(config, run=fake_run)
        args, kwargs = calls[-1]
        self.assertEqual(args[0], "ssh")
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("IdentitiesOnly=yes", args)
        self.assertNotIn("private-synthetic", " ".join(args))
        self.assertEqual(json.loads(kwargs["input"])["registry_token"], "private-synthetic")

    def test_superseded_revision_does_not_connect_to_server(self):
        spec = importlib.util.spec_from_file_location("do_push", SCRIPT.parent / "do_push.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return CompletedProcess(args, 0, stdout="c" * 40 + "\trefs/heads/main\n", stderr="")

        with patch.dict(os.environ, {"REVISION": "a" * 40}):
            module.push(Path("/unused"), run=fake_run)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "git")
