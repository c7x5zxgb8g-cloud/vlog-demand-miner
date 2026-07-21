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

    def test_blocked_page_classifier_distinguishes_login_verification_and_risk(self) -> None:
        self.assertEqual(browser.classify_blocked_page("https://sso.douyin.com/login", ""), "blocked_auth")
        self.assertEqual(browser.classify_blocked_page("https://www.douyin.com/verify", "安全验证"), "blocked_verification")
        self.assertEqual(browser.classify_blocked_page("https://www.douyin.com/video/1", "访问过于频繁，请稍后再试"), "risk_control")
        self.assertIsNone(browser.classify_blocked_page("https://www.douyin.com/video/1", "登录后可以发表评论"))

    def test_browser_plan_coalesces_post_and_comments_for_the_same_video(self) -> None:
        class FakeProvider:
            def __init__(self) -> None:
                self.calls = []

            async def action(self, operation):
                self.calls.append(("action", operation["op"]))
                return {"op": operation["op"], "status": "ok"}

            async def fetch_post_and_comments(self, post_operation, comment_operation):
                self.calls.append(("combined", post_operation["aweme_id"], comment_operation["aweme_id"]))
                return [
                    {"op": "fetch_post", "status": "ok"},
                    {"op": "fetch_comments", "status": "ok", "comments": []},
                ]

        provider = FakeProvider()
        results = asyncio.run(browser.execute_operations(
            provider,
            [{"op": "fetch_post", "aweme_id": "1"}, {"op": "fetch_comments", "aweme_id": "1"}],
            (0, 0),
        ))
        self.assertEqual(provider.calls, [("combined", "1", "1")])
        self.assertEqual([item["op"] for item in results], ["fetch_post", "fetch_comments"])

    def test_browser_plan_stops_after_platform_block(self) -> None:
        class FakeProvider:
            def __init__(self) -> None:
                self.calls = []

            async def action(self, operation):
                self.calls.append(operation["op"])
                return {"op": operation["op"], "status": "risk_control"}

        provider = FakeProvider()
        results = asyncio.run(browser.execute_operations(
            provider,
            [{"op": "list_posts"}, {"op": "fetch_post"}],
            (0, 0),
        ))
        self.assertEqual(provider.calls, ["list_posts"])
        self.assertEqual(results[0]["status"], "risk_control")

    def test_combined_video_navigation_stops_at_visible_risk_checkpoint(self) -> None:
        class Checkpoint(RuntimeError):
            def __init__(self, status):
                self.status = status

        class Locator:
            async def inner_text(self, timeout=None):
                return "访问过于频繁，请稍后再试"

        class Page:
            def __init__(self):
                self.url = ""
                self.goto_count = 0
                self.closed = False

            async def goto(self, url, **_kwargs):
                self.url = url
                self.goto_count += 1

            def locator(self, _selector):
                return Locator()

            async def close(self):
                self.closed = True

        class Context:
            def __init__(self, page):
                self.page = page

            async def new_page(self):
                return self.page

        class Crawler:
            PageCheckpoint = Checkpoint

            @staticmethod
            async def fetch_comments(_session, aweme_id, *, page, navigate, page_guard, **_kwargs):
                if navigate:
                    await page.goto(f"https://www.douyin.com/video/{aweme_id}")
                status = await page_guard(page)
                if status:
                    raise Checkpoint(status)
                return []

        page = Page()
        provider = browser.BrowserProvider(Path("/tmp/vdm-browser-test"))
        provider.context = Context(page)
        provider.crawler = Crawler()
        provider.upstream_session = object()
        provider.supports_page_reuse = True
        results = asyncio.run(provider.fetch_post_and_comments(
            {"op": "fetch_post", "aweme_id": "1"},
            {"op": "fetch_comments", "aweme_id": "1", "max_pages": 1},
        ))
        self.assertEqual([item["status"] for item in results], ["risk_control", "risk_control"])
        self.assertEqual(page.goto_count, 1)
        self.assertTrue(page.closed)

    def test_visible_account_id_only_uses_profile_path(self) -> None:
        self.assertEqual(browser.visible_account_id("https://www.douyin.com/user/MS4-test?from=search"), "MS4-test")
        self.assertEqual(browser.visible_account_id("https://www.douyin.com/video/123"), "")

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
        fallback = {"status": "ok", "data": {"operations": [
            {"op": "list_posts", "status": "ok", "posts": []},
            {"op": "fetch_post", "status": "ok"},
        ]}}
        plans = []

        def fake_invoke(_command, plan):
            plans.append(json.loads(plan.read_text(encoding="utf-8")))
            return sidecar if len(plans) == 1 else fallback

        with tempfile.TemporaryDirectory() as directory, patch.object(vdm, "invoke_provider", side_effect=fake_invoke) as invoke:
            project = Path(directory)
            vdm.connect(project).close()
            result = vdm.run_provider(project, "douyin", args, [
                {"op": "list_posts", "sec_user_id": "x"},
                {"op": "fetch_post", "aweme_id": "1"},
            ])
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(len(plans[0]["operations"]), 1)
        self.assertEqual(len(plans[1]["operations"]), 2)
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
