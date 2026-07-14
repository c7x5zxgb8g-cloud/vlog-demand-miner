"""Deterministic, privacy-preserving Markdown and HTML review-packet renderer."""
from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any


def coverage_diagnostic(atoms: list[dict[str, Any]]) -> dict[str, Any]:
    platforms = sorted({str(atom.get("platform")) for atom in atoms if atom.get("platform") and atom.get("platform") != "offline-demo"})
    posts = {str(atom.get("post_id")) for atom in atoms if atom.get("post_id")}
    reasons = []
    if len(platforms) < 2: reasons.append("requires_at_least_two_automatic_platforms")
    if len(posts) < 40: reasons.append("requires_at_least_40_effective_posts")
    return {"formal_eligible": not reasons, "platforms": platforms, "effective_posts": len(posts), "reasons": reasons}


def _time(ms: int) -> str:
    seconds = max(0, int(ms // 1000))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def public_evidence(atom: dict[str, Any]) -> dict[str, Any]:
    source = str(atom.get("source_id") or "")
    if atom.get("channel") == "transcript":
        reference = f"{source} @ {_time(int(atom.get('start_ms') or 0))}-{_time(int(atom.get('end_ms') or 0))}"
    else:
        reference = f"{source} (anonymous comment snapshot)"
    return {"evidence_id": atom["evidence_id"], "reference": reference, "channel": atom["channel"], "claim_type": atom["claim_type"], "quote_snippet": atom["quote_snippet"]}


def packet_payload(clusters: list[dict[str, Any]], atoms: list[dict[str, Any]], reviews: dict[str, dict[str, Any]], *, requested_formal: bool) -> dict[str, Any]:
    atom_map = {str(atom["evidence_id"]): atom for atom in atoms if atom.get("evidence_id")}
    visible = []
    for rank, cluster in enumerate(clusters[:10], 1):
        supporting = [public_evidence(atom_map[item]) for item in cluster.get("supporting_evidence_ids", []) if item in atom_map]
        counter = [public_evidence(atom_map[item]) for item in cluster.get("counter_evidence_ids", []) if item in atom_map]
        visible.append({**cluster, "rank": rank, "supporting_evidence": supporting, "counter_evidence": counter, "review": reviews.get(cluster["cluster_id"])})
    coverage = coverage_diagnostic(atoms)
    return {"report_schema_version": "1.0.0", "requested_formal": requested_formal, "report_type": "formal" if requested_formal and coverage["formal_eligible"] else "provisional", "coverage": coverage, "opportunities": visible, "top_five": [item["cluster_id"] for item in visible[:5]], "notice": "This packet identifies demand hypotheses for professional market research. It does not establish a market, willingness to pay, or product viability."}


def opportunity_markdown(item: dict[str, Any]) -> str:
    summary = item["summary"]
    coverage = item["coverage"]
    lines = [
        f"# {item['cluster_id']} - {summary['pain_statement']}", "",
        item["warning"], "",
        "## Candidate", f"- Rank: {item['rank']}", f"- Demand score: {item['demand_score']}/100", f"- Confidence: {item['confidence']}", f"- Evidence maturity: {item['maturity']}", "",
        "## User Context", f"- Job to be done: {summary['job_to_be_done'] or 'Not yet specific'}", f"- Context: {summary['context'] or 'Not yet specific'}", "",
        "## Coverage", f"- Independent creators: {coverage['independent_creators']}", f"- Distinct posts: {coverage['distinct_posts']}", f"- Independent commenters: {coverage['independent_commenters']}", f"- Platforms: {', '.join(coverage['platforms'])}", "",
        "## Supporting Evidence",
    ]
    lines.extend([f"- [{entry['evidence_id']}] {entry['reference']}: {entry['quote_snippet']}" for entry in item["supporting_evidence"]] or ["- None"])
    lines += ["", "## Counter Evidence"]
    lines.extend([f"- [{entry['evidence_id']}] {entry['reference']}: {entry['quote_snippet']}" for entry in item["counter_evidence"]] or ["- None captured"])
    lines += ["", "## Score Dimensions"]
    lines.extend([f"- {key}: {value}" for key, value in item["score_dimensions"].items()])
    lines += [f"- Source concentration penalty: {item['penalties']['source_concentration']}", "", "## Reviewer Decision"]
    if item.get("review"):
        review = item["review"]
        lines += [f"- Decision: {review['decision']}", f"- Rationale: {review['rationale']}", f"- Scores: traceability {review['scores']['traceability']}/5, clarity {review['scores']['clarity']}/5, actionability {review['scores']['actionability']}/5"]
    else:
        lines.append("- Pending")
    return "\n".join(lines) + "\n"


def executive_markdown(payload: dict[str, Any]) -> str:
    coverage = payload["coverage"]
    heading = "# Market Demand Review Packet" if payload["report_type"] == "formal" else "# Provisional Market Demand Review Packet"
    lines = [heading, "", payload["notice"], "", "## Coverage", f"- Platforms: {', '.join(coverage['platforms']) or 'none'}", f"- Effective posts: {coverage['effective_posts']}", f"- Formal eligibility: {'yes' if coverage['formal_eligible'] else 'no'}"]
    if coverage["reasons"]:
        lines += ["- Formal-report blockers:"] + [f"  - {reason}" for reason in coverage["reasons"]]
    lines += ["", "## Ranked Candidates"]
    for item in payload["opportunities"]:
        review = (item.get("review") or {}).get("decision", "pending")
        lines.append(f"{item['rank']}. {item['cluster_id']} | score {item['demand_score']} | confidence {item['confidence']} | {item['maturity']} | review: {review}")
    return "\n".join(lines) + "\n"


def html_packet(payload: dict[str, Any]) -> str:
    coverage = payload["coverage"]
    cards = []
    for item in payload["opportunities"]:
        evidence = "".join(f"<li><code>{escape(entry['reference'])}</code><br>{escape(entry['quote_snippet'])}</li>" for entry in item["supporting_evidence"]) or "<li>None</li>"
        counter = "".join(f"<li><code>{escape(entry['reference'])}</code><br>{escape(entry['quote_snippet'])}</li>" for entry in item["counter_evidence"]) or "<li>None captured</li>"
        review = item.get("review")
        review_html = f"<p><strong>Review:</strong> {escape(review['decision'])}<br>{escape(review['rationale'])}</p>" if review else "<p><strong>Review:</strong> pending</p>"
        cards.append(f"<article><h2>{item['rank']}. {escape(item['cluster_id'])}</h2><p>{escape(item['summary']['pain_statement'])}</p><dl><dt>Demand score</dt><dd>{item['demand_score']}/100</dd><dt>Confidence</dt><dd>{item['confidence']}</dd><dt>Maturity</dt><dd>{escape(item['maturity'])}</dd><dt>Coverage</dt><dd>{item['coverage']['independent_creators']} creators, {item['coverage']['distinct_posts']} posts, {item['coverage']['independent_commenters']} commenters</dd></dl><h3>Supporting evidence</h3><ul>{evidence}</ul><h3>Counter evidence</h3><ul>{counter}</ul>{review_html}</article>")
    blockers = "".join(f"<li>{escape(reason)}</li>" for reason in coverage["reasons"]) or "<li>None</li>"
    return f"<!doctype html><html lang='en'><meta charset='utf-8'><title>Demand Review Packet</title><style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:960px;margin:40px auto;padding:0 20px;background:#f6f7f8;color:#1d252c}}article{{background:#fff;border:1px solid #d9dee3;border-radius:6px;padding:22px;margin:18px 0}}h1,h2,h3{{margin-top:0}}dl{{display:grid;grid-template-columns:150px 1fr;gap:8px 14px}}dt{{font-weight:650}}dd{{margin:0}}code{{font-size:12px;color:#42606f}}li{{margin:8px 0}}.notice{{border-left:4px solid #b45309;padding-left:12px}}</style><main><h1>{'Formal' if payload['report_type'] == 'formal' else 'Provisional'} Demand Review Packet</h1><p class='notice'>{escape(payload['notice'])}</p><h2>Coverage</h2><p>Platforms: {escape(', '.join(coverage['platforms']) or 'none')} | Effective posts: {coverage['effective_posts']} | Formal eligible: {'yes' if coverage['formal_eligible'] else 'no'}</p><ul>{blockers}</ul>{''.join(cards)}</main></html>"


def write_packet(directory: Path, payload: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        directory / "executive-summary.md": executive_markdown(payload),
        directory / "review-packet.html": html_packet(payload),
        directory / "packet.json": json.dumps(payload, ensure_ascii=False, indent=2),
    }
    # Packet directories are named by their content hash.  A resumed task may
    # finish a database update after its files were written, but it must not
    # mutate a completed packet that already has the same identity.
    for path, content in files.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    opportunity_dir = directory / "opportunities"
    opportunity_dir.mkdir(exist_ok=True)
    for item in payload["opportunities"]:
        path = opportunity_dir / f"{item['cluster_id']}.md"
        if not path.exists():
            path.write_text(opportunity_markdown(item), encoding="utf-8")
