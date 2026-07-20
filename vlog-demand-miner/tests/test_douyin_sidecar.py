from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit


MODULE = Path(__file__).parents[1] / "scripts" / "providers" / "douyin_sidecar.py"
SPEC = importlib.util.spec_from_file_location("douyin_sidecar_for_test", MODULE)
assert SPEC and SPEC.loader
sidecar = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sidecar
SPEC.loader.exec_module(sidecar)


class DouyinSidecarTests(unittest.TestCase):
    def test_resolve_account_uses_local_sidecar_without_exposing_credentials(self) -> None:
        seen: list[str] = []

        def fake_get(url: str, _timeout: int):
            seen.append(url)
            return 200, json.dumps({"code": 200, "data": "MS4-resolved"}).encode()

        provider = sidecar.DouyinProvider(sidecar.LocalSidecar("http://127.0.0.1:18080", http_get=fake_get))
        result = provider.resolve_account("https://v.douyin.com/example/")
        query = parse_qs(urlsplit(seen[0]).query)
        self.assertEqual(result["account_id"], "MS4-resolved")
        self.assertEqual(query["url"], ["https://v.douyin.com/example/"])
        self.assertNotIn("Cookie", json.dumps(result))

    def test_resolve_account_rejects_non_douyin_url_before_request(self) -> None:
        provider = sidecar.DouyinProvider(sidecar.LocalSidecar("http://127.0.0.1:18080", http_get=lambda _url, _timeout: (500, b"")))
        with self.assertRaisesRegex(sidecar.SidecarFailure, "invalid_input"):
            provider.resolve_account("https://example.com/user/1")

    def test_sidecar_search_reports_browser_or_manual_recovery(self) -> None:
        provider = sidecar.DouyinProvider(sidecar.LocalSidecar("http://127.0.0.1:18080"))
        result = provider.action({"op": "search_accounts", "keyword": "首次租房"})
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["recovery"]["action"], "use_browser_search_or_manual_account")


if __name__ == "__main__":
    unittest.main()
