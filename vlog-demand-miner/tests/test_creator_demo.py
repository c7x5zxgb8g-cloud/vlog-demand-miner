from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).parents[1] / "scripts" / "vdm.py"
FIXTURE = Path(__file__).parents[1] / "fixtures" / "creator-demo"


class CreatorDemoTests(unittest.TestCase):
    def test_creator_demo_generates_complete_offline_studio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run([sys.executable, str(CLI), "--project", directory, "creator-demo"], capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["opportunities"], 4)
            self.assertTrue(result["demo_data"])
            self.assertEqual(result["ratios"]["saves_per_view"], 0.030685)
            html = Path(result["studio"]).read_text(encoding="utf-8")
            for label in ("发现", "本期文案", "本期复盘", "下一条", "下一期文案", "面试团播公司", "演示数据"):
                self.assertIn(label, html)
            for internal in ("原生 NextTake Content Engine 工作流", "VDM source pack", "Immutable section hash", "CMT-", "OPP-", "L1_demand_signal"):
                self.assertNotIn(internal, html)
            self.assertNotIn("<script>alert", html)

    def test_demo_performance_fixture_contains_no_precomputed_ratios(self) -> None:
        payload = json.loads((FIXTURE / ".nexttake" / "performance.json").read_text(encoding="utf-8"))
        self.assertNotIn("ratios", payload)
        self.assertNotIn("likes_per_view", payload)

    def test_demo_prediction_hash_is_unchanged_by_retro_text(self) -> None:
        prediction = FIXTURE / "predictions" / "2026-07-13_61c7492abf1a_团播收入.md"
        before = prediction.read_text(encoding="utf-8")
        sys.path.insert(0, str(CLI.parent))
        import creator_reports
        first = creator_reports.prediction_section_hash(before)
        second = creator_reports.prediction_section_hash(before + "\n追加复盘，不影响预测段。\n")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
