#!/usr/bin/env python3
"""Thin, serialized bridge for the pinned ``bilibili-cli`` executable.

The upstream CLI owns Bilibili API details.  This bridge invokes it one command
at a time, removes platform identities before returning comments, and emits
only the demand-miner JSON envelope.  It deliberately does not parse or retain
upstream diagnostics, credentials, or raw platform responses.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class ProviderFailure(Exception):
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


def normalize_post(raw: dict[str, Any]) -> dict[str, Any]:
    bvid = str(raw.get("bvid") or raw.get("id") or "")
    stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}
    return {
        "post_id": bvid,
        "creator_id": str((raw.get("owner") or {}).get("id") or ""),
        "title": str(raw.get("title") or "")[:500],
        # The upstream normalized inventory payload has no publish timestamp.
        # Keep it explicit rather than inventing one from collection time.
        "published_at": None,
        "duration_ms": as_int(raw.get("duration_seconds")) * 1_000,
        "content_type": "video",
        "public_metrics": {
            "views": as_int(stats.get("view") or raw.get("play")),
            "likes": as_int(stats.get("like")),
            "coins": as_int(stats.get("coin")),
            "favorites": as_int(stats.get("favorite")),
            "shares": as_int(stats.get("share")),
        },
    }


def normalize_comment(raw: dict[str, Any], post_id: str, secret: bytes | None) -> dict[str, Any]:
    result = {
        "comment_id": str(raw.get("id") or ""),
        "post_id": post_id,
        "text": str(raw.get("message") or ""),
        "like_count": as_int(raw.get("like")),
        "reply_count": as_int(raw.get("reply_count")),
        "created_at": None,
    }
    raw_id = str((raw.get("author") or {}).get("id") or "")
    if raw_id and secret:
        result["commenter_id"] = hmac.new(secret, f"bilibili:{raw_id}".encode(), hashlib.sha256).hexdigest()
    return result


Runner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


@dataclass
class BilibiliCli:
    executable: Path
    commenter_secret: bytes | None = None
    media_dir: Path | None = None
    timeout_seconds: int = 120
    runner: Runner | None = None

    def _run(self, arguments: list[str], *, json_output: bool = True) -> Any:
        command = [str(self.executable), *arguments]
        if json_output:
            command.append("--json")
        try:
            completed = self.runner(command, self.timeout_seconds) if self.runner else subprocess.run(
                command, capture_output=True, text=True, timeout=self.timeout_seconds, check=False
            )
        except FileNotFoundError as exc:
            raise ProviderFailure("provider_unavailable") from exc
        except subprocess.TimeoutExpired as exc:
            raise ProviderFailure("provider_timeout") from exc

        if not json_output:
            if completed.returncode != 0:
                raise ProviderFailure("upstream_error")
            return None
        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderFailure("schema_drift") from exc
        if not isinstance(envelope, dict) or envelope.get("schema_version") != "1":
            raise ProviderFailure("schema_drift")
        if envelope.get("ok") is not True:
            error = envelope.get("error") if isinstance(envelope.get("error"), dict) else {}
            raise ProviderFailure(str(error.get("code") or "upstream_error"))
        return envelope.get("data")

    def healthcheck(self) -> dict[str, Any]:
        executable = str(self.executable)
        if not ((self.executable.is_file() and os.access(self.executable, os.X_OK)) or shutil.which(executable)):
            raise ProviderFailure("provider_unavailable")
        # A moved virtual environment can leave the console script present but
        # point it at a missing interpreter or editable source tree. Execute a
        # local-only version probe so doctor does not report that state as OK.
        command = [str(self.executable), "--version"]
        try:
            completed = self.runner(command, self.timeout_seconds) if self.runner else subprocess.run(command, capture_output=True, text=True, timeout=self.timeout_seconds)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderFailure("provider_unavailable") from exc
        if completed.returncode != 0:
            raise ProviderFailure("provider_unavailable")
        return {"runtime": "pinned-bilibili-cli", "capabilities": ["search_creator_signals", "search_accounts", "list_posts", "fetch_post", "fetch_comments", "fetch_media"]}

    def list_posts(self, uid: str, max_pages: int, page_size: int) -> dict[str, Any]:
        if max_pages != 1:
            raise ProviderFailure("safe_page_limit_exceeded")
        limit = min(max(max_pages, 1) * min(max(page_size, 1), 50), 1_000)
        data = self._run(["user-videos", uid, "--max", str(limit)])
        if not isinstance(data, list):
            raise ProviderFailure("schema_drift")
        posts = [normalize_post(raw) for raw in data if isinstance(raw, dict) and normalize_post(raw)["post_id"]]
        if not posts:
            raise ProviderFailure("anomalous_empty_result")
        return {"status": "ok", "posts": posts, "coverage": {
            "requested_limit": limit, "records_seen": len(data), "records_unique": len({post["post_id"] for post in posts}),
            "complete": False, "next_cursor": None, "stopped_reason": "provider_latest_limit_no_cursor",
        }, "warnings": ["inventory_publish_time_unavailable"]}

    def search_accounts(self, keyword: str, page: int, limit: int) -> dict[str, Any]:
        if page != 1:
            raise ProviderFailure("safe_page_limit_exceeded")
        keyword = keyword.strip()
        if not keyword:
            raise ProviderFailure("invalid_input")
        count = min(max(limit, 1), 20)
        data = self._run(["search", keyword, "--type", "user", "--page", "1", "--max", str(count)])
        if not isinstance(data, list):
            raise ProviderFailure("schema_drift")
        candidates = []
        for raw in data[:count]:
            if not isinstance(raw, dict):
                continue
            account_id = str(raw.get("id") or "")
            name = str(raw.get("name") or "").strip()
            if account_id and name:
                candidates.append({
                    "account_id": account_id,
                    "name": name[:200],
                    "bio": str(raw.get("sign") or "")[:500],
                    "followers": as_int(raw.get("fans")),
                    "posts": as_int(raw.get("videos")),
                    "profile_url": f"https://space.bilibili.com/{account_id}",
                })
        return {
            "status": "ok",
            "candidates": candidates,
            "coverage": {"page": 1, "records_seen": len(data), "records_returned": len(candidates), "complete": False, "stopped_reason": "single_search_page_limit"},
            "warnings": ["platform_search_order_bias", "candidate_relevance_requires_review"],
        }

    def search_creator_signals(self, keyword: str, page: int, limit: int) -> dict[str, Any]:
        if page != 1:
            raise ProviderFailure("safe_page_limit_exceeded")
        keyword = keyword.strip()
        if not keyword:
            raise ProviderFailure("invalid_input")
        count = min(max(limit, 1), 20)
        data = self._run(["search", keyword, "--type", "video", "--page", "1", "--max", str(count)])
        if not isinstance(data, list):
            raise ProviderFailure("schema_drift")
        creators: dict[str, dict[str, Any]] = {}
        for raw in data[:count]:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("author") or "").strip()
            title = str(raw.get("title") or "").strip()
            if not name or not title:
                continue
            signal = creators.setdefault(name, {"name": name[:200], "evidence_titles": [], "plays": 0})
            if title[:500] not in signal["evidence_titles"]:
                signal["evidence_titles"].append(title[:500])
            signal["plays"] = max(signal["plays"], as_int(raw.get("play")))
        return {
            "status": "ok",
            "keyword": keyword,
            "creators": list(creators.values()),
            "coverage": {"page": 1, "records_seen": len(data), "creator_names": len(creators), "complete": False, "stopped_reason": "single_search_page_limit"},
            "warnings": ["content_search_order_bias", "creator_identity_requires_resolution"],
        }

    def fetch_post(self, bvid: str) -> dict[str, Any]:
        data = self._run(["video", bvid, "--subtitle-timeline", "--comments"])
        if not isinstance(data, dict) or not isinstance(data.get("video"), dict):
            raise ProviderFailure("schema_drift")
        post = normalize_post(data["video"])
        if not post["post_id"]:
            raise ProviderFailure("schema_drift")
        subtitle = data.get("subtitle") if isinstance(data.get("subtitle"), dict) else {}
        warnings = [str(item.get("code")) for item in data.get("warnings", []) if isinstance(item, dict) and item.get("code")]
        return {"status": "ok", "post": post, "subtitles": {
            "available": bool(subtitle.get("available")), "segments": subtitle.get("items") if isinstance(subtitle.get("items"), list) else [],
        }, "warnings": warnings}

    def fetch_comments(self, bvid: str) -> dict[str, Any]:
        data = self._run(["video", bvid, "--comments"])
        if not isinstance(data, dict) or not isinstance(data.get("comments"), list):
            raise ProviderFailure("schema_drift")
        comments = [normalize_comment(raw, bvid, self.commenter_secret) for raw in data["comments"] if isinstance(raw, dict) and raw.get("id")]
        warnings = [] if self.commenter_secret else ["commenter_identity_unavailable"]
        warnings.append("popular_comments_only")
        return {"status": "ok", "comments": comments, "coverage": {
            "comments_fetched": len(comments), "complete": False, "sort": "popular", "stopped_reason": "provider_top_comments_only",
        }, "warnings": warnings}

    def fetch_replies(self, _bvid: str, _comment_id: str) -> dict[str, Any]:
        return {"status": "unsupported", "recovery": {"action": "manual_or_future_deep_comment_provider"}}

    def fetch_media(self, bvid: str) -> dict[str, Any]:
        if not self.media_dir:
            raise ProviderFailure("invalid_input")
        target = self.media_dir / f"bilibili-{bvid}"
        target.mkdir(parents=True, exist_ok=True)
        before = {path.resolve() for path in target.glob("*") if path.is_file()}
        self._run(["audio", bvid, "--no-split", "--output", str(target)], json_output=False)
        files = [path for path in target.glob("*.m4a") if path.is_file() and path.resolve() not in before]
        if len(files) != 1 or files[0].stat().st_size <= 0:
            raise ProviderFailure("anomalous_empty_result")
        media = files[0]
        return {"status": "ok", "media": {"filename": media.name, "bytes": media.stat().st_size, "container": "m4a", "audio_track": "native_audio_for_asr"}}

    def action(self, operation: dict[str, Any]) -> dict[str, Any]:
        try:
            kind = operation.get("op")
            if kind == "healthcheck": return {"status": "ok", "health": self.healthcheck()}
            if kind == "search_creator_signals": return self.search_creator_signals(str(operation.get("keyword") or ""), as_int(operation.get("page") or 1), as_int(operation.get("limit") or 10))
            if kind == "search_accounts": return self.search_accounts(str(operation.get("keyword") or ""), as_int(operation.get("page") or 1), as_int(operation.get("limit") or 10))
            if kind == "list_posts": return self.list_posts(str(operation.get("uid") or ""), as_int(operation.get("max_pages") or 1), as_int(operation.get("page_size") or 20))
            if kind == "fetch_post": return self.fetch_post(str(operation.get("bvid") or ""))
            if kind == "fetch_comments": return self.fetch_comments(str(operation.get("bvid") or ""))
            if kind == "fetch_replies": return self.fetch_replies(str(operation.get("bvid") or ""), str(operation.get("comment_id") or ""))
            if kind == "fetch_media": return self.fetch_media(str(operation.get("bvid") or ""))
            return {"status": "invalid_input"}
        except ProviderFailure as exc:
            return {"status": exc.status}


def main(args: argparse.Namespace) -> int:
    secret = os.getenv(args.commenter_hmac_key_env).encode() if args.commenter_hmac_key_env and os.getenv(args.commenter_hmac_key_env) else None
    provider = BilibiliCli(Path(args.bilibili_cli).expanduser(), secret, args.media_dir, args.timeout_seconds)
    if args.command == "healthcheck":
        result = provider.action({"op": "healthcheck"})
        emit(result["status"], result.get("health"))
        return 0 if result["status"] == "ok" else 2
    try:
        payload = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        emit("invalid_input")
        return 2
    operations = payload.get("operations") if isinstance(payload, dict) else None
    if not isinstance(operations, list):
        emit("invalid_input")
        return 2
    results = [provider.action(operation) for operation in operations if isinstance(operation, dict)]
    overall = "ok" if results and all(result.get("status") == "ok" for result in results) else "partial"
    emit(overall, {"operations": results})
    return 0 if overall == "ok" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bilibili-cli", default=os.getenv("VDM_BILIBILI_CLI", "bili"))
    parser.add_argument("--commenter-hmac-key-env")
    parser.add_argument("--media-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("healthcheck")
    run = commands.add_parser("run")
    run.add_argument("--plan", required=True)
    raise SystemExit(main(parser.parse_args()))
