from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).parents[1] / "scripts" / "vdm.py"


def run(project: str, *arguments: str) -> tuple[int, dict]:
    completed = subprocess.run([sys.executable, str(CLI), "--project", project, *arguments], capture_output=True, text=True, check=False)
    return completed.returncode, json.loads(completed.stdout)


class ReportTests(unittest.TestCase):
    def test_provisional_packet_review_and_formal_gate(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            code, demo = run(project, "demo")
            self.assertEqual(code, 0)
            code, draft = run(project, "report")
            self.assertEqual(code, 0)
            self.assertEqual(draft["report_type"], "provisional")
            report_dir = Path(draft["report_dir"])
            self.assertTrue((report_dir / "executive-summary.md").is_file())
            self.assertTrue((report_dir / "review-packet.html").is_file())
            self.assertTrue((report_dir / "opportunities" / f"{demo['top_cluster']}.md").is_file())
            packet = (report_dir / "packet.json").read_text(encoding="utf-8")
            self.assertNotIn("demo-C:", packet)
            self.assertNotIn("commenter_id", packet)

            code, review = run(project, "review", "--cluster-id", demo["top_cluster"], "--decision", "accepted_for_research", "--rationale", "证据可追溯，建议进入专业调研。", "--traceability", "5", "--clarity", "4", "--actionability", "4")
            self.assertEqual(code, 0)
            self.assertEqual(review["decision"], "accepted_for_research")
            code, reviewed = run(project, "report")
            self.assertEqual(code, 0)
            reviewed_packet = json.loads((Path(reviewed["report_dir"]) / "packet.json").read_text(encoding="utf-8"))
            self.assertEqual(reviewed_packet["opportunities"][0]["review"]["decision"], "accepted_for_research")

            code, blocked = run(project, "report", "--formal")
            self.assertEqual(code, 2)
            self.assertEqual(blocked["status"], "coverage_insufficient")
            self.assertEqual(blocked["error"], "E-ACQUISITION-COVERAGE-001")
            self.assertTrue((Path(blocked["report_dir"]) / "executive-summary.md").is_file())


if __name__ == "__main__":
    unittest.main()
