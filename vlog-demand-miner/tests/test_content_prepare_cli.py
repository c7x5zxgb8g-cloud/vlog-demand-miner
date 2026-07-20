from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).parents[1] / "scripts" / "vdm.py"


def run(project: Path, *arguments: str) -> tuple[int, dict]:
    completed = subprocess.run([sys.executable, str(CLI), "--project", str(project), *arguments], capture_output=True, text=True, check=False)
    return completed.returncode, json.loads(completed.stdout)


class ContentPrepareCliTests(unittest.TestCase):
    def test_content_prepare_bridges_cluster_into_native_candidate_pool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            research = root / "research"
            creator = root / "creator"
            creator.mkdir()
            (creator / ".nexttake-state.json").write_text("{}\n", encoding="utf-8")
            code, demo = run(research, "demo")
            self.assertEqual(code, 0)
            code, prepared = run(research, "content-prepare", "--cluster-id", demo["top_cluster"], "--creator-project", str(creator), "--snapshot-at", "2026-07-17")
            self.assertEqual(code, 0, prepared)
            self.assertEqual(prepared["status"], "ok")
            self.assertTrue(Path(prepared["source_pack"]).is_file())
            self.assertIn(prepared["candidate_id"], (creator / "candidates.md").read_text(encoding="utf-8"))
            code, reused = run(research, "content-prepare", "--cluster-id", demo["top_cluster"], "--creator-project", str(creator), "--snapshot-at", "2026-07-17")
            self.assertEqual(code, 0)
            self.assertEqual(reused["status"], "reused")
            self.assertEqual((creator / "candidates.md").read_text(encoding="utf-8").count(f"nexttake:{prepared['candidate_id']}:start"), 1)

    def test_content_prepare_requires_creator_init(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            research = root / "research"
            creator = root / "creator"
            creator.mkdir()
            _, demo = run(research, "demo")
            code, prepared = run(research, "content-prepare", "--cluster-id", demo["top_cluster"], "--creator-project", str(creator))
            self.assertEqual(code, 2)
            self.assertEqual(prepared["error"], "creator_init_required")
            self.assertEqual(prepared["next_action"]["action"], "initialize_creator_project")
            self.assertNotIn("cheat", json.dumps(prepared, ensure_ascii=False).casefold())

    def test_prepare_attach_and_studio_form_a_complete_cli_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            research = root / "research"
            creator = root / "creator"
            creator.mkdir()
            (creator / ".nexttake-state.json").write_text("{}\n", encoding="utf-8")
            _, demo = run(research, "demo")
            code, prepared = run(research, "content-prepare", "--cluster-id", demo["top_cluster"], "--creator-project", str(creator))
            self.assertEqual(code, 0)
            candidate = prepared["candidate_id"]
            files = {
                "script": "scripts/a.md",
                "prediction": "predictions/a.md",
                "report": "videos/a/report.md",
                "audience": "audience.md",
                "recommendation": ".nexttake/recommendation.md",
                "next_script": "scripts/next.md",
            }
            contents = {
                "script": "# Draft\n\nBody",
                "prediction": "# Prediction\n\n## 预测 v1\nBlind bet\n\n## 复盘\nPending",
                "report": "# Retro\n\nvalidated",
                "audience": "# Audience\n\nEarly signal",
                "recommendation": "# Next\n\nDo the follow-up",
                "next_script": "# Next draft\n\n---\n\nSecond copy",
            }
            for key, relative in files.items():
                target = creator / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(contents[key], encoding="utf-8")
            performance = root / "performance.json"
            performance.write_text(json.dumps({"views": 1000, "likes": 100, "comments": 20, "shares": 10, "saves": 30, "follows": 5, "captured_at": "2026-07-17", "top_comments": ["next"]}), encoding="utf-8")
            code, attached = run(
                research, "creator-attach", "--creator-project", str(creator), "--candidate-id", candidate,
                "--script-path", files["script"], "--prediction-path", files["prediction"], "--report-path", files["report"],
                "--performance-file", str(performance), "--audience-path", files["audience"], "--recommendation-path", files["recommendation"],
                "--next-script-path", files["next_script"],
            )
            self.assertEqual(code, 0, attached)
            code, studio = run(research, "creator-studio", "--creator-project", str(creator), "--candidate-id", candidate)
            self.assertEqual(code, 0, studio)
            self.assertEqual(studio["ratios"]["saves_per_view"], 0.03)
            self.assertTrue(Path(studio["studio"]).is_file())
            self.assertIn("Second copy", Path(studio["studio"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
