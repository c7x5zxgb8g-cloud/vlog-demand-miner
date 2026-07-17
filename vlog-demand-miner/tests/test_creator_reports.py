from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import creator_reports  # noqa: E402


class CreatorReportTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, str]:
        candidate = "abc123def456"
        files = {
            ".nexttake/sources/item.json": {"cluster_id": "OPP-X", "supporting_evidence": [{"evidence_id": "e1", "quote_snippet": "<script>alert(1)</script>"}], "limitations": ["单平台"]},
            ".nexttake/opportunities.json": {"opportunities": [{"rank": 1, "cluster_id": "OPP-X", "summary": {"pain_statement": "收入不透明"}, "demand_score": 30, "confidence": 0.5, "maturity": "L1"}]},
            ".nexttake/performance.json": {"views": 1000, "likes": 100, "comments": 20, "shares": 10, "saves": 30, "follows": 5, "captured_at": "2026-07-17", "demo_data": True, "top_comments": ["下一期讲什么"]},
        }
        for relative, value in files.items():
            path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        markdowns = {"scripts/a.md": "# 稿件\n\n**Article ID**: internal\n\n---\n\n正文", "scripts/next.md": "# 下一期标题\n\n**Article ID**: internal-next\n\n---\n\n下一期正文", "predictions/a.md": "# 预测\n\n**Script Path**: internal\n\n## 预测 v1\n不可变\n\n## 复盘\n结果", "videos/a/report.md": "# 复盘\n\nvalidated", "audience.md": "# Persona\n\n求职者", ".nexttake/recommendation.md": "# 下一条\n\n面试清单"}
        for relative, value in markdowns.items():
            path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value, encoding="utf-8")
        link = {"candidate_id": candidate, "source_json": ".nexttake/sources/item.json", "opportunity_index": ".nexttake/opportunities.json", "script_path": "scripts/a.md", "next_script_path": "scripts/next.md", "prediction_path": "predictions/a.md", "report_path": "videos/a/report.md", "audience_path": "audience.md", "recommendation_path": ".nexttake/recommendation.md", "performance_path": ".nexttake/performance.json"}
        path = root / ".nexttake/links" / f"{candidate}.json"; path.parent.mkdir(parents=True); path.write_text(json.dumps(link), encoding="utf-8")
        return root, candidate

    def test_studio_escapes_model_and_comment_html(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, candidate = self.fixture(Path(directory))
            payload = creator_reports.load_studio_payload(root, candidate)
            html = creator_reports.studio_html(payload)
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertIn("演示数据", html)
            self.assertIn("3.00%", html)
            self.assertIn("本期文案", html)
            self.assertIn("下一期文案", html)
            self.assertIn("下一期正文", html)
            self.assertEqual(html.count("data-copy="), 2)
            for internal in ("原生 cheat-on-content 工作流", "VDM source pack", "Immutable section hash", "Article ID", "Script Path", "CMT-", "OPP-", "L1_demand_signal"):
                self.assertNotIn(internal, html)

    def test_script_display_keeps_title_and_body_only(self) -> None:
        result = creator_reports.script_display_markdown("# 标题\n\n**Article ID**: x\n\n---\n\n正文")
        self.assertEqual(result, "# 标题\n\n正文\n")

    def test_prediction_hash_excludes_retro_append(self) -> None:
        before = "# X\n## 预测 v1\nbet\n## 复盘\n"
        after = before + "actual\n"
        self.assertEqual(creator_reports.prediction_section_hash(before), creator_reports.prediction_section_hash(after))

    def test_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(creator_reports.CreatorReportError, "outside_project"):
                creator_reports._project_path(root, "../secret")


if __name__ == "__main__":
    unittest.main()
