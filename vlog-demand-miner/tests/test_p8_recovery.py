from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import importlib.util


CLI = Path(__file__).parents[1] / "scripts" / "vdm.py"
SPEC = importlib.util.spec_from_file_location("vdm_for_p8_test", CLI)
assert SPEC and SPEC.loader
vdm = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(CLI.parent))
SPEC.loader.exec_module(vdm)


def run(project: str, *arguments: str) -> tuple[int, dict]:
    completed = subprocess.run([sys.executable, str(CLI), "--project", project, *arguments], capture_output=True, text=True, check=False)
    return completed.returncode, json.loads(completed.stdout)


def fault(project: str, kind: str, artifact_hash: str | None = None) -> tuple[str, str]:
    db = sqlite3.connect(Path(project) / ".vlog-demand-miner" / "control.db")
    if artifact_hash:
        row = db.execute("SELECT id, artifact_hash FROM tasks WHERE kind=? AND artifact_hash=?", (kind, artifact_hash)).fetchone()
    else:
        row = db.execute("SELECT id, artifact_hash FROM tasks WHERE kind=? ORDER BY updated_at DESC, id DESC LIMIT 1", (kind,)).fetchone()
    assert row is not None
    db.execute("UPDATE tasks SET status='running', artifact_hash=NULL, error_code=NULL WHERE id=?", (row[0],))
    db.commit()
    db.close()
    return str(row[0]), str(row[1])


class P8RecoveryTests(unittest.TestCase):
    def test_commenter_identity_mode_versions_acquisition_without_storing_secret(self) -> None:
        args = type("Args", (), {"commenter_hmac_key_env": "VDM_TEST_COMMENT_HMAC"})()
        previous = os.environ.pop("VDM_TEST_COMMENT_HMAC", None)
        try:
            self.assertEqual(vdm.commenter_identity_mode(args), "unavailable")
            os.environ["VDM_TEST_COMMENT_HMAC"] = "not-written-to-task-input"
            self.assertEqual(vdm.commenter_identity_mode(args), "hmac:VDM_TEST_COMMENT_HMAC")
        finally:
            if previous is None:
                os.environ.pop("VDM_TEST_COMMENT_HMAC", None)
            else:
                os.environ["VDM_TEST_COMMENT_HMAC"] = previous

    def test_e2e_review_acceptance_and_recovery_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            code, demo = run(project, "demo")
            self.assertEqual(code, 0)

            code, first_report = run(project, "report")
            self.assertEqual(code, 0)
            code, review = run(project, "review", "--cluster-id", demo["top_cluster"], "--decision", "accepted_for_research", "--rationale", "可以进入负责人专业调研。", "--traceability", "5", "--clarity", "4", "--actionability", "4")
            self.assertEqual(code, 0)
            self.assertEqual(review["status"], "ok")
            code, reviewed_report = run(project, "report")
            self.assertEqual(code, 0)
            packet = Path(reviewed_report["report_dir"]) / "packet.json"
            before = packet.read_text(encoding="utf-8")

            code, acceptance = run(project, "acceptance")
            self.assertEqual(code, 0)
            self.assertFalse(acceptance["acceptance_ready"])
            self.assertIn("automatic_platforms", {item["criterion"] for item in acceptance["unmet"]})
            self.assertIn("clustered_opportunities", {item["criterion"] for item in acceptance["unmet"]})

            _, normal_cluster_artifact = fault(project, "cluster-score", demo["artifact"])
            code, resumed = run(project, "resume")
            self.assertEqual(code, 0)
            recovered_cluster = next(item for item in resumed["replayed"] if item["kind"] == "cluster-score")
            self.assertEqual(recovered_cluster["status"], "ok")
            self.assertEqual(recovered_cluster["artifact"], normal_cluster_artifact)

            _, normal_report_artifact = fault(project, "report", reviewed_report["artifact"])
            code, resumed = run(project, "resume")
            self.assertEqual(code, 0)
            recovered_report = next(item for item in resumed["replayed"] if item["kind"] == "report")
            self.assertIn(recovered_report["status"], {"ok", "reused"})
            self.assertEqual(recovered_report["artifact"], normal_report_artifact)
            self.assertEqual(packet.read_text(encoding="utf-8"), before)

    def test_evidence_submit_replays_from_immutable_submission_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            code, _ = run(project, "demo")
            self.assertEqual(code, 0)
            _, artifact_hash = fault(project, "evidence-submit")
            code, resumed = run(project, "resume")
            self.assertEqual(code, 0)
            recovered = next(item for item in resumed["replayed"] if item["kind"] == "evidence-submit")
            self.assertEqual(recovered["status"], "ok")
            self.assertEqual(recovered["artifact"], artifact_hash)

    def test_doctor_is_safe_when_local_providers_are_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            code, result = run(project, "--sidecar-url", "http://127.0.0.1:9", "--bilibili-cli", "/not/a/provider", "doctor")
            self.assertEqual(code, 0)
            self.assertFalse(result["healthy"])
            self.assertEqual({(item["platform"], item.get("mode")) for item in result["providers"]}, {("bilibili", "cli"), ("douyin", "sidecar"), ("douyin", "browser")})
            self.assertNotIn("Cookie", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
