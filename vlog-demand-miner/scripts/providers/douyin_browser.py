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
import inspect
import json
import io
import math
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

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
ACCOUNT_ID = re.compile(r"/user/([^/?#]+)")
SKILL_ROOT = Path(__file__).resolve().parents[2]
CONTENT_ENGINE_ROOT = Path(
    os.getenv("NEXTTAKE_CONTENT_ENGINE_ROOT")
    or str(SKILL_ROOT / "vendor" / "content-engine")
).expanduser().resolve()
DEFAULT_UPSTREAM_ADAPTER = CONTENT_ENGINE_ROOT / "adapters" / "perf-data" / "douyin-session"
BROWSER_STOP_STATUSES = {
    "blocked_auth", "blocked_verification", "risk_control",
    "schema_drift", "anomalous_empty_result", "blocked_browser_page",
}
EXPECTED_EMPTY_COMMENT_MARKERS = ("暂无评论", "还没有评论", "暂时没有评论")


class UpstreamAdapterUnavailable(RuntimeError):
    pass


class UpstreamAdapterIncompatible(RuntimeError):
    pass


def upstream_adapter_dir(value: str | Path | None) -> Path:
    selected = Path(
        value
        or os.getenv("NEXTTAKE_DOUYIN_ADAPTER_DIR")
        or DEFAULT_UPSTREAM_ADAPTER
    ).expanduser().resolve()
    if not (selected / "crawler.py").is_file():
        raise UpstreamAdapterUnavailable("douyin_adapter_unavailable")
    return selected


def load_upstream_crawler(adapter_dir: Path) -> Any:
    module_name = "vdm_nexttake_douyin_session"
    if module_name in sys.modules:
        return sys.modules[module_name]
    previous_paths = sys.modules.pop("paths", None)
    sys.path.insert(0, str(adapter_dir))
    try:
        spec = importlib.util.spec_from_file_location(module_name, adapter_dir / "crawler.py")
        if not spec or not spec.loader:
            raise UpstreamAdapterUnavailable("douyin_adapter_unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except (ImportError, OSError) as exc:
        sys.modules.pop(module_name, None)
        raise UpstreamAdapterUnavailable("douyin_adapter_unavailable") from exc
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


def classify_blocked_page(url: str, body_text: str) -> str | None:
    """Classify a visible platform stop page without reading browser storage."""
    parsed = urlsplit(url or "")
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "").casefold()
    text = " ".join((body_text or "").split()).casefold()
    verification_markers = (
        "安全验证", "请完成下列验证", "完成验证", "滑块验证", "验证码",
    )
    risk_markers = (
        "访问过于频繁", "访问频繁", "请求过于频繁", "操作频繁",
        "异常访问", "网络环境存在风险", "存在风险", "系统繁忙", "稍后再试",
    )
    auth_markers = ("扫码登录", "请先登录", "登录后继续", "登录已失效", "重新登录")
    if any(value in host or value in path for value in ("captcha", "challenge", "verify")):
        return "blocked_verification"
    if any(marker.casefold() in text for marker in verification_markers):
        return "blocked_verification"
    if any(marker.casefold() in text for marker in risk_markers):
        return "risk_control"
    if host.startswith("sso.") or host.startswith("passport.") or path.startswith("/login"):
        return "blocked_auth"
    if any(marker.casefold() in text for marker in auth_markers):
        return "blocked_auth"
    return None


def operation_delay_bounds(plan: dict[str, Any]) -> tuple[float, float]:
    raw = plan.get("operation_delay_seconds")
    if not isinstance(raw, dict):
        return 0.0, 0.0
    try:
        minimum = float(raw.get("min", 0))
        maximum = float(raw.get("max", minimum))
    except (TypeError, ValueError):
        return 0.0, 0.0
    if not math.isfinite(minimum) or not math.isfinite(maximum) or minimum < 0 or maximum < minimum:
        return 0.0, 0.0
    return minimum, maximum


def can_combine_post_and_comments(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return (
        first.get("op") == "fetch_post"
        and second.get("op") == "fetch_comments"
        and bool(str(first.get("aweme_id") or ""))
        and str(first.get("aweme_id")) == str(second.get("aweme_id"))
    )


async def execute_operations(
    provider: Any,
    operations: list[dict[str, Any]],
    delay_bounds: tuple[float, float],
) -> list[dict[str, Any]]:
    """Execute a Browser plan in one context and stop at platform checkpoints."""
    results: list[dict[str, Any]] = []
    index = 0
    acquisition_index = 0
    while index < len(operations):
        if acquisition_index:
            await asyncio.sleep(random.uniform(*delay_bounds))
        operation = operations[index]
        if index + 1 < len(operations) and can_combine_post_and_comments(operation, operations[index + 1]):
            current = await provider.fetch_post_and_comments(operation, operations[index + 1])
            index += 2
        else:
            current = [await provider.action(operation)]
            index += 1
        results.extend(current)
        acquisition_index += 1
        if any(item.get("status") in BROWSER_STOP_STATUSES for item in current):
            break
    return results


def visible_post_id(href: str | None) -> str:
    match = VIDEO_ID.search(href or "")
    return match.group(1) if match else ""


def visible_account_id(href: str | None) -> str:
    match = ACCOUNT_ID.search(href or "")
    return match.group(1) if match else ""


def validate_douyin_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "douyin.com" or host.endswith(".douyin.com")):
        raise ValueError("douyin_account_url_required")
    if parsed.username or parsed.password:
        raise ValueError("douyin_account_url_required")
    return value.strip()


@dataclass
class BrowserProvider:
    profile_dir: Path
    headless: bool = False
    upstream_adapter_dir: Path | None = None
    commenter_secret: bytes | None = None

    async def __aenter__(self) -> "BrowserProvider":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.chmod(0o700)
        self.previous_upstream_root = os.environ.get("NEXTTAKE_PROJECT_ROOT")
        os.environ["NEXTTAKE_PROJECT_ROOT"] = str(self.profile_dir)
        try:
            self.adapter_dir = upstream_adapter_dir(self.upstream_adapter_dir)
            self.crawler = load_upstream_crawler(self.adapter_dir)
            comment_parameters = inspect.signature(self.crawler.fetch_comments).parameters
            self.supports_page_reuse = (
                all(name in comment_parameters for name in ("page", "page_guard"))
                and hasattr(self.crawler, "PageCheckpoint")
            )
            self.playwright = await async_playwright().start()
            # This is the exact persistent profile location expected by the
            # upstream NextTake Content Engine douyin-session adapter.
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
            os.environ.pop("NEXTTAKE_PROJECT_ROOT", None)
        else:
            os.environ["NEXTTAKE_PROJECT_ROOT"] = self.previous_upstream_root

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

    async def _navigate(self, page: Any, url: str, warnings: list[str]) -> str | None:
        try:
            await page.goto(url, wait_until="commit", timeout=25_000)
        except PlaywrightTimeoutError:
            warnings.append("navigation_timeout_after_browser_commit")
        except PlaywrightError as exc:
            warnings.append(f"navigation_error:{type(exc).__name__}")
        await page.wait_for_timeout(3_000)
        return await self._page_block_status(page)

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

    async def _page_block_status(self, page: Any) -> str | None:
        return classify_blocked_page(str(getattr(page, "url", "") or ""), await self._body_text(page))

    def _blocked_result(self, kind: str, status: str, warnings: list[str]) -> dict[str, Any]:
        return {
            "op": kind,
            "status": status,
            "warnings": warnings + ["browser_checkpoint_preserved", "manual_resume_required"],
            "recovery": {"action": "complete_platform_checkpoint_then_resume"},
        }

    async def _post_result(self, page: Any, aweme_id: str, warnings: list[str]) -> dict[str, Any]:
        title = ""
        try:
            title = (await page.locator("h1").first.inner_text(timeout=2_000)).strip()[:500]
        except PlaywrightError:
            pass
        return {
            "op": "fetch_post",
            "status": "ok",
            "post": {"post_id": aweme_id, "title": title, "content_type": "video", "published_at": None, "public_metrics": {}},
            "subtitles": {"available": False, "items": []},
            "coverage": self._coverage(records=1, scrolls=0, warnings=warnings, kind="fetch_post"),
            "warnings": warnings + ["subtitle_unavailable_browser_provider"],
        }

    async def _comments_result(
        self,
        page: Any,
        aweme_id: str,
        operation: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        if not self.supports_page_reuse:
            return {
                "op": "fetch_comments",
                "status": "schema_drift",
                "warnings": warnings + ["douyin_adapter_page_reuse_required"],
                "recovery": {"action": "install_compatible_douyin_adapter"},
            }
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                raw_comments = await self.crawler.fetch_comments(
                    self.upstream_session,
                    aweme_id,
                    max_pages=browser_comment_scrolls(operation.get("max_pages")),
                    page=page,
                    navigate=True,
                    page_guard=self._page_block_status,
                )
        except self.crawler.PageCheckpoint as checkpoint:
            return self._blocked_result("fetch_comments", checkpoint.status, warnings)
        blocked = await self._page_block_status(page)
        if blocked:
            return self._blocked_result("fetch_comments", blocked, warnings)
        comments = self._comments_from_upstream(raw_comments, aweme_id)
        if self.commenter_secret:
            warnings.append("commenter_identity_display_name_based")
        else:
            warnings.append("commenter_identity_unavailable")
        if not comments:
            body = await self._body_text(page)
            warnings.append("no_browser_captured_comments_detected")
            if not any(marker in body for marker in EXPECTED_EMPTY_COMMENT_MARKERS):
                return {
                    "op": "fetch_comments",
                    "status": "anomalous_empty_result",
                    "comments": [],
                    "coverage": self._coverage(records=0, scrolls=browser_comment_scrolls(operation.get("max_pages")), warnings=warnings, kind="fetch_comments"),
                    "warnings": warnings + ["browser_checkpoint_preserved", "manual_review_required"],
                    "recovery": {"action": "review_visible_page_then_resume"},
                }
        return {
            "op": "fetch_comments",
            "status": "ok",
            "comments": comments,
            "coverage": self._coverage(records=len(comments), scrolls=browser_comment_scrolls(operation.get("max_pages")), warnings=warnings, kind="fetch_comments"),
            "warnings": warnings,
        }

    async def fetch_post_and_comments(
        self,
        post_operation: dict[str, Any],
        comment_operation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        aweme_id = str(post_operation.get("aweme_id") or "")
        if not aweme_id:
            invalid = {"status": "invalid_input", "warnings": ["aweme_id_required"]}
            return [{"op": "fetch_post", **invalid}, {"op": "fetch_comments", **invalid}]
        page = await self.context.new_page()
        warnings: list[str] = ["browser_visible_partial_coverage", "single_navigation_reused"]
        try:
            comments = await self._comments_result(page, aweme_id, comment_operation, list(warnings))
            if comments.get("status") == "schema_drift":
                return [
                    {
                        "op": "fetch_post",
                        "status": "schema_drift",
                        "warnings": list(comments.get("warnings") or []),
                        "recovery": comments.get("recovery"),
                    },
                    comments,
                ]
            if comments.get("status") in {"blocked_auth", "blocked_verification", "risk_control", "blocked_browser_page"}:
                return [
                    self._blocked_result("fetch_post", str(comments["status"]), warnings),
                    comments,
                ]
            post = await self._post_result(page, aweme_id, list(warnings))
            return [post, comments]
        except PlaywrightError as exc:
            blocked = {"status": "blocked_browser_page", "warnings": warnings, "error": {"type": type(exc).__name__}}
            return [{"op": "fetch_post", **blocked}, {"op": "fetch_comments", **blocked}]
        finally:
            await page.close()

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

    async def _accounts_from_page(self, page: Any, limit: int) -> list[dict[str, Any]]:
        links = page.locator('a[href*="/user/"]')
        accounts: dict[str, dict[str, Any]] = {}
        try:
            for index in range(min(await links.count(), 80)):
                link = links.nth(index)
                href = await link.get_attribute("href")
                account_id = visible_account_id(href)
                if not account_id or account_id in accounts:
                    continue
                text = (await link.inner_text()).strip()
                if not text:
                    image = link.locator("img").first
                    text = str(await image.get_attribute("alt") or "").strip()
                try:
                    card_text = str(await link.evaluate("el => ((el.closest('li') || el.parentElement || el).innerText || '').trim()"))
                except PlaywrightError:
                    card_text = text
                lines = [line.strip() for line in (text or card_text).splitlines() if line.strip()]
                name = lines[0] if lines else ""
                if not name:
                    continue
                profile_url = href if str(href or "").startswith("https://") else f"https://www.douyin.com/user/{account_id}"
                accounts[account_id] = {
                    "account_id": account_id,
                    "name": name[:200],
                    "bio": card_text[:500],
                    "followers": 0,
                    "posts": 0,
                    "profile_url": clean_url(profile_url),
                }
                if len(accounts) >= min(max(limit, 1), 20):
                    break
        except PlaywrightError:
            pass
        return list(accounts.values())

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
            # NextTake Content Engine deliberately exposes no raw account identifier
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
        if kind not in {"search_accounts", "resolve_account", "list_posts", "fetch_post", "fetch_comments"}:
            return {"op": kind, "status": "unsupported", "warnings": ["unsupported_operation"]}
        page = await self.context.new_page()
        warnings: list[str] = ["browser_visible_partial_coverage"]
        try:
            if kind == "search_accounts":
                keyword = str(operation.get("keyword") or "").strip()
                if not keyword:
                    return {"op": kind, "status": "invalid_input", "warnings": ["search_keyword_required"]}
                limit = min(max(positive_int(operation.get("limit"), 10), 1), 20)
                blocked = await self._navigate(page, f"https://www.douyin.com/search/{quote(keyword, safe='')}?type=video", warnings)
                if blocked:
                    return self._blocked_result(kind, blocked, warnings)
                await self._scroll(page, 1, warnings)
                blocked = await self._page_block_status(page)
                if blocked:
                    return self._blocked_result(kind, blocked, warnings)
                candidates = await self._accounts_from_page(page, limit)
                if not candidates:
                    warnings.append("no_visible_accounts_detected")
                    body = await self._body_text(page)
                    expected_empty = any(marker in body for marker in ("未找到相关", "暂无搜索结果", "没有找到"))
                    if not expected_empty:
                        warnings += ["browser_checkpoint_preserved", "manual_review_required"]
                    return {"op": kind, "status": "partial" if expected_empty else "anomalous_empty_result", "candidates": [], "coverage": self._coverage(records=0, scrolls=1, warnings=warnings, kind=kind), "warnings": warnings, **({"recovery": {"action": "review_visible_page_then_resume"}} if not expected_empty else {})}
                return {"op": kind, "status": "ok", "candidates": candidates, "coverage": self._coverage(records=len(candidates), scrolls=1, warnings=warnings, kind=kind), "warnings": warnings + ["platform_search_order_bias", "candidate_relevance_requires_review"]}
            if kind == "resolve_account":
                source_url = validate_douyin_url(str(operation.get("source_url") or ""))
                blocked = await self._navigate(page, source_url, warnings)
                if blocked:
                    return self._blocked_result(kind, blocked, warnings)
                account_id = visible_account_id(page.url)
                if not account_id:
                    links = page.locator('a[href*="/user/"]')
                    account_id = visible_account_id(await links.first.get_attribute("href")) if await links.count() else ""
                if not account_id:
                    return {"op": kind, "status": "account_not_found", "warnings": warnings}
                return {"op": kind, "status": "ok", "account_id": account_id, "warnings": warnings}
            if kind == "list_posts":
                sec_user_id = str(operation.get("sec_user_id") or "")
                if not sec_user_id:
                    return {"op": kind, "status": "invalid_input", "warnings": ["sec_user_id_required"]}
                blocked = await self._navigate(page, f"https://www.douyin.com/user/{sec_user_id}", warnings)
                if blocked:
                    return self._blocked_result(kind, blocked, warnings)
                await self._scroll(page, positive_int(operation.get("max_pages"), 1), warnings)
                blocked = await self._page_block_status(page)
                if blocked:
                    return self._blocked_result(kind, blocked, warnings)
                posts = await self._posts_from_page(page)
                if not posts:
                    warnings.append("no_visible_posts_detected")
                    body = await self._body_text(page)
                    expected_empty = any(marker in body for marker in ("暂无作品", "还没有作品", "暂时没有作品"))
                    if not expected_empty:
                        warnings += ["browser_checkpoint_preserved", "manual_review_required"]
                    return {"op": kind, "status": "partial" if expected_empty else "anomalous_empty_result", "posts": [], "coverage": self._coverage(records=0, scrolls=positive_int(operation.get("max_pages"), 1), warnings=warnings, kind=kind), "warnings": warnings, **({"recovery": {"action": "review_visible_page_then_resume"}} if not expected_empty else {})}
                return {"op": kind, "status": "ok", "posts": posts, "coverage": self._coverage(records=len(posts), scrolls=positive_int(operation.get("max_pages"), 1), warnings=warnings, kind=kind), "warnings": warnings}
            aweme_id = str(operation.get("aweme_id") or "")
            if not aweme_id:
                return {"op": kind, "status": "invalid_input", "warnings": ["aweme_id_required"]}
            if kind == "fetch_comments":
                return await self._comments_result(page, aweme_id, operation, warnings)
            blocked = await self._navigate(page, f"https://www.douyin.com/video/{aweme_id}", warnings)
            if blocked:
                return self._blocked_result(kind, blocked, warnings)
            return await self._post_result(page, aweme_id, warnings)
        except ValueError as exc:
            return {"op": kind, "status": "invalid_input", "warnings": warnings, "error": {"type": str(exc)}}
        except PlaywrightError as exc:
            return {"op": kind, "status": "blocked_browser_page", "warnings": warnings, "error": {"type": type(exc).__name__}}
        finally:
            await page.close()


async def healthcheck(profile_dir: Path, adapter_dir: Path | None) -> dict[str, Any]:
    upstream_adapter_dir(adapter_dir)
    crawler = load_upstream_crawler(upstream_adapter_dir(adapter_dir))
    if (
        not all(name in inspect.signature(crawler.fetch_comments).parameters for name in ("page", "page_guard"))
        or not hasattr(crawler, "PageCheckpoint")
    ):
        raise UpstreamAdapterIncompatible("douyin_adapter_page_reuse_required")
    playwright = await async_playwright().start()
    try:
        executable = Path(playwright.chromium.executable_path)
        if not executable.is_file():
            raise PlaywrightError("playwright_browser_runtime_missing")
        return {"runtime": "playwright-persistent-browser",
                "capabilities": ["search_accounts_visible", "resolve_account_visible", "list_posts_visible", "fetch_post_visible", "fetch_comments_visible", "manual_login"]}
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
            emit("blocked_browser_unavailable", warnings=["douyin_adapter_unavailable"])
            return 2
        except UpstreamAdapterIncompatible:
            emit("blocked_browser_unavailable", warnings=["douyin_adapter_page_reuse_required"])
            return 2
        except PlaywrightError:
            emit("blocked_browser_unavailable")
            return 2
    try:
        if args.command == "login":
            adapter_dir = upstream_adapter_dir(args.upstream_adapter_dir)
            crawler = load_upstream_crawler(adapter_dir)
            previous_root = os.environ.get("NEXTTAKE_PROJECT_ROOT")
            profile_dir = args.profile_dir.expanduser().resolve()
            profile_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.chmod(0o700)
            os.environ["NEXTTAKE_PROJECT_ROOT"] = str(profile_dir)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    logged_in = await crawler.ensure_login(max(1, min(args.wait_seconds, 900)))
            finally:
                if previous_root is None:
                    os.environ.pop("NEXTTAKE_PROJECT_ROOT", None)
                else:
                    os.environ["NEXTTAKE_PROJECT_ROOT"] = previous_root
            emit("ok" if logged_in else "blocked_auth", {"action": "manual_login_completed" if logged_in else "manual_login_incomplete"})
            return 0 if logged_in else 2
        async with BrowserProvider(args.profile_dir, args.headless, args.upstream_adapter_dir, (os.environ.get(args.commenter_hmac_key_env, "").encode() if args.commenter_hmac_key_env else None) or None) as provider:
            plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
            operations = plan.get("operations") if isinstance(plan, dict) else None
            if not isinstance(operations, list):
                emit("invalid_plan")
                return 2
            normalized_operations = [item for item in operations if isinstance(item, dict)]
            results = await execute_operations(provider, normalized_operations, operation_delay_bounds(plan))
            overall = "ok" if results and all(item.get("status") in {"ok", "unsupported"} for item in results) else "partial"
            emit(overall, {"operations": results, "provider_mode": "browser"})
            return 0 if overall == "ok" else 2
    except UpstreamAdapterUnavailable:
        emit("blocked_browser_unavailable", warnings=["douyin_adapter_unavailable"])
        return 2
    except PlaywrightError as exc:
        emit("blocked_browser_unavailable", error={"type": type(exc).__name__})
        return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-dir", type=Path, required=True)
    adapter_default = os.getenv("NEXTTAKE_DOUYIN_ADAPTER_DIR") or str(DEFAULT_UPSTREAM_ADAPTER)
    parser.add_argument("--upstream-adapter-dir", type=Path, default=adapter_default)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--commenter-hmac-key-env")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("healthcheck")
    login = commands.add_parser("login")
    login.add_argument("--wait-seconds", type=int, default=300)
    run = commands.add_parser("run")
    run.add_argument("--plan", required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
