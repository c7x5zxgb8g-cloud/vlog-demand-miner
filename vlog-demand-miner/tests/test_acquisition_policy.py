from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


CLI = Path(__file__).parents[1] / "scripts" / "vdm.py"
SPEC = importlib.util.spec_from_file_location("vdm_for_acquisition_policy_test", CLI)
assert SPEC and SPEC.loader
vdm = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(CLI.parent))
SPEC.loader.exec_module(vdm)


def args(**overrides):
    values = {
        "bilibili_cli": "/tmp/bili",
        "commenter_hmac_key_env": None,
        "douyin_provider": "auto",
        "douyin_adapter_revision": "test",
        "request_delay_min_seconds": 6,
        "request_delay_max_seconds": 12,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeClock:
    def __init__(self, value: float) -> None:
        self.value = value
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class AcquisitionPolicyTests(unittest.TestCase):
    def test_provider_processes_disable_bytecode_writes(self) -> None:
        completed = subprocess.CompletedProcess(["provider"], 0, '{"status":"ok","data":{}}', "")
        with tempfile.TemporaryDirectory() as directory, patch.object(vdm.subprocess, "run", return_value=completed) as run:
            plan = Path(directory) / "plan.json"
            plan.write_text('{"operations":[]}', encoding="utf-8")
            vdm.invoke_provider(["provider"], plan)
        self.assertEqual(run.call_args.kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")

    def test_bilibili_sync_rejects_more_than_one_page_before_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            db = vdm.connect(project)
            db.execute("INSERT INTO creators VALUES ('creator-1','test',0)")
            db.execute("INSERT INTO accounts VALUES ('account-1','creator-1','bilibili','100',NULL)")
            db.commit()
            with patch.object(vdm, "run_provider") as provider:
                result = vdm.do_sync(project, db, "creator-1", 2, "bilibili", args())
            db.close()
        self.assertEqual(result, {"status": "invalid_input", "error": "bilibili_sync_requires_single_page"})
        provider.assert_not_called()

    def test_invalid_delay_range_is_structured_input_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "request_delay_must_be_numeric"):
            vdm.request_delay_bounds(args(request_delay_min_seconds="not-a-number"))
        with self.assertRaisesRegex(ValueError, "request_delay_range_invalid"):
            vdm.request_delay_bounds(args(request_delay_min_seconds=12, request_delay_max_seconds=6))
        with self.assertRaisesRegex(ValueError, "request_delay_range_invalid"):
            vdm.request_delay_bounds(args(request_delay_min_seconds=-1))

    def test_request_gate_persists_jitter_between_independent_calls(self) -> None:
        clock = FakeClock(100)
        response = {"status": "ok", "data": {"operations": [{"status": "ok"}]}, "warnings": []}
        with tempfile.TemporaryDirectory() as directory, patch.object(vdm, "invoke_provider", return_value=response) as invoke:
            project = Path(directory)
            operation = {"op": "list_posts", "uid": "100"}
            vdm.invoke_provider_serialized(project, "bilibili", ["provider"], operation, (6, 12), clock=clock.now, sleeper=clock.sleep, jitter=lambda _low, _high: 7)
            vdm.invoke_provider_serialized(project, "bilibili", ["provider"], operation, (6, 12), clock=clock.now, sleeper=clock.sleep, jitter=lambda _low, _high: 7)
            state = json.loads((project / ".vlog-demand-miner" / "provider-request-gate.json").read_text(encoding="utf-8"))
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(clock.sleeps, [7])
        self.assertEqual(state["revision"], vdm.ACQUISITION_POLICY_REVISION)
        self.assertEqual(state["platforms"]["bilibili"]["last_completed_at"], 107)

    def test_provider_operations_are_submitted_one_at_a_time_in_order(self) -> None:
        seen: list[str] = []

        def fake_invoke(_command, plan):
            payload = json.loads(plan.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["operations"]), 1)
            operation = payload["operations"][0]
            seen.append(operation["op"])
            return {"status": "ok", "data": {"operations": [{"op": operation["op"], "status": "ok"}]}, "warnings": []}

        with tempfile.TemporaryDirectory() as directory, patch.object(vdm, "invoke_provider", side_effect=fake_invoke):
            project = Path(directory)
            vdm.connect(project).close()
            result = vdm.run_provider(
                project,
                "bilibili",
                args(request_delay_min_seconds=0, request_delay_max_seconds=0),
                [{"op": "fetch_post", "bvid": "BV1"}, {"op": "fetch_comments", "bvid": "BV1"}],
            )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(seen, ["fetch_post", "fetch_comments"])

    def test_policy_is_part_of_sync_task_identity(self) -> None:
        provider_response = {
            "status": "ok",
            "data": {"operations": [{
                "status": "ok",
                "posts": [],
                "coverage": {"requested_limit": 20},
                "warnings": [],
            }]},
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(vdm, "run_provider", return_value=provider_response):
            project = Path(directory)
            db = vdm.connect(project)
            db.execute("INSERT INTO creators VALUES ('creator-1','test',0)")
            db.execute("INSERT INTO accounts VALUES ('account-1','creator-1','bilibili','100',NULL)")
            db.commit()
            result = vdm.do_sync(project, db, "creator-1", 1, "bilibili", args())
            task_input = json.loads(db.execute("SELECT input_json FROM tasks WHERE kind='sync'").fetchone()[0])
            db.close()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(task_input["acquisition_policy"]["revision"], vdm.ACQUISITION_POLICY_REVISION)
        self.assertEqual(task_input["acquisition_policy"]["sync_page_limit"], 1)


if __name__ == "__main__":
    unittest.main()
