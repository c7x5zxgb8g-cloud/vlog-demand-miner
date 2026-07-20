"""Pure contracts between VDM evidence and the NextTake creator workflow.

This module deliberately does not generate drafts, score content, predict
performance, or run retros. Those capabilities belong to the internal content
engine and are exposed only through NextTake actions.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


SCHEMA_VERSION = "1.0.0"
SOURCE = "research:vdm"
PERFORMANCE_FIELDS = {
    "views", "likes", "comments", "shares", "saves", "follows",
    "completion_rate", "top_comments", "captured_at", "demo_data",
}


class ContentError(ValueError):
    """A validation failure safe to return from the CLI."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def candidate_id(source: str, title: str, url: str | None = None) -> str:
    """Use the content engine's stable candidate ID algorithm."""
    normalized_title = "".join(title.strip().lower().split())
    clean_url = url.split("?", 1)[0].rstrip("/") if url else ""
    raw = f"{source.split(':', 1)[0]}|{normalized_title}|{clean_url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _text(value: Any, field: str, *, required: bool = False, limit: int = 2_000) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ContentError(f"invalid_{field}")
    value = value.strip()
    if required and not value:
        raise ContentError(f"missing_{field}")
    if len(value) > limit:
        raise ContentError(f"too_long_{field}")
    return value


def _evidence(cluster: dict[str, Any], atoms: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    atom_map = {str(atom.get("evidence_id")): atom for atom in atoms if isinstance(atom, dict) and atom.get("evidence_id")}
    values = cluster.get(field)
    if not isinstance(values, list):
        raise ContentError(f"invalid_{field}")
    result = []
    for evidence_id in values:
        atom = atom_map.get(str(evidence_id))
        if not atom:
            raise ContentError("cluster_evidence_not_found")
        result.append({
            "evidence_id": str(evidence_id),
            "channel": str(atom.get("channel") or ""),
            "claim_type": str(atom.get("claim_type") or ""),
            "quote_snippet": _text(atom.get("quote_snippet"), "quote_snippet", required=True, limit=500),
            "source_pointer": atom.get("source_pointer") if isinstance(atom.get("source_pointer"), dict) else {},
        })
    return result


def coverage_limitations(cluster: dict[str, Any]) -> list[str]:
    coverage = cluster.get("coverage") if isinstance(cluster.get("coverage"), dict) else {}
    limitations = []
    if len(coverage.get("platforms") or []) < 2:
        limitations.append("当前信号未形成跨平台验证。")
    if int(coverage.get("independent_creators") or 0) < 3:
        limitations.append("独立创作者覆盖少于 3 个，可能受单一账号表达影响。")
    if int(coverage.get("independent_commenters") or 0) < 5:
        limitations.append("独立评论者少于 5 个，评论需求信号仍偏早期。")
    if int(coverage.get("distinct_posts") or 0) < 5:
        limitations.append("作品覆盖少于 5 条，不代表整个赛道的稳定规律。")
    if not cluster.get("counter_evidence_ids"):
        limitations.append("当前没有捕获到明确反证，不等于不存在反对意见。")
    return limitations or ["该机会仍是内容假设，不是市场事实或流量承诺。"]


def build_opportunity(cluster_artifact: str, cluster: dict[str, Any], atoms: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(cluster, dict):
        raise ContentError("invalid_cluster")
    cluster_id = _text(cluster.get("cluster_id"), "cluster_id", required=True, limit=100)
    summary = cluster.get("summary") if isinstance(cluster.get("summary"), dict) else {}
    title = _text(summary.get("pain_statement"), "pain_statement", required=True, limit=180)
    score = cluster.get("demand_score")
    confidence = cluster.get("confidence")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= float(score) <= 100:
        raise ContentError("invalid_demand_score")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= float(confidence) <= 1:
        raise ContentError("invalid_confidence")
    url = f"vdm://artifact/{cluster_artifact}/cluster/{cluster_id}"
    supporting = _evidence(cluster, atoms, "supporting_evidence_ids")
    counter = _evidence(cluster, atoms, "counter_evidence_ids")
    if not supporting:
        raise ContentError("supporting_evidence_required")
    return {
        "nexttake_schema_version": SCHEMA_VERSION,
        "cluster_id": cluster_id,
        "candidate_id": candidate_id(SOURCE, title, url),
        "title": title,
        "source": SOURCE,
        "source_url": url,
        "audience_problem": title,
        "job_to_be_done": _text(summary.get("job_to_be_done"), "job_to_be_done", limit=500),
        "context": _text(summary.get("context"), "context", limit=500),
        "demand_score": round(float(score), 1),
        "confidence": round(float(confidence), 3),
        "maturity": _text(cluster.get("maturity"), "maturity", required=True, limit=100),
        "coverage": cluster.get("coverage") if isinstance(cluster.get("coverage"), dict) else {},
        "supporting_evidence": supporting,
        "counter_evidence": counter,
        "limitations": coverage_limitations(cluster),
        "source_cluster_artifact": cluster_artifact,
    }


def source_snapshot(opportunity: dict[str, Any]) -> str:
    lines = [
        f"受众问题：{opportunity['audience_problem']}",
        f"想完成的任务：{opportunity['job_to_be_done'] or '尚未明确'}",
        f"发生场景：{opportunity['context'] or '尚未明确'}",
        f"需求分：{opportunity['demand_score']}/100；置信度：{opportunity['confidence']}；成熟度：{opportunity['maturity']}",
        "支持证据：",
    ]
    lines.extend(f"- [{item['evidence_id']}] {item['quote_snippet']}" for item in opportunity["supporting_evidence"])
    lines.append("反证：")
    lines.extend(f"- [{item['evidence_id']}] {item['quote_snippet']}" for item in opportunity["counter_evidence"])
    if not opportunity["counter_evidence"]:
        lines.append("- 当前没有捕获到明确反证。")
    lines.append("限制：")
    lines.extend(f"- {item}" for item in opportunity["limitations"])
    return "\n".join(lines)


def source_pack_markdown(opportunity: dict[str, Any]) -> str:
    snapshot = source_snapshot(opportunity)
    return (
        f"# NextTake Source Pack - {opportunity['title']}\n\n"
        f"- Candidate ID: `{opportunity['candidate_id']}`\n"
        f"- Cluster: `{opportunity['cluster_id']}`\n"
        f"- Opportunity Artifact: `{opportunity.get('opportunity_artifact', 'pending')}`\n"
        f"- Source Cluster Artifact: `{opportunity['source_cluster_artifact']}`\n"
        f"- Source: `{opportunity['source']}`\n\n"
        "## NextTake Draft Context\n\n"
        "Use this source pack as evidence for topic discussion and draft generation. "
        "Keep factual claims tied to the listed Evidence IDs. Mark creator opinions or experiences as creator-original. "
        "Do not turn the demand score into a traffic promise.\n\n"
        f"## Evidence Snapshot\n\n{snapshot}\n"
    )


def candidate_markdown(opportunity: dict[str, Any], source_pack_path: str, snapshot_at: str) -> str:
    snapshot = source_snapshot(opportunity)
    return (
        f"### {opportunity['title']}\n\n"
        f"- **id**: {opportunity['candidate_id']}\n"
        f"- **source**: {opportunity['source']}\n"
        f"- **snapshot_at**: {snapshot_at}\n"
        "- **read_status**: deep_read\n"
        f"- **category**: {opportunity['cluster_id']}\n"
        f"- **note**: VDM demand score {opportunity['demand_score']}/100; source pack `{source_pack_path}`\n\n"
        + "\n".join(f"> {line}" if line else ">" for line in snapshot.splitlines())
        + "\n"
    )


def validate_performance(payload: Any) -> dict[str, Any]:
    """Validate raw metrics for NextTake retro and compute deterministic ratios."""
    if not isinstance(payload, dict) or set(payload) - PERFORMANCE_FIELDS:
        raise ContentError("invalid_performance_payload")
    values: dict[str, Any] = {}
    for field in ("views", "likes", "comments", "shares", "saves", "follows"):
        value = payload.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ContentError(f"invalid_{field}")
        values[field] = value
    if values["views"] <= 0:
        raise ContentError("views_must_be_positive")
    completion = payload.get("completion_rate")
    if completion is not None and (not isinstance(completion, (int, float)) or isinstance(completion, bool) or not 0 <= float(completion) <= 1):
        raise ContentError("invalid_completion_rate")
    values["completion_rate"] = None if completion is None else round(float(completion), 6)
    raw_comments = payload.get("top_comments", [])
    if not isinstance(raw_comments, list) or len(raw_comments) > 30:
        raise ContentError("invalid_top_comments")
    comments = []
    for raw in raw_comments:
        text = _text(raw if isinstance(raw, str) else raw.get("text") if isinstance(raw, dict) else None, "comment", required=True, limit=500)
        comments.append({"comment_id": f"CMT-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12].upper()}", "text": text})
    values["top_comments"] = comments
    values["captured_at"] = _text(payload.get("captured_at"), "captured_at", required=True, limit=64)
    values["demo_data"] = bool(payload.get("demo_data", False))
    values["ratios"] = {
        "likes_per_view": round(values["likes"] / values["views"], 6),
        "comments_per_view": round(values["comments"] / values["views"], 6),
        "shares_per_view": round(values["shares"] / values["views"], 6),
        "saves_per_view": round(values["saves"] / values["views"], 6),
        "follows_per_view": round(values["follows"] / values["views"], 6),
    }
    return values
