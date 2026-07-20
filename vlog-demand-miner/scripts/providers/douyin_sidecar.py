#!/usr/bin/env python3
"""Serialized, credential-isolated bridge for the local Douyin Sidecar.

The Sidecar owns Douyin request signing and its private credential volume. This
bridge only talks to a localhost Sidecar and emits a small, normalized contract
for the demand-mining pipeline. It never accepts or prints Cookie values.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import urlopen

API_PREFIX = "/api/douyin/web"
FALLBACK_STATUSES = {"blocked_auth", "blocked_verification", "risk_control", "schema_drift", "anomalous_empty_result"}


class SidecarFailure(Exception):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(status)


def emit(status: str, data: Any = None, warnings: list[str] | None = None) -> None:
    print(json.dumps({"schema_version": "1.0.0", "status": status, "data": data, "warnings": warnings or []}, ensure_ascii=False))


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_sidecar_url(value: str) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("sidecar_url_must_be_localhost")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("sidecar_url_must_not_contain_credentials_or_query")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def classify_error(http_status: int, body: bytes) -> str:
    """Classify locally; raw upstream diagnostics never leave this process."""
    text = body[:4_096].decode("utf-8", errors="ignore").casefold()
    if "captcha" in text or "verify" in text or "验证码" in text:
        return "blocked_verification"
    if "risk" in text or "风控" in text:
        return "risk_control"
    if http_status in {401, 403}:
        return "blocked_auth"
    return "sidecar_http_error"


def unwrap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("code") != 200 or not isinstance(payload.get("data"), dict):
        raise SidecarFailure("schema_drift")
    return payload["data"]


def unwrap_value(payload: Any) -> Any:
    if not isinstance(payload, dict) or payload.get("code") != 200 or "data" not in payload:
        raise SidecarFailure("schema_drift")
    return payload["data"]


def validate_douyin_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "douyin.com" or host.endswith(".douyin.com")):
        raise SidecarFailure("invalid_input")
    if parsed.username or parsed.password:
        raise SidecarFailure("invalid_input")
    return value.strip()


def pick_list(data: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    nested = data.get("data")
    return pick_list(nested, *keys) if isinstance(nested, dict) else []


def has_more(data: dict[str, Any]) -> bool:
    for key in ("has_more", "hasMore"):
        if key in data:
            return data[key] if isinstance(data[key], bool) else bool(as_int(data[key]))
    nested = data.get("data")
    return has_more(nested) if isinstance(nested, dict) else False


def next_cursor(data: dict[str, Any], current: int) -> int | None:
    for key in ("max_cursor", "cursor", "next_cursor", "nextCursor"):
        if key in data:
            candidate = as_int(data[key])
            if candidate != current:
                return candidate
    nested = data.get("data")
    return next_cursor(nested, current) if isinstance(nested, dict) else None


def normalize_post(raw: dict[str, Any]) -> dict[str, Any]:
    stats, video, author = raw.get("statistics") or raw.get("stats") or {}, raw.get("video") or {}, raw.get("author") or {}
    is_image_post = bool(raw.get("images") or raw.get("image_infos") or raw.get("image_post_info"))
    return {
        "post_id": str(raw.get("aweme_id") or raw.get("item_id") or raw.get("id") or ""),
        "creator_id": str(author.get("sec_uid") or raw.get("sec_user_id") or ""),
        "title": str(raw.get("desc") or raw.get("title") or "")[:500],
        "published_at": raw.get("create_time") or raw.get("createTime"),
        "duration_ms": as_int(video.get("duration") or raw.get("duration")),
        "content_type": "image_post" if is_image_post else "video",
        "public_metrics": {"likes": as_int(stats.get("digg_count") or raw.get("digg_count")), "comments": as_int(stats.get("comment_count") or raw.get("comment_count")), "collects": as_int(stats.get("collect_count") or raw.get("collect_count")), "shares": as_int(stats.get("share_count") or raw.get("share_count"))},
    }


def normalize_comment(raw: dict[str, Any], post_id: str, secret: bytes | None) -> dict[str, Any]:
    result = {"comment_id": str(raw.get("cid") or raw.get("comment_id") or raw.get("id") or ""), "post_id": post_id, "text": str(raw.get("text") or raw.get("content") or ""), "like_count": as_int(raw.get("digg_count") or raw.get("like_count")), "reply_count": as_int(raw.get("reply_comment_total") or raw.get("reply_count")), "created_at": raw.get("create_time") or raw.get("createTime")}
    user = raw.get("user") or raw.get("user_info") or {}
    raw_id = str(user.get("uid") or user.get("user_id") or raw.get("uid") or "")
    if raw_id and secret:
        result["commenter_id"] = hmac.new(secret, f"douyin:{raw_id}".encode(), hashlib.sha256).hexdigest()
    return result


@dataclass
class LocalSidecar:
    base_url: str
    timeout_seconds: int = 30
    http_get: Callable[[str, int], tuple[int, bytes]] | None = None

    def __post_init__(self) -> None:
        self.base_url = normalize_sidecar_url(self.base_url)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}" + (f"?{urlencode(params or {})}" if params else "")
        try:
            if self.http_get:
                status, body = self.http_get(url, self.timeout_seconds)
            else:
                with urlopen(url, timeout=self.timeout_seconds) as response:  # nosec B310: validated localhost only
                    status, body = response.status, response.read()
        except HTTPError as exc:
            raise SidecarFailure(classify_error(exc.code, exc.read())) from exc
        except URLError as exc:
            raise SidecarFailure("sidecar_unavailable") from exc
        if status != 200:
            raise SidecarFailure(classify_error(status, body))
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise SidecarFailure("schema_drift") from exc

    def download_to(self, source_url: str, target_stem: Path) -> dict[str, Any]:
        parsed = urlsplit(source_url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith("douyin.com"):
            raise SidecarFailure("invalid_input")
        url = f"{self.base_url}/api/download?{urlencode({'url': source_url, 'prefix': 'false'})}"
        try:
            with urlopen(url, timeout=self.timeout_seconds) as response:  # nosec B310: validated localhost only
                if response.status != 200:
                    raise SidecarFailure("sidecar_http_error")
                content_type = response.headers.get("content-type", "")
                if content_type.startswith("video/") or content_type == "application/octet-stream":
                    target, container, audio_track = target_stem.with_suffix(".mp4"), "mp4", "included_for_asr"
                elif content_type == "application/zip":
                    target, container, audio_track = target_stem.with_suffix(".zip"), "zip", "unavailable_image_archive"
                else:
                    raise SidecarFailure("schema_drift")
                target.parent.mkdir(parents=True, exist_ok=True)
                bytes_written = 0
                with target.open("wb") as handle:
                    while chunk := response.read(1_048_576):
                        handle.write(chunk)
                        bytes_written += len(chunk)
                if not bytes_written:
                    target.unlink(missing_ok=True)
                    raise SidecarFailure("anomalous_empty_result")
                return {"filename": target.name, "bytes": bytes_written, "container": container, "audio_track": audio_track}
        except HTTPError as exc:
            raise SidecarFailure(classify_error(exc.code, exc.read())) from exc
        except URLError as exc:
            raise SidecarFailure("sidecar_unavailable") from exc


class DouyinProvider:
    def __init__(self, sidecar: LocalSidecar, commenter_secret: bytes | None = None, media_dir: Path | None = None) -> None:
        self.sidecar, self.commenter_secret, self.media_dir = sidecar, commenter_secret, media_dir

    def healthcheck(self) -> dict[str, Any]:
        paths = self.sidecar.get_json("/openapi.json").get("paths")
        required = {f"{API_PREFIX}/fetch_one_video", f"{API_PREFIX}/fetch_user_post_videos", f"{API_PREFIX}/fetch_video_comments", f"{API_PREFIX}/fetch_video_comment_replies", f"{API_PREFIX}/get_sec_user_id", "/api/download"}
        if not isinstance(paths, dict) or not required.issubset(paths):
            raise SidecarFailure("schema_drift")
        return {"runtime": "local-douyin-sidecar", "capabilities": sorted(required)}

    def resolve_account(self, source_url: str) -> dict[str, Any]:
        value = unwrap_value(self.sidecar.get_json(f"{API_PREFIX}/get_sec_user_id", {"url": validate_douyin_url(source_url)}))
        if isinstance(value, dict):
            account_id = str(value.get("sec_user_id") or value.get("sec_uid") or "")
        else:
            account_id = str(value or "")
        if not account_id:
            raise SidecarFailure("account_not_found")
        return {"status": "ok", "account_id": account_id}

    def fetch_post(self, aweme_id: str) -> dict[str, Any]:
        data = unwrap(self.sidecar.get_json(f"{API_PREFIX}/fetch_one_video", {"aweme_id": aweme_id}))
        raw = data.get("aweme_detail") or data.get("aweme") or data
        if not isinstance(raw, dict):
            raise SidecarFailure("schema_drift")
        post = normalize_post(raw)
        if not post["post_id"]:
            raise SidecarFailure("schema_drift")
        return {"status": "ok", "post": post}

    def list_posts(self, sec_user_id: str, max_pages: int, page_size: int, initial_cursor: int = 0) -> dict[str, Any]:
        cursor, pages, posts, records_seen, exhausted = initial_cursor, 0, {}, 0, False
        for _ in range(max_pages):
            data = unwrap(self.sidecar.get_json(f"{API_PREFIX}/fetch_user_post_videos", {"sec_user_id": sec_user_id, "max_cursor": cursor, "count": page_size}))
            pages += 1
            page_posts = pick_list(data, "aweme_list", "item_list", "items")
            records_seen += len(page_posts)
            for raw in page_posts:
                post = normalize_post(raw)
                if post["post_id"]:
                    posts[post["post_id"]] = post
            if not has_more(data):
                exhausted = True
                break
            cursor = next_cursor(data, cursor)
            if cursor is None:
                raise SidecarFailure("schema_drift")
        if not posts:
            raise SidecarFailure("anomalous_empty_result")
        return {"status": "ok", "posts": list(posts.values()), "coverage": {"pages_fetched": pages, "records_seen": records_seen, "records_unique": len(posts), "complete": exhausted, "next_cursor": None if exhausted else cursor, "stopped_reason": "source_exhausted" if exhausted else "configured_page_limit"}}

    def fetch_comments(self, aweme_id: str, max_pages: int, page_size: int, require_nonempty: bool, initial_cursor: int = 0) -> dict[str, Any]:
        return self._comment_pages(f"{API_PREFIX}/fetch_video_comments", {"aweme_id": aweme_id}, aweme_id, max_pages, page_size, require_nonempty, initial_cursor)

    def fetch_replies(self, aweme_id: str, comment_id: str, max_pages: int, page_size: int, initial_cursor: int = 0) -> dict[str, Any]:
        return self._comment_pages(f"{API_PREFIX}/fetch_video_comment_replies", {"item_id": aweme_id, "comment_id": comment_id}, aweme_id, max_pages, page_size, False, initial_cursor)

    def fetch_media(self, aweme_id: str, source_url: str) -> dict[str, Any]:
        if not self.media_dir:
            raise SidecarFailure("invalid_input")
        media = self.sidecar.download_to(source_url, self.media_dir / f"douyin-{aweme_id}")
        return {"status": "ok", "media": media}

    def _comment_pages(self, path: str, fixed: dict[str, Any], aweme_id: str, max_pages: int, page_size: int, require_nonempty: bool, initial_cursor: int) -> dict[str, Any]:
        cursor, pages, comments, records_seen, exhausted = initial_cursor, 0, {}, 0, False
        for _ in range(max_pages):
            data = unwrap(self.sidecar.get_json(path, {**fixed, "cursor": cursor, "count": page_size}))
            pages += 1
            page_comments = pick_list(data, "comments", "comment_list")
            records_seen += len(page_comments)
            for raw in page_comments:
                comment = normalize_comment(raw, aweme_id, self.commenter_secret)
                if comment["comment_id"]:
                    comments[comment["comment_id"]] = comment
            if not has_more(data):
                exhausted = True
                break
            cursor = next_cursor(data, cursor)
            if cursor is None:
                raise SidecarFailure("schema_drift")
        if require_nonempty and not comments:
            raise SidecarFailure("anomalous_empty_result")
        warnings = [] if self.commenter_secret else ["commenter_identity_unavailable"]
        return {"status": "ok", "comments": list(comments.values()), "coverage": {"pages_fetched": pages, "records_seen": records_seen, "comments_fetched": len(comments), "complete": exhausted, "next_cursor": None if exhausted else cursor, "stopped_reason": "source_exhausted" if exhausted else "configured_page_limit"}, "warnings": warnings}

    def action(self, operation: dict[str, Any]) -> dict[str, Any]:
        kind = operation.get("op")
        page_size = min(max(as_int(operation.get("page_size") or 20), 1), 20)
        max_pages = max(as_int(operation.get("max_pages") or 1), 1)
        try:
            if kind == "search_accounts":
                return {"op": kind, "status": "unsupported", "recovery": {"action": "use_browser_search_or_manual_account"}, "warnings": ["sidecar_search_endpoint_unavailable"]}
            if kind == "resolve_account":
                return {"op": kind, **self.resolve_account(str(operation["source_url"]))}
            if kind == "fetch_post":
                return {"op": kind, **self.fetch_post(str(operation["aweme_id"]))}
            if kind == "list_posts":
                return {"op": kind, **self.list_posts(str(operation["sec_user_id"]), max_pages, page_size, as_int(operation.get("cursor")))}
            if kind == "fetch_comments":
                return {"op": kind, **self.fetch_comments(str(operation["aweme_id"]), max_pages, page_size, bool(operation.get("require_nonempty", False)), as_int(operation.get("cursor")))}
            if kind == "fetch_replies":
                return {"op": kind, **self.fetch_replies(str(operation["aweme_id"]), str(operation["comment_id"]), max_pages, page_size, as_int(operation.get("cursor")))}
            if kind == "fetch_media":
                return {"op": kind, **self.fetch_media(str(operation["aweme_id"]), str(operation["source_url"]))}
            return {"op": kind, "status": "unsupported", "warnings": ["unsupported_operation"]}
        except KeyError:
            return {"op": kind, "status": "invalid_input", "warnings": ["required_input_missing"]}
        except SidecarFailure as exc:
            result = {"op": kind, "status": exc.status}
            if exc.status in FALLBACK_STATUSES:
                result["recovery"] = {"action": "switch_to_browser_fallback", "resume_checkpoint": kind}
            return result


def main(args: argparse.Namespace) -> int:
    secret = os.environ.get(args.commenter_hmac_key_env, "").encode() if args.commenter_hmac_key_env else None
    provider = DouyinProvider(LocalSidecar(args.sidecar_url, args.timeout_seconds), secret or None, args.media_dir)
    if args.command == "healthcheck":
        try:
            emit("ok", provider.healthcheck())
            return 0
        except SidecarFailure as exc:
            emit(exc.status)
            return 2
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        operations = plan["operations"]
        if not isinstance(operations, list):
            raise ValueError
    except (OSError, ValueError, json.JSONDecodeError, KeyError):
        emit("invalid_plan")
        return 2
    results = [provider.action(operation) for operation in operations if isinstance(operation, dict)]
    overall = "ok" if results and all(result.get("status") == "ok" for result in results) else "partial"
    emit(overall, {"operations": results})
    return 0 if overall == "ok" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar-url", default="http://127.0.0.1:18080")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--commenter-hmac-key-env")
    parser.add_argument("--media-dir", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("healthcheck")
    run = commands.add_parser("run")
    run.add_argument("--plan", required=True)
    raise SystemExit(main(parser.parse_args()))
