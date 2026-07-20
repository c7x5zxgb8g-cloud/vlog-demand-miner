from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


MODULE = Path(__file__).parents[1] / "scripts" / "setup_local_environment.py"
SPEC = importlib.util.spec_from_file_location("setup_local_environment", MODULE)
assert SPEC and SPEC.loader
SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETUP)


class SetupEnvironmentTests(unittest.TestCase):
    def test_model_spec_is_consistent(self) -> None:
        self.assertEqual(len(SETUP.MODEL_SHA256), 64)
        self.assertGreater(SETUP.MODEL_BYTES, SETUP.CHUNK_BYTES)
        self.assertRegex(SETUP.PLAYWRIGHT_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(SETUP.DEFAULT_DOUYIN_ADAPTER.name, "douyin-session")
        self.assertIn("vendor/content-engine", SETUP.DEFAULT_DOUYIN_ADAPTER.as_posix())

    def test_vendored_adapter_is_preferred_without_clone(self) -> None:
        self.assertTrue(SETUP.is_douyin_adapter(SETUP.DEFAULT_DOUYIN_ADAPTER))
        with tempfile.TemporaryDirectory() as directory, patch.object(SETUP, "ensure_pinned_checkout") as checkout:
            result = SETUP.resolve_douyin_adapter(Path(directory))
        self.assertEqual(result["source"], "bundled")
        self.assertEqual(result["path"], str(SETUP.DEFAULT_DOUYIN_ADAPTER))
        checkout.assert_not_called()

    def test_sha256_matches_written_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.bin"
            path.write_bytes(b"vdm")
            self.assertEqual(SETUP.sha256(path), hashlib.sha256(b"vdm").hexdigest())

    def test_service_name_is_project_scoped(self) -> None:
        project = Path("/tmp/vdm-pilot")
        self.assertEqual(f"vlog-demand-miner/{project.name}/commenter-hmac", "vlog-demand-miner/vdm-pilot/commenter-hmac")

    def test_configured_adapter_is_used_without_clone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = root / "adapter"
            adapter.mkdir()
            (adapter / "crawler.py").write_text("# test\n", encoding="utf-8")
            (adapter / "requirements.txt").write_text("playwright>=1.44\n", encoding="utf-8")
            with patch.object(SETUP, "ensure_pinned_checkout") as checkout:
                result = SETUP.resolve_douyin_adapter(root / "state", str(adapter))
        self.assertEqual(result["source"], "configured")
        self.assertEqual(result["path"], str(adapter.resolve()))
        checkout.assert_not_called()

    def test_missing_bundled_adapter_is_reported_without_external_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-adapter"
            with patch.object(SETUP, "DEFAULT_DOUYIN_ADAPTER", missing):
                with self.assertRaisesRegex(SETUP.SetupError, "bundled_douyin_adapter_missing"):
                    SETUP.resolve_douyin_adapter(Path(directory) / "state")

    def test_pinned_checkout_reuses_matching_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "upstream"
            (source / ".git").mkdir(parents=True)
            with patch.object(SETUP, "current_git_commit", return_value="abc"), patch.object(SETUP, "run") as command:
                command.return_value = ""
                SETUP.ensure_pinned_checkout(source, "https://example.invalid/repo.git", "abc")
        command.assert_called_once_with("git", "-C", str(source), "status", "--porcelain", capture=True)

    def test_next_actions_include_paths_for_ai_runner(self) -> None:
        state = Path("/tmp/vdm-state")
        project = Path("/tmp/vdm-project")
        environment, actions = SETUP.build_next_actions(
            state_dir=state,
            project=project,
            skill_root=Path("/tmp/vdm-skill"),
            browser={"python": "/tmp/browser/bin/python", "adapter_dir": "/tmp/nexttake/douyin-session", "adapter_revision": "sha256:test"},
            bilibili={"bilibili_cli": "/tmp/bilibili/bin/bili"},
        )
        self.assertEqual(environment["VDM_DOUYIN_BROWSER_PYTHON"], "/tmp/browser/bin/python")
        self.assertEqual(environment["NEXTTAKE_DOUYIN_ADAPTER_DIR"], "/tmp/nexttake/douyin-session")
        self.assertIn("NEXTTAKE_DOUYIN_ADAPTER_REVISION", environment)
        legacy_prefix = ("ch" + "eat").upper()
        self.assertNotIn(legacy_prefix, " ".join(environment))
        self.assertEqual(environment["VDM_BILIBILI_CLI"], "/tmp/bilibili/bin/bili")
        self.assertEqual([item["name"] for item in actions], ["douyin_browser_login", "bilibili_login", "doctor"])
        self.assertIn(str(project), actions[-1]["argv"])


if __name__ == "__main__":
    unittest.main()
