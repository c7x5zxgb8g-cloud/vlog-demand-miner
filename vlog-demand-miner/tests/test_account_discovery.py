from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


CLI = Path(__file__).parents[1] / "scripts" / "vdm.py"
SPEC = importlib.util.spec_from_file_location("vdm_for_account_discovery_test", CLI)
assert SPEC and SPEC.loader
vdm = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(CLI.parent))
SPEC.loader.exec_module(vdm)


def args(**overrides):
    values = {
        "account_id": None,
        "account_url": None,
        "sec_user_id": None,
        "credential_ref": None,
        "name": "对标账号",
        "platform": "bilibili",
        "bilibili_cli": "/tmp/bili",
        "commenter_hmac_key_env": None,
        "douyin_provider": "auto",
        "douyin_adapter_revision": "test",
        "enable_experimental_douyin_discovery": False,
        "request_delay_min_seconds": 0,
        "request_delay_max_seconds": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class AccountDiscoveryTests(unittest.TestCase):
    def test_default_keywords_expand_track_with_bounded_queries(self) -> None:
        self.assertEqual(vdm.discovery_keywords("首次租房"), ["首次租房", "首次租房经验", "首次租房避坑"])
        self.assertEqual(vdm.discovery_keywords("租房避坑"), ["租房避坑", "租房避坑经验"])

    def test_duplicate_search_hits_do_not_outscore_unique_content_evidence(self) -> None:
        repeated = [
            {"keyword": query, "creators": [{"name": "重复账号", "evidence_titles": ["同一条租房视频"], "plays": 1000}]}
            for query in ("首次租房", "首次租房经验", "首次租房避坑")
        ]
        unique = {"keyword": "首次租房", "creators": [{"name": "持续创作者", "evidence_titles": ["租房检查清单", "入住第一天"], "plays": 500}]}
        ranked = vdm.rank_creator_signals([*repeated, unique])
        self.assertEqual(ranked[0]["name"], "持续创作者")

    def test_default_automatic_discovery_only_selects_bilibili(self) -> None:
        response = {"status": "ok", "data": {"operations": []}, "warnings": []}
        with tempfile.TemporaryDirectory() as directory, patch.object(vdm, "run_provider", return_value=response) as provider:
            project = Path(directory)
            db = vdm.connect(project)
            result = vdm.do_creator_discover(project, db, "首次租房", None, None, 1, args())
            db.close()
        self.assertEqual([item["platform"] for item in result["platforms"]], ["bilibili"])
        self.assertTrue(all(call.args[1] == "bilibili" for call in provider.call_args_list))

    def test_automatic_discovery_adds_top_account_per_platform_and_reuses(self) -> None:
        def fake_provider(_project, platform, _args, operations):
            results = []
            for index, operation in enumerate(operations):
                if operation["op"] == "search_creator_signals":
                    results.append({"op": "search_creator_signals", "status": "ok", "keyword": operation["keyword"], "creators": [{"name": "首次租房指南", "evidence_titles": ["第一次租房要检查什么"], "plays": 5000}]})
                    continue
                if platform == "bilibili":
                    candidates = [
                        {"account_id": "100", "name": "首次租房指南", "bio": "租房经验和避坑", "followers": 1000, "posts": 40, "profile_url": "https://space.bilibili.com/100"},
                        {"account_id": f"20{index}", "name": "生活记录", "bio": "日常", "followers": 100, "posts": 10, "profile_url": ""},
                    ]
                else:
                    candidates = [{"account_id": "d-1", "name": "首次租房日记", "bio": "租房避坑", "followers": 0, "posts": 0, "profile_url": "https://www.douyin.com/user/d-1"}]
                results.append({"op": "search_accounts", "status": "ok", "candidates": candidates})
            return {"status": "ok", "data": {"operations": results}, "warnings": []}

        with tempfile.TemporaryDirectory() as directory, patch.object(vdm, "run_provider", side_effect=fake_provider) as provider:
            project = Path(directory)
            db = vdm.connect(project)
            discover_args = args(enable_experimental_douyin_discovery=True)
            first = vdm.do_creator_discover(project, db, "首次租房", ["bilibili", "douyin"], None, 1, discover_args)
            second = vdm.do_creator_discover(project, db, "首次租房", ["bilibili", "douyin"], None, 1, discover_args)
            accounts = db.execute("SELECT platform,platform_account_id FROM accounts ORDER BY platform").fetchall()
            task_inputs = [json.loads(row[0]) for row in db.execute("SELECT input_json FROM tasks WHERE kind='account-discover' ORDER BY entity_id").fetchall()]
            db.close()
        self.assertEqual(first["status"], "ok")
        self.assertEqual([item["status"] for item in second["platforms"]], ["reused", "reused"])
        self.assertEqual(provider.call_count, 3)
        self.assertEqual([(row[0], row[1]) for row in accounts], [("bilibili", "100"), ("douyin", "d-1")])
        self.assertTrue(all(item["acquisition_policy"]["execution"] == "serial" for item in task_inputs))
        self.assertIn("not evidence of demand", first["notice"])

    def test_douyin_automatic_discovery_requires_explicit_experimental_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(vdm, "run_provider") as provider:
            project = Path(directory)
            db = vdm.connect(project)
            result = vdm.do_creator_discover(project, db, "首次租房", ["douyin"], None, 1, args())
            account_count = db.execute("SELECT count(*) FROM accounts").fetchone()[0]
            task_count = db.execute("SELECT count(*) FROM tasks WHERE kind='account-discover'").fetchone()[0]
            db.close()
        self.assertEqual(result["status"], "manual_input_required")
        self.assertEqual(result["platforms"][0]["next_action"], "import_benchmark_account")
        self.assertIn("profile_url", result["platforms"][0]["accepted_inputs"])
        self.assertEqual(account_count, 0)
        self.assertEqual(task_count, 0)
        provider.assert_not_called()

    def test_manual_bilibili_profile_url_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            db = vdm.connect(project)
            manual_args = args(account_url="https://space.bilibili.com/12345", name="租房博主")
            first = vdm.do_creator_add(project, db, manual_args)
            second = vdm.do_creator_add(project, db, manual_args)
            count = db.execute("SELECT count(*) FROM accounts").fetchone()[0]
            db.close()
        self.assertTrue(first["added"])
        self.assertFalse(second["added"])
        self.assertEqual(first["account_id"], "12345")
        self.assertEqual(count, 1)

    def test_manual_douyin_share_url_uses_provider_resolution(self) -> None:
        response = {"status": "ok", "data": {"operations": [{"op": "resolve_account", "status": "ok", "account_id": "MS4-resolved"}]}}
        with tempfile.TemporaryDirectory() as directory, patch.object(vdm, "run_provider", return_value=response) as provider:
            project = Path(directory)
            db = vdm.connect(project)
            result = vdm.do_creator_add(project, db, args(platform="douyin", account_url="https://v.douyin.com/example/", name="租房博主"))
            db.close()
        self.assertEqual(result["account_id"], "MS4-resolved")
        self.assertEqual(result["source"], "share_url")
        self.assertEqual(provider.call_args.args[3][0]["op"], "resolve_account")


if __name__ == "__main__":
    unittest.main()
