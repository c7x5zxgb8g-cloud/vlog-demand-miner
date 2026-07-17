from __future__ import annotations

import unittest

import sys
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import content  # noqa: E402


class ContentTests(unittest.TestCase):
    def opportunity(self) -> dict:
        cluster = {
            "cluster_id": "OPP-TEST",
            "demand_score": 72.5,
            "confidence": 0.73,
            "maturity": "L2_high_confidence_signal",
            "coverage": {"platforms": ["douyin"], "independent_creators": 2, "independent_commenters": 3, "distinct_posts": 3},
            "summary": {"pain_statement": "团播新人不知道真实收入结构", "job_to_be_done": "判断是否进入团播行业", "context": "求职前"},
            "supporting_evidence_ids": ["e1"],
            "counter_evidence_ids": ["e2"],
        }
        atoms = [
            {"evidence_id": "e1", "channel": "comment", "claim_type": "solution_seeking", "quote_snippet": "到底能赚多少", "source_pointer": {}},
            {"evidence_id": "e2", "channel": "comment", "claim_type": "counter_evidence", "quote_snippet": "收入主要看个人", "source_pointer": {}},
        ]
        return content.build_opportunity("a" * 64, cluster, atoms)

    def test_candidate_id_matches_upstream_normalization(self) -> None:
        first = content.candidate_id("research:vdm", "Hello World", "https://x.test/a?utm=1")
        second = content.candidate_id("research:other", "helloworld", "https://x.test/a")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 12)

    def test_opportunity_keeps_support_counter_and_limitations(self) -> None:
        result = self.opportunity()
        self.assertEqual(result["supporting_evidence"][0]["evidence_id"], "e1")
        self.assertEqual(result["counter_evidence"][0]["evidence_id"], "e2")
        self.assertIn("跨平台", "".join(result["limitations"]))
        self.assertEqual(result["source_cluster_artifact"], "a" * 64)

    def test_unknown_cluster_evidence_is_rejected(self) -> None:
        opportunity = self.opportunity()
        self.assertIn("Evidence IDs", content.source_pack_markdown(opportunity))
        cluster = {
            "cluster_id": "OPP-X", "demand_score": 1, "confidence": 0.1, "maturity": "L1",
            "coverage": {}, "summary": {"pain_statement": "x"},
            "supporting_evidence_ids": ["missing"], "counter_evidence_ids": [],
        }
        with self.assertRaisesRegex(content.ContentError, "cluster_evidence_not_found"):
            content.build_opportunity("b" * 64, cluster, [])

    def test_performance_is_raw_and_ratios_are_recomputed(self) -> None:
        result = content.validate_performance({
            "views": 1000, "likes": 100, "comments": 20, "shares": 10,
            "saves": 30, "follows": 5, "captured_at": "2026-07-17T12:00:00+08:00",
            "top_comments": ["下一期讲讲筛选标准"],
        })
        self.assertEqual(result["ratios"]["saves_per_view"], 0.03)
        self.assertTrue(result["top_comments"][0]["comment_id"].startswith("CMT-"))

    def test_zero_views_and_identity_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(content.ContentError, "views_must_be_positive"):
            content.validate_performance({"views": 0, "captured_at": "2026-07-17"})
        with self.assertRaisesRegex(content.ContentError, "invalid_performance_payload"):
            content.validate_performance({"views": 1, "captured_at": "2026-07-17", "user_id": "secret"})


if __name__ == "__main__":
    unittest.main()
