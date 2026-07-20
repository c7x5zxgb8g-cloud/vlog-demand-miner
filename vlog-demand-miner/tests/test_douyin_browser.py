from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
BROWSER = ROOT / "scripts" / "providers" / "douyin_browser.py"
CLI = ROOT / "scripts" / "vdm.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


browser = load("douyin_browser_for_test", BROWSER)
sys.path.insert(0, str(CLI.parent))
vdm = load("vdm_browser_for_test", CLI)


class DouyinBrowserProviderTests(unittest.TestCase):
    def test_visible_video_id_parser_rejects_non_video_links(self) -> None:
        self.assertEqual(browser.visible_post_id("/video/123456789"), "123456789")
        self.assertEqual(browser.visible_post_id("/user/example"), "")

    def test_browser_comment_budget_allows_upstream_stagnation_detection(self) -> None:
        self.assertEqual(browser.browser_comment_scrolls(1), 6)
        self.assertEqual(browser.browser_comment_scrolls(100), 20)

    def test_default_adapter_points_to_bundled_content_engine(self) -> None:
        self.assertEqual(browser.DEFAULT_UPSTREAM_ADAPTER.name, "douyin-session")
        self.assertIn("vendor/content-engine", browser.DEFAULT_UPSTREAM_ADAPTER.as_posix())

    def test_browser_mode_refuses_media_and_reply_collection(self) -> None:
        provider = browser.BrowserProvider(Path("/tmp/vdm-browser-test"))
        media = asyncio.run(provider.action({"op": "fetch_media", "aweme_id": "1"}))
        replies = asyncio.run(provider.action({"op": "fetch_replies", "aweme_id": "1", "comment_id": "2"}))
        self.assertEqual(media["status"], "unsupported")
        self.assertEqual(media["recovery"]["action"], "user_supplied_media_required")
        self.assertEqual(replies["status"], "unsupported")

    def test_commenter_identity_is_not_inflated_by_comment_id(self) -> None:
        provider = browser.BrowserProvider(Path("/tmp/vdm-browser-test"), commenter_secret=b"test-secret")
        comments = provider._comments_from_upstream([
            {"cid": "comment-1", "text": "first", "user_name": "same-user"},
            {"cid": "comment-2", "text": "second", "user_name": "same-user"},
            {"cid": "comment-3", "text": "anonymous"},
        ], "post-1")
        self.assertEqual(comments[0]["commenter_id"], comments[1]["commenter_id"])
        self.assertNotIn("commenter_id", comments[2])

    def test_browser_provider_does_not_import_cookie_or_request_replay_libraries(self) -> None:
        source = BROWSER.read_text(encoding="utf-8")
        self.assertNotIn("browser_cookie3", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("context.cookies", source)

    def test_upstream_debug_output_is_scoped_to_external_profile(self) -> None:
        provider = browser.BrowserProvider(Path("/tmp/vdm-browser-test"))
        provider.previous_upstream_root = None
        with patch.dict(browser.os.environ, {"NEXTTAKE_PROJECT_ROOT": str(provider.profile_dir)}, clear=False):
            provider._restore_upstream_root()
            self.assertNotIn("NEXTTAKE_PROJECT_ROOT", browser.os.environ)

    def test_auto_mode_switches_once_after_sidecar_failure(self) -> None:
        args = SimpleNamespace(
            douyin_provider="auto",
            douyin_browser_python=sys.executable,
            douyin_browser_profile_dir="/tmp/vdm-browser-profile",
            sidecar_url="http://127.0.0.1:9",
            commenter_hmac_key_env=None,
            request_delay_min_seconds=0,
            request_delay_max_seconds=0,
        )
        sidecar = {"status": "partial", "data": {"operations": [{"op": "list_posts", "status": "sidecar_unavailable"}]}}
        fallback = {"status": "ok", "data": {"operations": [{"op": "list_posts", "status": "ok", "posts": []}]}}
        with tempfile.TemporaryDirectory() as directory, patch.object(vdm, "invoke_provider", side_effect=[sidecar, fallback]) as invoke:
            project = Path(directory)
            vdm.connect(project).close()
            result = vdm.run_provider(project, "douyin", args, [{"op": "list_posts", "sec_user_id": "x"}])
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(result["provider_selection"]["selected"], "browser")
        self.assertEqual(result["provider_selection"]["fallback_from"], "sidecar")

    def test_profile_inside_research_project_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            args = SimpleNamespace(douyin_browser_profile_dir=str(project / ".vlog-demand-miner" / "profile"))
            with self.assertRaisesRegex(ValueError, "outside_research_project"):
                vdm.browser_profile(project, args)

    def test_missing_playwright_returns_structured_health_status(self) -> None:
        if browser.PLAYWRIGHT_AVAILABLE:
            self.skipTest("local runtime is installed")
        result = asyncio.run(browser.main(SimpleNamespace(command="healthcheck", profile_dir=Path("/tmp/vdm-browser-test"))))
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
