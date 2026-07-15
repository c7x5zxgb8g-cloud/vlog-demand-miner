#!/usr/bin/env python3
"""Visible-page Douyin browser fallback.

This provider deliberately uses one Playwright persistent context and ordinary
page navigation only.  It never reads browser cookies or storage, replays
platform requests, bypasses verification, or downloads media.  Results are
limited to records rendered in the browser and are marked as partial.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import hmac
import importlib.util
import json
import io
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PlaywrightError = RuntimeError
    PlaywrightTimeoutError = RuntimeError
    async_playwright = None
    PLAYWRIGHT_AVAILABLE = False


SCHEMA_VERSION = "1.0.0"
VIDEO_ID = re.compile(r"/video/(\d+)")
DEFAULT_UPSTREAM_ADAPTER = Path.home() / ".cc-switch" / "skills" / "cheat-on-content" / "adapters" / "perf-data" / "douyin-session"


class UpstreamAdapterUnavailable(RuntimeError):
    pass


def upstream_adapter_dir(value: str | Path | None) -> Path:
    selected = Path(value or os.getenv("VDM_CHEAT_DOUYIN_ADAPTER_DIR") or DEFAULT_UPSTREAM_ADAPTER).expanduser().resolve()
    if not (selected / "crawler.py").is_file():
        raise UpstreamAdapterUnavailable("cheat_douyin_session_adapter_unavailable")
    return selected


def load_upstream_crawler(adapter_dir: Path) -> Any:
    module_name = "vdm_cheat_douyin_session"
    if module_name in sys.modules:
        return sys.modules[module_name]
    previous_paths = sys.modules.pop("paths", None)
    sys.path.insert(0, str(adapter_dir))
    try:
        spec = importlib.util.spec_from_file_location(module_name, adapter_dir / "crawler.py")
        if not spec or not spec.loader:
            raise UpstreamAdapterUnavailable("cheat_douyin_session_adapter_unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except (ImportError, OSError) as exc:
        sys.modules.pop(module_name, None)
        raise UpstreamAdapterUnavailable("cheat_douyin_session_adapter_unavailable") from exc
    finally:
        sys.path.pop(0)
        sys.modules.pop("paths", None)
        if previous_paths is not None:
            sys.modules["paths"] = previous_paths


def emit(status: str, data: Any = None, warnings: list[str] | None = None, error: Any = None) -> None:
    print(json.dumps({"schema_version": SCHEMA_VERSION, "status": status, "data": data,
                      "warnings": warnings or [], "error": error}, ensure_ascii=False))


def clean_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def positive_int(value: Any, default: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def browser_comment_scrolls(value: Any) -> int:
    # The upstream adapter stops after six stagnant scrolls. A Sidecar page
    # count of one is therefore not a meaningful browser acquisition budget.
    return min(max(positive_int(value, 1), 6), 20)


def visible_post_id(href: str | None) -> str:
    match = VIDEO_ID.search(href or "")
    return match.group(1) if match else ""


@dataclass
class BrowserProvider:
    profile_dir: Path
    headless: bool = False
    upstream_adapter_dir: Path | None = None
    commenter_secret: bytes | None = None

    async def __aenter__(self) -> "BrowserProvider":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.chmod(0o700)
        self.previous_upstream_root = os.environ.get("CHEAT_PROJECT_ROOT")
        os.environ["CHEAT_PROJECT_ROOT"] = str(self.profile_dir)
        try:
            self.adapter_dir = upstream_adapter_dir(self.upstream_adapter_dir)
            self.crawler = load_upstream_crawler(self.adapter_dir)
            self.playwright = await async_playwright().start()
            # This is the exact persistent profile location expected by the
            # upstream cheat-on-content douyin-session adapter.
            options = {"user_data_dir": str(self.profile_dir / ".auth"), "headless": self.headless,
                       "viewport": {"width": 1440, "height": 960}}
            try:
                self.context = await self.playwright.chromium.launch_persistent_context(**options)
            except PlaywrightError:
                # A locally installed Chrome is a legitimate browser runtime too.
                self.context = await self.playwright.chromium.launch_persistent_context(**options, channel="chrome")
        except Exception:
            if hasattr(self, "playwright"):
                with contextlib.suppress(Exception):
                    await self.playwright.stop()
            self._restore_upstream_root()
            raise
        self.overlay_tasks: set[asyncio.Task[Any]] = set()
        self.context.on("page", self._schedule_overlay_dismissal)
        self.upstream_session = self.crawler.Session(self.context, self.playwright)
        return self

    async def __aexit__(self, *_: Any) -> None:
        try:
            if self.overlay_tasks:
                await asyncio.gather(*self.overlay_tasks, return_exceptions=True)
            await self.context.close()
            await self.playwright.stop()
        finally:
            self._restore_upstream_root()

    def _restore_upstream_root(self) -> None:
        if self.previous_upstream_root is None:
            os.environ.pop("CHEAT_PROJECT_ROOT", None)
        else:
            os.environ["CHEAT_PROJECT_ROOT"] = self.previous_upstream_root

    def _schedule_overlay_dismissal(self, page: Any) -> None:
        task = asyncio.create_task(self._dismiss_known_overlays(page))
        self.overlay_tasks.add(task)
        task.add_done_callback(self.overlay_tasks.discard)

    async def _dismiss_known_overlays(self, page: Any) -> None:
        # Douyin may show a first-use navigation guide over the video. This is
        # an ordinary visible UI action; no storage or request is modified.
        try:
            button = page.get_by_text("我知道了", exact=True)
            await button.wait_for(state="visible", timeout=10_000)
            await button.click(timeout=3_000)
        except PlaywrightError:
            return

    async def _navigate(self, page: Any, url: str, warnings: list[str]) -> None:
        try:
            await page.goto(url, wait_until="commit", timeout=25_000)
        except PlaywrightTimeoutError:
            warnings.append("navigation_timeout_after_browser_commit")
        except PlaywrightError as exc:
            warnings.append(f"navigation_error:{type(exc).__name__}")
        await page.wait_for_timeout(3_000)

    async def _scroll(self, page: Any, count: int, warnings: list[str]) -> None:
        for _ in range(min(max(count, 0), 8)):
            try:
                await page.evaluate("window.scrollBy(0, Math.max(800, window.innerHeight))")
                await page.wait_for_timeout(1_200)
            except PlaywrightError as exc:
                warnings.append(f"scroll_error:{type(exc).__name__}")
                return

    async def _body_text(self, page: Any) -> str:
        try:
            return await page.locator("body").inner_text(timeout=8_000)
        except PlaywrightError:
            return ""

    async def _posts_from_page(self, page: Any) -> list[dict[str, Any]]:
        links = page.locator('a[href*="/video/"]')
        posts: dict[str, dict[str, Any]] = {}
        try:
            for index in range(min(await links.count(), 80)):
                link = links.nth(index)
                post_id = visible_post_id(await link.get_attribute("href"))
                if not post_id:
                    continue
                title = (await link.get_attribute("aria-label") or await link.inner_text()).strip()[:500]
                posts.setdefault(post_id, {"post_id": post_id, "title": title, "content_type": "video",
                                            "published_at": None, "public_metrics": {}})
        except PlaywrightError:
            pass
        return list(posts.values())

    def _comments_from_upstream(self, rows: list[dict[str, Any]], aweme_id: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in rows:
            comment_id = str(raw.get("cid") or "")
            text = str(raw.get("text") or "").strip()
            if not comment_id or not text or comment_id in seen:
                continue
            seen.add(comment_id)
            normalized = {"comment_id": comment_id, "post_id": aweme_id, "text": text[:2_000],
                          "like_count": positive_int(raw.get("digg_count")),
                          "reply_count": positive_int(raw.get("reply_comment_total")),
                          "created_at": raw.get("create_time")}
            # cheat-on-content deliberately exposes no raw account identifier
            # in this public-page path. Use the display name only when present
            # and disclose the collision risk instead of treating each comment
            # as a different person.
            display_name = str(raw.get("user_name") or "").strip()
            if self.commenter_secret and display_name:
                normalized["commenter_id"] = hmac.new(self.commenter_secret, f"douyin-browser-name:{display_name}".encode(), hashlib.sha256).hexdigest()
            comments.append(normalized)
        return comments

    def _coverage(self, *, records: int, scrolls: int, warnings: list[str], kind: str) -> dict[str, Any]:
        return {"acquisition_mode": "browser_passive_xhr" if kind == "fetch_comments" else "browser_visible", "records_fetched": records, "scrolls": min(max(scrolls, 0), 20),
                "sampling": "browser_passive_xhr", "complete": False,
                "stopped_reason": "partial_with_warnings" if warnings else "configured_scroll_limit",
                "bias_warnings": ["browser_response_capture", "not_random", "not_complete", "configured_page_limit" if kind == "fetch_comments" else "visible_order_bias"]}

    async def action(self, operation: dict[str, Any]) -> dict[str, Any]:
        kind = str(operation.get("op") or "")
        if kind == "fetch_media":
            return {"op": kind, "status": "unsupported", "recovery": {"action": "user_supplied_media_required"},
                    "warnings": ["browser_provider_does_not_download_media"]}
        if kind == "fetch_replies":
            return {"op": kind, "status": "unsupported", "warnings": ["browser_visible_reply_collection_not_supported"]}
        if kind not in {"list_posts", "fetch_post", "fetch_comments"}:
            return {"op": kind, "status": "unsupported", "warnings": ["unsupported_operation"]}
        page = await self.context.new_page()
        warnings: list[str] = ["browser_visible_partial_coverage"]
        try:
            if kind == "list_posts":
                sec_user_id = str(operation.get("sec_user_id") or "")
                if not sec_user_id:
                    return {"op": kind, "status": "invalid_input", "warnings": ["sec_user_id_required"]}
                await self._navigate(page, f"https://www.douyin.com/user/{sec_user_id}", warnings)
                await self._scroll(page, positive_int(operation.get("max_pages"), 1), warnings)
                posts = await self._posts_from_page(page)
                if not posts:
                    warnings.append("no_visible_posts_detected")
                    return {"op": kind, "status": "partial", "posts": [], "coverage": self._coverage(records=0, scrolls=positive_int(operation.get("max_pages"), 1), warnings=warnings, kind=kind), "warnings": warnings}
                return {"op": kind, "status": "ok", "posts": posts, "coverage": self._coverage(records=len(posts), scrolls=positive_int(operation.get("max_pages"), 1), warnings=warnings, kind=kind), "warnings": warnings}
            aweme_id = str(operation.get("aweme_id") or "")
            if not aweme_id:
                return {"op": kind, "status": "invalid_input", "warnings": ["aweme_id_required"]}
            await self._navigate(page, f"https://www.douyin.com/video/{aweme_id}", warnings)
            if kind == "fetch_post":
                title = ""
                try:
                    title = (await page.locator("h1").first.inner_text(timeout=2_000)).strip()[:500]
                except PlaywrightError:
                    pass
                return {"op": kind, "status": "ok", "post": {"post_id": aweme_id, "title": title, "content_type": "video", "published_at": None, "public_metrics": {}},
                        "subtitles": {"available": False, "items": []}, "coverage": self._coverage(records=1, scrolls=0, warnings=warnings, kind=kind), "warnings": warnings + ["subtitle_unavailable_browser_provider"]}
            # The upstream adapter prints progress messages. Provider stdout is
            # reserved for our single JSON response, so keep those diagnostics
            # out of the control-plane protocol.
            with contextlib.redirect_stdout(io.StringIO()):
                raw_comments = await self.crawler.fetch_comments(self.upstream_session, aweme_id, max_pages=browser_comment_scrolls(operation.get("max_pages")))
            comments = self._comments_from_upstream(raw_comments, aweme_id)
            if self.commenter_secret:
                warnings.append("commenter_identity_display_name_based")
            else:
                warnings.append("commenter_identity_unavailable")
            if not comments:
                warnings.append("no_browser_captured_comments_detected")
            return {"op": kind, "status": "ok", "comments": comments,
                    "coverage": self._coverage(records=len(comments), scrolls=browser_comment_scrolls(operation.get("max_pages")), warnings=warnings, kind=kind),
                    "warnings": warnings}
        except PlaywrightError as exc:
            return {"op": kind, "status": "blocked_browser_page", "warnings": warnings, "error": {"type": type(exc).__name__}}
        finally:
            await page.close()


async def healthcheck(profile_dir: Path, adapter_dir: Path | None) -> dict[str, Any]:
    upstream_adapter_dir(adapter_dir)
    load_upstream_crawler(upstream_adapter_dir(adapter_dir))
    playwright = await async_playwright().start()
    try:
        executable = Path(playwright.chromium.executable_path)
        if not executable.is_file():
            raise PlaywrightError("playwright_browser_runtime_missing")
        return {"runtime": "playwright-persistent-browser",
                "capabilities": ["list_posts_visible", "fetch_post_visible", "fetch_comments_visible", "manual_login"]}
    finally:
        await playwright.stop()


async def main(args: argparse.Namespace) -> int:
    if not PLAYWRIGHT_AVAILABLE:
        emit("blocked_browser_unavailable", warnings=["playwright_runtime_not_installed"])
        return 2
    if args.command == "healthcheck":
        try:
            emit("ok", await healthcheck(args.profile_dir, args.upstream_adapter_dir))
            return 0
        except UpstreamAdapterUnavailable:
            emit("blocked_browser_unavailable", warnings=["cheat_douyin_session_adapter_unavailable"])
            return 2
        except PlaywrightError:
            emit("blocked_browser_unavailable")
            return 2
    try:
        if args.command == "login":
            adapter_dir = upstream_adapter_dir(args.upstream_adapter_dir)
            crawler = load_upstream_crawler(adapter_dir)
            previous_root = os.environ.get("CHEAT_PROJECT_ROOT")
            profile_dir = args.profile_dir.expanduser().resolve()
            profile_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.chmod(0o700)
            os.environ["CHEAT_PROJECT_ROOT"] = str(profile_dir)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    logged_in = await crawler.ensure_login(max(1, min(args.wait_seconds, 900)))
            finally:
                if previous_root is None:
                    os.environ.pop("CHEAT_PROJECT_ROOT", None)
                else:
                    os.environ["CHEAT_PROJECT_ROOT"] = previous_root
            emit("ok" if logged_in else "blocked_auth", {"action": "manual_login_completed" if logged_in else "manual_login_incomplete"})
            return 0 if logged_in else 2
        async with BrowserProvider(args.profile_dir, args.headless, args.upstream_adapter_dir, (os.environ.get(args.commenter_hmac_key_env, "").encode() if args.commenter_hmac_key_env else None) or None) as provider:
            plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
            operations = plan.get("operations") if isinstance(plan, dict) else None
            if not isinstance(operations, list):
                emit("invalid_plan")
                return 2
            results = [await provider.action(item) for item in operations if isinstance(item, dict)]
            overall = "ok" if results and all(item.get("status") in {"ok", "unsupported"} for item in results) else "partial"
            emit(overall, {"operations": results, "provider_mode": "browser"})
            return 0 if overall == "ok" else 2
    except UpstreamAdapterUnavailable:
        emit("blocked_browser_unavailable", warnings=["cheat_douyin_session_adapter_unavailable"])
        return 2
    except PlaywrightError as exc:
        emit("blocked_browser_unavailable", error={"type": type(exc).__name__})
        return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--upstream-adapter-dir", type=Path, default=os.getenv("VDM_CHEAT_DOUYIN_ADAPTER_DIR", str(DEFAULT_UPSTREAM_ADAPTER)))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--commenter-hmac-key-env")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("healthcheck")
    login = commands.add_parser("login")
    login.add_argument("--wait-seconds", type=int, default=300)
    run = commands.add_parser("run")
    run.add_argument("--plan", required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
