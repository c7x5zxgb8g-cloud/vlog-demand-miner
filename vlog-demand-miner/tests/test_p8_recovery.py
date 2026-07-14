from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).parents[1] / "scripts" / "vdm.py"


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
            self.assertEqual({item["platform"] for item in result["providers"]}, {"bilibili", "douyin"})
            self.assertNotIn("Cookie", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
