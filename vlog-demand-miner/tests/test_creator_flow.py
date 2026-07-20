from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import creator_flow  # noqa: E402


class CreatorFlowTests(unittest.TestCase):
    def opportunity(self) -> dict:
        return {
            "nexttake_schema_version": "1.0.0", "cluster_id": "OPP-TEST", "candidate_id": "abc123def456",
            "title": "团播新人不知道真实收入结构", "source": "research:vdm", "source_url": "vdm://test",
            "audience_problem": "团播新人不知道真实收入结构", "job_to_be_done": "判断是否入行", "context": "求职前",
            "demand_score": 70.0, "confidence": 0.7, "maturity": "L2", "coverage": {},
            "supporting_evidence": [{"evidence_id": "e1", "quote_snippet": "真实收入是多少", "channel": "comment", "claim_type": "question", "source_pointer": {}}],
            "counter_evidence": [], "limitations": ["仍需验证"], "source_cluster_artifact": "b" * 64,
            "opportunity_artifact": "a" * 64,
        }

    def test_creator_init_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(creator_flow.CreatorFlowError, "creator_init_required"):
                creator_flow.write_opportunity(Path(directory), self.opportunity(), "2026-07-17")

    def test_writes_native_candidate_source_and_link_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".nexttake-state.json").write_text("{}\n", encoding="utf-8")
            first = creator_flow.write_opportunity(project, self.opportunity(), "2026-07-17")
            second = creator_flow.write_opportunity(project, self.opportunity(), "2026-07-17")
            candidates = (project / "candidates.md").read_text(encoding="utf-8")
            self.assertEqual(candidates.count("<!-- nexttake:abc123def456:start -->"), 1)
            self.assertEqual(first["source_pack"], second["source_pack"])
            self.assertEqual(first["next_action"]["action"], "generate_current_draft")
            link = json.loads(Path(first["link_file"]).read_text(encoding="utf-8"))
            self.assertIsNone(link["script_path"])
            self.assertEqual(link["opportunity_artifact"], "a" * 64)

    def test_attach_registers_native_files_and_copies_only_raw_performance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".nexttake-state.json").write_text("{}\n", encoding="utf-8")
            creator_flow.write_opportunity(project, self.opportunity(), "2026-07-17")
            paths = {}
            for field, relative in {"script_path": "scripts/a.md", "next_script_path": "scripts/next.md", "prediction_path": "predictions/a.md", "report_path": "videos/a/report.md", "audience_path": "audience.md", "recommendation_path": ".nexttake/recommendation.md"}.items():
                target = project / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(f"# {field}\n", encoding="utf-8"); paths[field] = relative
            performance = project.parent / "performance.json"
            performance.write_text(json.dumps({"views": 100, "captured_at": "2026-07-17", "top_comments": []}), encoding="utf-8")
            result = creator_flow.attach_lifecycle(project, "abc123def456", performance_file=str(performance), **paths)
            copied = json.loads((project / result["performance_path"]).read_text(encoding="utf-8"))
            self.assertNotIn("ratios", copied)
            self.assertEqual(result["script_path"], "scripts/a.md")
            self.assertEqual(result["next_script_path"], "scripts/next.md")

    def test_reprepare_does_not_erase_attached_lifecycle_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".nexttake-state.json").write_text("{}\n", encoding="utf-8")
            first = creator_flow.write_opportunity(project, self.opportunity(), "2026-07-17")
            link_path = Path(first["link_file"])
            link = json.loads(link_path.read_text(encoding="utf-8")); link["script_path"] = "scripts/existing.md"; link_path.write_text(json.dumps(link), encoding="utf-8")
            creator_flow.write_opportunity(project, self.opportunity(), "2026-07-17")
            self.assertEqual(json.loads(link_path.read_text(encoding="utf-8"))["script_path"], "scripts/existing.md")


if __name__ == "__main__":
    unittest.main()
