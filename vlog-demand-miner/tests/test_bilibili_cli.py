from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE = Path(__file__).parents[1] / "scripts" / "providers" / "bilibili_cli.py"
SPEC = importlib.util.spec_from_file_location("bilibili_cli_bridge", MODULE)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge
SPEC.loader.exec_module(bridge)


def success(data: object) -> str:
    return json.dumps({"ok": True, "schema_version": "1", "data": data})


class FakeRunner:
    def __init__(self, *, inventory: object | None = None, video: object | None = None, code: int = 0) -> None:
        self.inventory = inventory if inventory is not None else []
        self.video = video if video is not None else {}
        self.code = code
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], _timeout: int) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[1] == "audio":
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "audio.m4a").write_bytes(b"audio")
            return subprocess.CompletedProcess(command, self.code, "", "")
        payload = self.inventory if command[1] == "user-videos" else self.video
        stdout = payload if isinstance(payload, str) else success(payload)
        return subprocess.CompletedProcess(command, self.code, stdout, "upstream diagnostic must not leak")


class BilibiliCliTests(unittest.TestCase):
    def provider(self, runner: FakeRunner, *, secret: bytes | None = b"test-secret", media_dir: Path | None = None):
        return bridge.BilibiliCli(Path(sys.executable), secret, media_dir, runner=runner)

    def test_list_posts_normalizes_inventory_without_fake_pagination(self) -> None:
        runner = FakeRunner(inventory=[{"bvid": "BV1x", "title": "瑜伽练习", "duration_seconds": 90, "stats": {"view": 12, "like": 3}}])
        result = self.provider(runner).list_posts("100", max_pages=1, page_size=20)
        self.assertEqual(result["posts"][0]["post_id"], "BV1x")
        self.assertEqual(result["posts"][0]["duration_ms"], 90_000)
        self.assertFalse(result["coverage"]["complete"])
        self.assertEqual(runner.commands[0][-3:], ["--max", "20", "--json"])

    def test_list_posts_rejects_more_than_one_page(self) -> None:
        with self.assertRaisesRegex(bridge.ProviderFailure, "safe_page_limit_exceeded"):
            self.provider(FakeRunner()).list_posts("100", max_pages=2, page_size=20)

    def test_search_accounts_reuses_single_page_user_search(self) -> None:
        runner = FakeRunner(video=[{"id": "100", "name": "首次租房指南", "sign": "租房避坑", "fans": 1200, "videos": 30}])
        result = self.provider(runner).search_accounts("首次租房", page=1, limit=5)
        self.assertEqual(result["candidates"][0]["account_id"], "100")
        self.assertEqual(result["candidates"][0]["followers"], 1200)
        self.assertEqual(runner.commands[0][1:], ["search", "首次租房", "--type", "user", "--page", "1", "--max", "5", "--json"])

    def test_search_accounts_rejects_additional_pages(self) -> None:
        with self.assertRaisesRegex(bridge.ProviderFailure, "safe_page_limit_exceeded"):
            self.provider(FakeRunner()).search_accounts("首次租房", page=2, limit=5)

    def test_content_search_returns_creator_signals_for_resolution(self) -> None:
        runner = FakeRunner(video=[{"author": "租房小林", "title": "第一次租房检查清单", "play": 5000}])
        result = self.provider(runner).search_creator_signals("首次租房", page=1, limit=10)
        self.assertEqual(result["creators"][0]["name"], "租房小林")
        self.assertEqual(result["creators"][0]["evidence_titles"], ["第一次租房检查清单"])
        self.assertIn("video", runner.commands[0])

    def test_empty_inventory_is_anomalous_not_a_successful_sync(self) -> None:
        result = self.provider(FakeRunner(inventory=[])).action({"op": "list_posts", "uid": "100"})
        self.assertEqual(result["status"], "anomalous_empty_result")

    def test_malformed_stdout_is_schema_drift_and_hides_diagnostics(self) -> None:
        result = self.provider(FakeRunner(inventory="not-json")).action({"op": "list_posts", "uid": "100"})
        self.assertEqual(result["status"], "schema_drift")
        self.assertNotIn("upstream diagnostic", json.dumps(result))

    def test_subtitle_unavailable_stays_a_successful_post_with_warning(self) -> None:
        runner = FakeRunner(video={"video": {"bvid": "BV1x", "title": "瑜伽"}, "subtitle": {"available": False, "items": []}, "comments": [], "warnings": [{"code": "subtitle_unavailable"}]})
        result = self.provider(runner).fetch_post("BV1x")
        self.assertFalse(result["subtitles"]["available"])
        self.assertIn("subtitle_unavailable", result["warnings"])

    def test_comments_anonymize_author_identity(self) -> None:
        runner = FakeRunner(video={"video": {"bvid": "BV1x"}, "subtitle": {}, "comments": [{"id": "c1", "author": {"id": "private-user", "name": "not-retained"}, "message": "需要防滑袜"}], "warnings": []})
        result = self.provider(runner).fetch_comments("BV1x")
        serialized = json.dumps(result)
        self.assertNotIn("private-user", serialized)
        self.assertNotIn("not-retained", serialized)
        self.assertEqual(len(result["comments"][0]["commenter_id"]), 64)

    def test_audio_success_is_reported_without_upstream_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.provider(FakeRunner(), media_dir=Path(directory)).fetch_media("BV1x")
            self.assertEqual(result["media"]["container"], "m4a")
            self.assertEqual(result["media"]["bytes"], 5)

    def test_healthcheck_rejects_a_present_but_unrunnable_entrypoint(self) -> None:
        with self.assertRaisesRegex(bridge.ProviderFailure, "provider_unavailable"):
            self.provider(FakeRunner(code=1)).healthcheck()


if __name__ == "__main__":
    unittest.main()
