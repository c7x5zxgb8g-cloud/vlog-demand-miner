#!/usr/bin/env python3
"""P3 CLI for the Vlog Demand Miner validation workflow.

The control plane owns project state and immutable artifacts. Platform bridges
own acquisition, and are always invoked serially within their platform.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import analysis
import content
import creator_flow
import creator_reports
import reports

SCHEMA_VERSION = "1.0.0"
ROOT_NAME = ".vlog-demand-miner"
PROVIDERS = {
    "douyin": Path(__file__).parent / "providers" / "douyin_sidecar.py",
    "bilibili": Path(__file__).parent / "providers" / "bilibili_cli.py",
}
DOUYIN_BROWSER_PROVIDER = Path(__file__).parent / "providers" / "douyin_browser.py"
DOUYIN_FALLBACK_STATUSES = {
    "sidecar_unavailable", "sidecar_http_error", "provider_protocol_error",
    "blocked_auth", "blocked_verification", "risk_control", "schema_drift",
    "anomalous_empty_result",
}
DOUYIN_PROVIDER_REVISION = "nexttake-douyin-browser-v1"
ACQUISITION_POLICY_REVISION = "serial-low-page-jitter-v1"
DEFAULT_REQUEST_DELAY_MIN_SECONDS = 6.0
DEFAULT_REQUEST_DELAY_MAX_SECONDS = 12.0
SKILL_ROOT = Path(__file__).resolve().parents[1]
CONTENT_ENGINE_ROOT = Path(
    os.getenv("NEXTTAKE_CONTENT_ENGINE_ROOT")
    or str(SKILL_ROOT / "vendor" / "content-engine")
).expanduser().resolve()
VENDORED_DOUYIN_ADAPTER = CONTENT_ENGINE_ROOT / "adapters" / "perf-data" / "douyin-session"


def now() -> int: return int(time.time())
def jid() -> str: return uuid.uuid4().hex[:12]
def dump(value: Any) -> str: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def digest(value: Any) -> str: return hashlib.sha256(dump(value).encode()).hexdigest()
def paths(project: Path) -> tuple[Path, Path, Path]:
    root = project / ROOT_NAME
    return root, root / "control.db", root / "artifacts"


def connect(project: Path) -> sqlite3.Connection:
    root, database, _ = paths(project)
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    db.executescript("""
      PRAGMA journal_mode=WAL;
      PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS creators (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, creator_id TEXT NOT NULL, platform TEXT NOT NULL, platform_account_id TEXT NOT NULL, credential_ref TEXT, UNIQUE(platform, platform_account_id));
      CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, creator_id TEXT NOT NULL, platform TEXT NOT NULL, platform_post_id TEXT NOT NULL, title TEXT, published_at INTEGER, content_type TEXT, metrics_json TEXT NOT NULL, selected INTEGER NOT NULL DEFAULT 0, UNIQUE(platform, platform_post_id));
      CREATE TABLE IF NOT EXISTS artifacts (hash TEXT PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL, created_at INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, kind TEXT NOT NULL, entity_id TEXT NOT NULL, input_hash TEXT NOT NULL, input_json TEXT NOT NULL, status TEXT NOT NULL, artifact_hash TEXT, error_code TEXT, attempts INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL, UNIQUE(kind, entity_id, input_hash));
    """)
    db.commit()
    return db


def artifact(project: Path, db: sqlite3.Connection, kind: str, data: Any) -> str:
    payload = dump({"schema_version": SCHEMA_VERSION, "kind": kind, "data": data})
    value = hashlib.sha256(payload.encode()).hexdigest()
    _, _, store = paths(project)
    target = store / value[:2] / f"{value}.json"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(target)
    db.execute("INSERT OR IGNORE INTO artifacts VALUES (?, ?, ?, ?)", (value, kind, str(target.relative_to(project)), now()))
    return value


def task(db: sqlite3.Connection, kind: str, entity_id: str, inputs: dict[str, Any]) -> sqlite3.Row:
    h = digest(inputs)
    row = db.execute("SELECT * FROM tasks WHERE kind=? AND entity_id=? AND input_hash=?", (kind, entity_id, h)).fetchone()
    if row: return row
    db.execute("INSERT INTO tasks (id,kind,entity_id,input_hash,input_json,status,updated_at) VALUES (?,?,?,?,?,'ready',?)", (jid(), kind, entity_id, h, dump(inputs), now()))
    db.commit()
    return db.execute("SELECT * FROM tasks WHERE kind=? AND entity_id=? AND input_hash=?", (kind, entity_id, h)).fetchone()


def read_artifact(project: Path, value: str) -> dict[str, Any]:
    _, _, store = paths(project)
    target = store / value[:2] / f"{value}.json"
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise analysis.AnalysisError("artifact_not_found")
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise analysis.AnalysisError("artifact_schema_drift")
    return payload


def latest_artifact(db: sqlite3.Connection, kind: str, entity_id: str) -> str | None:
    row = db.execute("SELECT artifact_hash FROM tasks WHERE kind=? AND entity_id=? AND status='succeeded' ORDER BY updated_at DESC LIMIT 1", (kind, entity_id)).fetchone()
    return str(row["artifact_hash"]) if row and row["artifact_hash"] else None


def commit_evidence(project: Path, db: sqlite3.Connection, job_hash: str, evidence_payload: Any) -> dict[str, Any]:
    job = read_artifact(project, job_hash).get("data")
    if not isinstance(job, dict) or job.get("kind") != "analysis.model_job":
        return {"status": "invalid_input", "error": "model_job_required"}
    try:
        atoms = analysis.validate_evidence(job, evidence_payload)
    except analysis.AnalysisError as exc:
        return {"status": "invalid_input", "error": str(exc)}
    # Keep the exact submitted JSON as an immutable artifact so a task that
    # dies after validation can be replayed without asking the model again.
    submission_hash = artifact(project, db, "analysis.evidence_submission", {"job_artifact": job_hash, "payload": evidence_payload})
    inputs = {"job_artifact": job_hash, "evidence_submission_artifact": submission_hash}
    row = task(db, "evidence-submit", job_hash, inputs)
    if row["status"] == "succeeded":
        return {"status": "reused", "task_id": row["id"], "artifact": row["artifact_hash"]}
    db.execute("UPDATE tasks SET status='running',attempts=attempts+1,updated_at=? WHERE id=?", (now(), row["id"])); db.commit()
    capture = artifact(project, db, "analysis.evidence", {"job_artifact": job_hash, "evidence": atoms})
    db.execute("UPDATE tasks SET status='succeeded',artifact_hash=?,error_code=NULL,updated_at=? WHERE id=?", (capture, now(), row["id"])); db.commit()
    return {"status": "ok", "task_id": row["id"], "artifact": capture, "evidence": len(atoms), "channel": job["channel"]}


def do_import_transcript(project: Path, db: sqlite3.Connection, post_id: str, source_file: Path) -> dict[str, Any]:
    post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post: return {"status": "invalid_input", "error": "post_not_found"}
    try:
        payload = json.loads(source_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "invalid_input", "error": "transcript_json_required"}
    segments = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(segments, list) or not segments:
        return {"status": "invalid_input", "error": "transcript_segments_required"}
    clean = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str) or not segment["text"].strip():
            return {"status": "invalid_input", "error": f"invalid_transcript_segment_{index}"}
        start, end = segment.get("start_ms"), segment.get("end_ms")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
            return {"status": "invalid_input", "error": f"invalid_transcript_timing_{index}"}
        clean.append({"start_ms": start, "end_ms": end, "text": segment["text"].strip()[:2_000]})
    inputs = {"post_id": post_id, "segments_hash": digest(clean)}
    row = task(db, "transcript-import", post_id, inputs)
    if row["status"] == "succeeded": return {"status": "reused", "task_id": row["id"], "artifact": row["artifact_hash"]}
    capture = artifact(project, db, "analysis.transcript", {"post_id": post_id, "segments": clean, "source": "external_asr_or_native_import"})
    db.execute("UPDATE tasks SET status='succeeded',artifact_hash=?,error_code=NULL,attempts=attempts+1,updated_at=? WHERE id=?", (capture, now(), row["id"])); db.commit()
    return {"status": "ok", "task_id": row["id"], "artifact": capture, "segments": len(clean)}


def do_prepare_analysis(project: Path, db: sqlite3.Connection, post_id: str) -> dict[str, Any]:
    post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post: return {"status": "invalid_input", "error": "post_not_found"}
    acquire_hash = latest_artifact(db, "acquire", post_id)
    if not acquire_hash: return {"status": "invalid_input", "error": "acquisition_required"}
    try:
        acquisition = read_artifact(project, acquire_hash)
        transcript_hash = latest_artifact(db, "transcript-import", post_id)
        imported = read_artifact(project, transcript_hash).get("data", {}).get("segments") if transcript_hash else None
        sources = analysis.acquisition_sources(acquisition, acquire_hash, dict(post), imported, transcript_hash)
    except analysis.AnalysisError as exc:
        return {"status": "invalid_input", "error": str(exc)}
    jobs = []
    for channel in ("transcript", "comment"):
        if not sources[channel]:
            continue
        job = analysis.make_model_job(channel, dict(post), sources[channel])
        job_hash = artifact(project, db, "analysis.model_job", job)
        inputs = {"post_id": post_id, "channel": channel, "acquisition_artifact": acquire_hash, "transcript_artifact": transcript_hash}
        row = task(db, "model-job", f"{post_id}:{channel}", inputs)
        if row["status"] != "succeeded":
            db.execute("UPDATE tasks SET status='succeeded',artifact_hash=?,error_code=NULL,attempts=attempts+1,updated_at=? WHERE id=?", (job_hash, now(), row["id"])); db.commit()
        jobs.append({"channel": channel, "job_artifact": job_hash, "sources": len(sources[channel])})
    return {"status": "ok", "post_id": post_id, "jobs": jobs, "warnings": ["transcript_unavailable" if not sources["transcript"] else ""] if not sources["transcript"] else []}


def do_model_job_input(project: Path, job_hash: str) -> dict[str, Any]:
    try:
        job = read_artifact(project, job_hash).get("data")
    except analysis.AnalysisError as exc:
        return {"status": "invalid_input", "error": str(exc)}
    if not isinstance(job, dict) or job.get("kind") != "analysis.model_job":
        return {"status": "invalid_input", "error": "model_job_required"}
    # Never render allowed_sources: it contains validation metadata that the
    # model neither needs nor should be able to imitate in its response.
    return {"status": "ok", "job_artifact": job_hash, "channel": job["channel"], "model_input": job["model_input"]}


def submitted_atoms(project: Path, db: sqlite3.Connection) -> list[dict[str, Any]]:
    atoms: dict[str, dict[str, Any]] = {}
    for row in db.execute("SELECT artifact_hash FROM tasks WHERE kind='evidence-submit' AND status='succeeded' ORDER BY updated_at").fetchall():
        payload = read_artifact(project, str(row["artifact_hash"]))
        for atom in payload.get("data", {}).get("evidence", []):
            if isinstance(atom, dict) and atom.get("evidence_id"):
                atoms[str(atom["evidence_id"])] = atom
    return list(atoms.values())


def do_cluster(project: Path, db: sqlite3.Connection) -> dict[str, Any]:
    try:
        atoms = submitted_atoms(project, db)
    except analysis.AnalysisError as exc:
        return {"status": "invalid_input", "error": str(exc)}
    if not atoms: return {"status": "invalid_input", "error": "validated_evidence_required"}
    inputs = {"evidence_ids": sorted(atom["evidence_id"] for atom in atoms), "rubric_version": "v0.1"}
    row = task(db, "cluster-score", "project", inputs)
    if row["status"] == "succeeded": return {"status": "reused", "task_id": row["id"], "artifact": row["artifact_hash"]}
    clusters = analysis.cluster_and_score(atoms)
    capture = artifact(project, db, "analysis.cluster_score", {"rubric_version": "v0.1", "clusters": clusters, "evidence_count": len(atoms)})
    db.execute("UPDATE tasks SET status='succeeded',artifact_hash=?,error_code=NULL,attempts=attempts+1,updated_at=? WHERE id=?", (capture, now(), row["id"])); db.commit()
    return {"status": "ok", "task_id": row["id"], "artifact": capture, "evidence": len(atoms), "clusters": len(clusters), "top_cluster": clusters[0]["cluster_id"] if clusters else None}


def do_content_prepare(project: Path, db: sqlite3.Connection, cluster_id: str, creator_project: Path, snapshot_at: str) -> dict[str, Any]:
    cluster_hash = latest_artifact(db, "cluster-score", "project")
    if not cluster_hash:
        return {"status": "invalid_input", "error": "cluster_score_required"}
    try:
        cluster_payload = read_artifact(project, cluster_hash)
        clusters = cluster_payload.get("data", {}).get("clusters", [])
        selected = next((item for item in clusters if isinstance(item, dict) and item.get("cluster_id") == cluster_id), None)
        if not selected:
            return {"status": "invalid_input", "error": "cluster_not_found"}
        atoms = submitted_atoms(project, db)
        opportunity = content.build_opportunity(cluster_hash, selected, atoms)
    except (analysis.AnalysisError, content.ContentError) as exc:
        return {"status": "invalid_input", "error": str(exc)}

    inputs = {"cluster_artifact": cluster_hash, "cluster_id": cluster_id, "nexttake_schema_version": content.SCHEMA_VERSION}
    row = task(db, "content-prepare", cluster_id, inputs)
    capture = str(row["artifact_hash"]) if row["status"] == "succeeded" and row["artifact_hash"] else artifact(project, db, "content.opportunity", opportunity)
    if row["status"] != "succeeded":
        db.execute("UPDATE tasks SET status='succeeded',artifact_hash=?,error_code=NULL,attempts=attempts+1,updated_at=? WHERE id=?", (capture, now(), row["id"])); db.commit()
    bridge_opportunity = {**opportunity, "opportunity_artifact": capture}
    try:
        written = creator_flow.write_opportunity(creator_project, bridge_opportunity, snapshot_at)
    except creator_flow.CreatorFlowError as exc:
        return {
            "status": "invalid_input", "error": str(exc), "artifact": capture,
            "next_action": {
                "action": "initialize_creator_project",
                "instruction": "在创作者目录中使用 NextTake 初始化创作者项目，然后重新运行 content-prepare。",
            },
        }
    return {"status": "reused" if row["status"] == "succeeded" else "ok", "artifact": capture, "cluster_id": cluster_id, **written}


def do_creator_studio(project: Path, creator_project: Path, candidate_id: str, output_dir: Path | None = None) -> dict[str, Any]:
    target_dir = output_dir or (paths(project)[0] / "creator-studio" / candidate_id)
    try:
        target = creator_reports.write_studio(creator_project, candidate_id, target_dir)
        payload = creator_reports.load_studio_payload(creator_project, candidate_id)
    except creator_reports.CreatorReportError as exc:
        return {"status": "invalid_input", "error": str(exc)}
    return {
        "status": "ok",
        "candidate_id": candidate_id,
        "studio": str(target),
        "prediction_hash": payload["prediction_hash"],
        "demo_data": payload["performance"]["demo_data"],
        "views": payload["performance"]["views"],
        "ratios": payload["performance"]["ratios"],
    }


def do_creator_attach(args: argparse.Namespace) -> dict[str, Any]:
    try:
        attached = creator_flow.attach_lifecycle(
            Path(args.creator_project), args.candidate_id,
            script_path=args.script_path,
            prediction_path=args.prediction_path,
            report_path=args.report_path,
            performance_file=args.performance_file,
            audience_path=args.audience_path,
            recommendation_path=args.recommendation_path,
            next_script_path=args.next_script_path,
        )
    except creator_flow.CreatorFlowError as exc:
        return {"status": "invalid_input", "error": str(exc)}
    return {"status": "ok", **attached, "next_action": "Run creator-studio for this candidate."}


def do_creator_demo(project: Path) -> dict[str, Any]:
    fixture = SKILL_ROOT / "fixtures" / "creator-demo"
    result = do_creator_studio(project, fixture, "61c7492abf1a")
    if result.get("status") == "ok":
        result.update({
            "mode": "offline_fixture",
            "product": "下一条 NextTake",
            "notice": "Discover uses desensitized pilot evidence. Publication and performance are explicitly labeled demo data.",
            "opportunities": 4,
            "workflow_stages": [
                "generate_current_draft", "score_draft", "pre_publish_prediction",
                "register_shoot", "register_manual_publish", "retro",
                "update_audience", "recommend_next", "generate_next_draft",
            ],
        })
    return result


def latest_reviews(project: Path, db: sqlite3.Connection) -> tuple[dict[str, dict[str, Any]], list[str]]:
    values: dict[str, dict[str, Any]] = {}
    hashes: list[str] = []
    for row in db.execute("SELECT entity_id,artifact_hash FROM tasks WHERE kind='review' AND status='succeeded' ORDER BY updated_at,id").fetchall():
        payload = read_artifact(project, str(row["artifact_hash"])).get("data")
        if isinstance(payload, dict) and payload.get("cluster_id") == row["entity_id"]:
            values[str(row["entity_id"])] = payload
            hashes.append(str(row["artifact_hash"]))
    return values, hashes


def do_review(project: Path, db: sqlite3.Connection, cluster_id: str, decision: str, rationale: str, traceability: int, clarity: int, actionability: int) -> dict[str, Any]:
    if decision not in {"accepted_for_research", "rejected", "needs_more_evidence"}:
        return {"status": "invalid_input", "error": "invalid_review_decision"}
    rationale = rationale.strip()
    if not rationale or len(rationale) > 1_000:
        return {"status": "invalid_input", "error": "review_rationale_required"}
    scores = {"traceability": traceability, "clarity": clarity, "actionability": actionability}
    if any(not isinstance(value, int) or value < 1 or value > 5 for value in scores.values()):
        return {"status": "invalid_input", "error": "review_scores_must_be_1_to_5"}
    cluster_hash = latest_artifact(db, "cluster-score", "project")
    if not cluster_hash: return {"status": "invalid_input", "error": "cluster_score_required"}
    clusters = read_artifact(project, cluster_hash).get("data", {}).get("clusters", [])
    if not any(isinstance(item, dict) and item.get("cluster_id") == cluster_id for item in clusters):
        return {"status": "invalid_input", "error": "cluster_not_found"}
    review = {"cluster_id": cluster_id, "decision": decision, "rationale": rationale, "scores": scores, "reviewed_at": now()}
    inputs = {"cluster_artifact": cluster_hash, "decision": decision, "rationale": rationale, "scores": scores}
    row = task(db, "review", cluster_id, inputs)
    if row["status"] == "succeeded": return {"status": "reused", "task_id": row["id"], "artifact": row["artifact_hash"]}
    capture = artifact(project, db, "review.decision", review)
    db.execute("UPDATE tasks SET status='succeeded',artifact_hash=?,error_code=NULL,attempts=attempts+1,updated_at=? WHERE id=?", (capture, now(), row["id"])); db.commit()
    return {"status": "ok", "task_id": row["id"], "artifact": capture, "decision": decision}


def do_report(project: Path, db: sqlite3.Connection, formal: bool) -> dict[str, Any]:
    cluster_hash = latest_artifact(db, "cluster-score", "project")
    if not cluster_hash: return {"status": "invalid_input", "error": "cluster_score_required"}
    try:
        clusters = read_artifact(project, cluster_hash).get("data", {}).get("clusters", [])
        atoms = submitted_atoms(project, db)
        review_map, review_hashes = latest_reviews(project, db)
    except analysis.AnalysisError as exc:
        return {"status": "invalid_input", "error": str(exc)}
    if not isinstance(clusters, list) or not atoms: return {"status": "invalid_input", "error": "validated_evidence_required"}
    payload = reports.packet_payload(clusters, atoms, review_map, requested_formal=formal)
    inputs = {"cluster_artifact": cluster_hash, "review_artifacts": sorted(review_hashes), "formal": formal, "packet_hash": digest(payload)}
    row = task(db, "report", "project", inputs)
    capture = artifact(project, db, "report.packet", payload)
    report_dir = project / "reports" / capture[:12]
    if row["status"] == "succeeded":
        return {"status": "reused", "task_id": row["id"], "artifact": row["artifact_hash"], "report_dir": str(report_dir), "report_type": payload["report_type"], "opportunities": len(payload["opportunities"]), "top_five": payload["top_five"]}
    reports.write_packet(report_dir, payload)
    if formal and not payload["coverage"]["formal_eligible"]:
        db.execute("UPDATE tasks SET status='coverage_insufficient',artifact_hash=?,error_code='E-ACQUISITION-COVERAGE-001',attempts=attempts+1,updated_at=? WHERE id=?", (capture, now(), row["id"])); db.commit()
        return {"status": "coverage_insufficient", "error": "E-ACQUISITION-COVERAGE-001", "artifact": capture, "report_dir": str(report_dir), "coverage": payload["coverage"]}
    db.execute("UPDATE tasks SET status='succeeded',artifact_hash=?,error_code=NULL,attempts=attempts+1,updated_at=? WHERE id=?", (capture, now(), row["id"])); db.commit()
    return {"status": "ok", "artifact": capture, "report_dir": str(report_dir), "report_type": payload["report_type"], "opportunities": len(payload["opportunities"]), "top_five": payload["top_five"]}


def provider_status(command: list[str], timeout: int = 35) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=os.environ.copy())
        parsed = json.loads(completed.stdout)
        return str(parsed.get("status") or "provider_protocol_error") if isinstance(parsed, dict) else "provider_protocol_error"
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return "provider_protocol_error"


def do_doctor(project: Path, db: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    """Check local provider entry points without reading credential stores."""
    checks: list[dict[str, Any]] = []
    checks.append({"platform": "douyin", "mode": "sidecar", "status": provider_status([sys.executable, str(PROVIDERS["douyin"]), "--sidecar-url", args.sidecar_url, "healthcheck"]), "automatic": True})
    checks.append({"platform": "douyin", "mode": "browser", "status": provider_status(browser_provider_command(project, args) + ["healthcheck"]), "automatic": True})
    checks.append({"platform": "bilibili", "mode": "cli", "status": provider_status([sys.executable, str(PROVIDERS["bilibili"]), "--bilibili-cli", args.bilibili_cli, "healthcheck"]), "automatic": True})
    refs = db.execute("SELECT platform, count(*) AS accounts FROM accounts GROUP BY platform ORDER BY platform").fetchall()
    credential_env = args.commenter_hmac_key_env
    return {
        "status": "ok",
        "healthy": any(item["platform"] == "douyin" and item["status"] == "ok" for item in checks) and any(item["platform"] == "bilibili" and item["status"] == "ok" for item in checks),
        "providers": checks,
        "configured_accounts": [{"platform": str(row["platform"]), "accounts": int(row["accounts"])} for row in refs],
        "commenter_hmac_key_configured": bool(credential_env and os.environ.get(credential_env)),
        "notice": "Credential values and provider configuration contents were not read or displayed.",
    }


def do_acceptance(project: Path, db: sqlite3.Connection) -> dict[str, Any]:
    """Report the agreed pilot acceptance gaps; this command never self-certifies."""
    cluster_hash = latest_artifact(db, "cluster-score", "project")
    if not cluster_hash:
        return {"status": "ok", "acceptance_ready": False, "criteria": [], "unmet": [{"criterion": "clustered_opportunities", "expected": ">=3", "actual": 0}]}
    try:
        clusters = read_artifact(project, cluster_hash).get("data", {}).get("clusters", [])
        atoms = submitted_atoms(project, db)
        reviews, _ = latest_reviews(project, db)
    except analysis.AnalysisError as exc:
        return {"status": "invalid_input", "error": str(exc)}
    clusters = clusters if isinstance(clusters, list) else []
    coverage = reports.coverage_diagnostic(atoms)
    accepted = {cluster_id for cluster_id, review in reviews.items() if review.get("decision") == "accepted_for_research"}
    top_five = [str(item.get("cluster_id")) for item in clusters[:5] if isinstance(item, dict)]
    criteria = [
        {"criterion": "automatic_platforms", "expected": ">=2", "actual": len(coverage["platforms"]), "met": len(coverage["platforms"]) >= 2},
        {"criterion": "effective_posts", "expected": ">=40", "actual": coverage["effective_posts"], "met": coverage["effective_posts"] >= 40},
        {"criterion": "clustered_opportunities", "expected": ">=3", "actual": len(clusters), "met": len(clusters) >= 3},
        {"criterion": "reported_opportunity_limit", "expected": "<=10", "actual": len(clusters), "met": len(clusters) <= 10},
        {"criterion": "accepted_for_research", "expected": ">=3", "actual": len(accepted), "met": len(accepted) >= 3},
        {"criterion": "accepted_in_top_five", "expected": ">=2", "actual": sum(cluster_id in accepted for cluster_id in top_five), "met": sum(cluster_id in accepted for cluster_id in top_five) >= 2},
        {"criterion": "formal_coverage_eligible", "expected": True, "actual": coverage["formal_eligible"], "met": coverage["formal_eligible"]},
    ]
    unmet = [{key: value for key, value in item.items() if key != "met"} for item in criteria if not item["met"]]
    return {"status": "ok", "acceptance_ready": not unmet, "criteria": criteria, "unmet": unmet, "coverage": coverage, "notice": "Passing this pilot acceptance means the discovery workflow is ready for product-owner research review. It does not establish market demand or product viability."}


def replay_task(project: Path, db: sqlite3.Connection, row: sqlite3.Row, args: argparse.Namespace) -> dict[str, Any]:
    """Replay only tasks whose complete, stable input already lives in artifacts."""
    try:
        inputs = json.loads(row["input_json"])
    except json.JSONDecodeError:
        return {"task_id": row["id"], "kind": row["kind"], "status": "unrecoverable_task_input"}
    kind = str(row["kind"])
    if kind == "sync":
        result = do_sync(project, db, row["entity_id"], int(inputs["pages"]), inputs.get("platform"), args)
    elif kind == "acquire":
        result = do_acquire(project, db, row["entity_id"], args, bool(inputs["media"]))
    elif kind == "model-job":
        result = do_prepare_analysis(project, db, str(inputs["post_id"]))
    elif kind == "evidence-submit":
        submission_hash = inputs.get("evidence_submission_artifact")
        if not isinstance(submission_hash, str):
            result = {"status": "requires_user_input", "error": "evidence_submission_payload_unavailable"}
        else:
            try:
                submission = read_artifact(project, submission_hash).get("data", {})
                result = commit_evidence(project, db, str(submission["job_artifact"]), submission["payload"])
            except (analysis.AnalysisError, KeyError, TypeError):
                result = {"status": "requires_user_input", "error": "evidence_submission_payload_unavailable"}
    elif kind == "cluster-score":
        result = do_cluster(project, db)
    elif kind == "report":
        result = do_report(project, db, bool(inputs.get("formal", False)))
    elif kind == "review":
        scores = inputs.get("scores") if isinstance(inputs.get("scores"), dict) else {}
        result = do_review(project, db, row["entity_id"], str(inputs.get("decision", "")), str(inputs.get("rationale", "")), scores.get("traceability"), scores.get("clarity"), scores.get("actionability"))
    elif kind == "transcript-import":
        result = {"status": "requires_user_input", "error": "transcript_source_file_must_be_reprovided"}
    else:
        result = {"status": "unsupported", "error": "task_kind_not_replayable"}
    return {"task_id": row["id"], "kind": kind, **result}


def do_demo(project: Path, db: sqlite3.Connection) -> dict[str, Any]:
    """Run the real P6 validators and scorer with versioned offline model output."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "demo-evidence.json"
    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        entries = fixture["evidence"]
    except (OSError, KeyError, json.JSONDecodeError):
        return {"status": "invalid_input", "error": "demo_fixture_unavailable"}
    db.execute("INSERT OR IGNORE INTO projects VALUES ('project', ?, ?)", ("Vlog Demand Miner offline demo", now()))
    post_creator = {"demo-post-1": "demo-creator-a", "demo-post-2": "demo-creator-b", "demo-post-3": "demo-creator-c"}
    for creator_id in sorted(set(post_creator.values())):
        db.execute("INSERT OR IGNORE INTO creators VALUES (?,?,?)", (creator_id, creator_id, now()))
    for post_id, creator_id in post_creator.items():
        db.execute("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,0)", (post_id, creator_id, "offline-demo", post_id, post_id, None, "video", "{}"))
    db.commit()
    source_rows = []
    for item in entries:
        source_rows.append({"source_id": item["source_id"], "channel": item["channel"], "text": item["quote_snippet"], "commenter_id": f"demo-{item['source_id']}" if item["channel"] == "comment" else ""})
    source_hash = artifact(project, db, "analysis.demo_sources", {"sources": source_rows, "fixture": fixture_path.name})
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in entries:
        post_id = item["source_id"].split(":", 2)[1]
        grouped.setdefault((post_id, item["channel"]), []).append(item)
    submitted = 0
    for (post_id, channel), model_output in sorted(grouped.items()):
        post = dict(db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone())
        sources = []
        for index, item in enumerate(model_output):
            source_id = item["source_id"]
            source = next(row for row in source_rows if row["source_id"] == source_id)
            sources.append({**source, "source_pointer": f"artifact:{source_hash}#sources[{source_rows.index(source)}]"})
        job = analysis.make_model_job(channel, post, sources)
        job_hash = artifact(project, db, "analysis.model_job", job)
        outcome = commit_evidence(project, db, job_hash, {"evidence": model_output})
        if outcome["status"] not in {"ok", "reused"}:
            return outcome
        submitted += outcome.get("evidence", 0)
    outcome = do_cluster(project, db)
    if outcome["status"] not in {"ok", "reused"}: return outcome
    return {"status": "ok", "fixture": fixture_path.name, "submitted_evidence": submitted, **outcome}


def response_operation_statuses(response: dict[str, Any]) -> set[str]:
    operations = ((response.get("data") or {}).get("operations") or []) if isinstance(response, dict) else []
    return {str(item.get("status")) for item in operations if isinstance(item, dict) and item.get("status")}


def invoke_provider(command: list[str], plan: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(command + ["run", "--plan", str(plan)], capture_output=True, text=True, timeout=300, env=os.environ.copy())
        return json.loads(completed.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return {"status": "provider_protocol_error", "data": None}


def request_delay_bounds(args: argparse.Namespace) -> tuple[float, float]:
    try:
        minimum = float(getattr(args, "request_delay_min_seconds", DEFAULT_REQUEST_DELAY_MIN_SECONDS))
        maximum = float(getattr(args, "request_delay_max_seconds", DEFAULT_REQUEST_DELAY_MAX_SECONDS))
    except (TypeError, ValueError) as exc:
        raise ValueError("request_delay_must_be_numeric") from exc
    if not math.isfinite(minimum) or not math.isfinite(maximum) or minimum < 0 or maximum < minimum:
        raise ValueError("request_delay_range_invalid")
    return minimum, maximum


def acquisition_policy(args: argparse.Namespace, platform: str) -> dict[str, Any]:
    minimum, maximum = request_delay_bounds(args)
    return {
        "revision": ACQUISITION_POLICY_REVISION,
        "execution": "serial",
        "request_delay_seconds": {"min": minimum, "max": maximum},
        "sync_page_limit": 1 if platform == "bilibili" else None,
    }


def _read_request_gate(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"revision": ACQUISITION_POLICY_REVISION, "platforms": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("platforms"), dict):
        return {"revision": ACQUISITION_POLICY_REVISION, "platforms": {}}
    return payload


def _write_request_gate(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(dump(payload), encoding="utf-8")
    temporary.replace(path)


def invoke_provider_serialized(
    project: Path,
    platform: str,
    command: list[str],
    operation: dict[str, Any],
    delay_bounds: tuple[float, float],
    *,
    clock: Callable[[], float] = time.time,
    sleeper: Callable[[float], None] = time.sleep,
    jitter: Callable[[float, float], float] = random.uniform,
) -> dict[str, Any]:
    """Run one provider operation under a project-wide persistent request gate."""
    root, _, _ = paths(project)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "provider-request-gate.lock"
    state_path = root / "provider-request-gate.json"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = _read_request_gate(state_path)
        platform_state = state["platforms"].get(platform)
        last_completed = platform_state.get("last_completed_at") if isinstance(platform_state, dict) else None
        if isinstance(last_completed, (int, float)):
            delay = jitter(*delay_bounds)
            remaining = float(last_completed) + delay - clock()
            if remaining > 0:
                sleeper(remaining)
        with tempfile.NamedTemporaryFile("w", suffix=".json", dir=root, delete=False, encoding="utf-8") as handle:
            json.dump({"operations": [operation]}, handle)
            plan = Path(handle.name)
        try:
            return invoke_provider(command, plan)
        finally:
            plan.unlink(missing_ok=True)
            state["revision"] = ACQUISITION_POLICY_REVISION
            state["platforms"][platform] = {"last_completed_at": clock()}
            _write_request_gate(state_path, state)


def _combine_provider_responses(responses: list[dict[str, Any]]) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    warnings: list[str] = []
    envelope_failed = False
    for response in responses:
        envelope_failed = envelope_failed or response.get("status") != "ok"
        for warning in response.get("warnings") or []:
            if isinstance(warning, str) and warning not in warnings:
                warnings.append(warning)
        data = response.get("data")
        result_items = data.get("operations") if isinstance(data, dict) else None
        if isinstance(result_items, list):
            operations.extend(item for item in result_items if isinstance(item, dict))
        elif response.get("status"):
            operations.append({"status": str(response["status"])})
    operation_failed = not operations or any(item.get("status") != "ok" for item in operations)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "partial" if envelope_failed or operation_failed else "ok",
        "data": {"operations": operations},
        "warnings": warnings,
    }


def invoke_operations_serially(
    project: Path,
    platform: str,
    command: list[str],
    operations: list[dict[str, Any]],
    delay_bounds: tuple[float, float],
) -> dict[str, Any]:
    responses = [
        invoke_provider_serialized(project, platform, command, operation, delay_bounds)
        for operation in operations
    ]
    return _combine_provider_responses(responses)


def browser_profile(project: Path, args: argparse.Namespace) -> Path:
    profile = Path(args.douyin_browser_profile_dir).expanduser().resolve()
    root, _, _ = paths(project)
    try:
        profile.relative_to(root.resolve())
    except ValueError:
        return profile
    raise ValueError("douyin_browser_profile_must_be_outside_research_project")


def browser_provider_command(project: Path, args: argparse.Namespace) -> list[str]:
    command = [args.douyin_browser_python, str(DOUYIN_BROWSER_PROVIDER), "--profile-dir", str(browser_profile(project, args)),
               "--upstream-adapter-dir", str(getattr(args, "douyin_adapter_dir", ""))]
    if args.commenter_hmac_key_env:
        command += ["--commenter-hmac-key-env", args.commenter_hmac_key_env]
    return command


def run_provider(project: Path, platform: str, args: argparse.Namespace, operations: list[dict[str, Any]]) -> dict[str, Any]:
    provider = PROVIDERS.get(platform)
    if not provider:
        return {"status": "unsupported", "data": None}
    root, _, _ = paths(project)
    try:
        delay_bounds = request_delay_bounds(args)
        if platform == "bilibili":
            command = [sys.executable, str(provider), "--bilibili-cli", args.bilibili_cli, "--media-dir", str(root / "media")]
            if args.commenter_hmac_key_env:
                command += ["--commenter-hmac-key-env", args.commenter_hmac_key_env]
            return invoke_operations_serially(project, platform, command, operations, delay_bounds)
        if args.douyin_provider == "browser":
            command = browser_provider_command(project, args)
            response = invoke_operations_serially(project, platform, command, operations, delay_bounds)
            response["provider_selection"] = {"requested": "browser", "selected": "browser"}
            return response
        command = [sys.executable, str(provider), "--sidecar-url", args.sidecar_url, "--media-dir", str(root / "media")]
        if args.commenter_hmac_key_env:
            command += ["--commenter-hmac-key-env", args.commenter_hmac_key_env]
        if args.douyin_provider == "sidecar":
            response = invoke_operations_serially(project, platform, command, operations, delay_bounds)
            response["provider_selection"] = {"requested": "sidecar", "selected": "sidecar"}
            return response
        responses: list[dict[str, Any]] = []
        fallback_reasons: set[str] = set()
        using_browser = False
        browser_command: list[str] | None = None
        for operation in operations:
            selected_command = browser_command if using_browser else command
            response = invoke_provider_serialized(project, platform, selected_command or command, operation, delay_bounds)
            failed = response_operation_statuses(response)
            should_fallback = not using_browser and (
                response.get("status") == "provider_protocol_error"
                or bool(failed.intersection(DOUYIN_FALLBACK_STATUSES))
            )
            if should_fallback:
                fallback_reasons.update(failed.intersection(DOUYIN_FALLBACK_STATUSES) or {"provider_protocol_error"})
                browser_command = browser_provider_command(project, args)
                response = invoke_provider_serialized(project, platform, browser_command, operation, delay_bounds)
                using_browser = True
            responses.append(response)
        combined = _combine_provider_responses(responses)
        if using_browser:
            combined["provider_selection"] = {"requested": "auto", "selected": "browser", "fallback_from": "sidecar", "reason": sorted(fallback_reasons)}
        else:
            combined["provider_selection"] = {"requested": "auto", "selected": "sidecar"}
        return combined
    except ValueError as exc:
        return {"status": "invalid_input", "error": str(exc), "data": None}


def one_account(db: sqlite3.Connection, creator_id: str, platform: str | None) -> sqlite3.Row | None:
    query, values = "SELECT * FROM accounts WHERE creator_id=?", [creator_id]
    if platform:
        query += " AND platform=?"
        values.append(platform)
    rows = db.execute(query, values).fetchall()
    return rows[0] if len(rows) == 1 else None


def do_sync(project: Path, db: sqlite3.Connection, creator_id: str, pages: int, platform: str | None, args: argparse.Namespace) -> dict[str, Any]:
    account = one_account(db, creator_id, platform)
    if not account:
        return {"status": "invalid_input", "error": "exactly_one_matching_platform_account_required"}
    platform = account["platform"]
    if pages < 1:
        return {"status": "invalid_input", "error": "sync_pages_must_be_positive"}
    if platform == "bilibili" and pages != 1:
        return {"status": "invalid_input", "error": "bilibili_sync_requires_single_page"}
    try:
        policy = acquisition_policy(args, platform)
    except ValueError as exc:
        return {"status": "invalid_input", "error": str(exc)}
    revision = f"{DOUYIN_PROVIDER_REVISION}:{args.douyin_adapter_revision}" if platform == "douyin" else "bilibili-cli"
    inputs = {"creator_id": creator_id, "pages": pages, "platform": platform, "provider": f"{platform}-bridge", "provider_mode": args.douyin_provider if platform == "douyin" else "cli", "provider_revision": revision, "acquisition_policy": policy}
    row = task(db, "sync", creator_id, inputs)
    if row["status"] == "succeeded": return {"status": "reused", "task_id": row["id"]}
    db.execute("UPDATE tasks SET status='running',attempts=attempts+1,updated_at=? WHERE id=?", (now(), row["id"])); db.commit()
    if platform == "douyin":
        operations = [{"op": "list_posts", "sec_user_id": account["platform_account_id"], "max_pages": pages, "page_size": 20}]
    else:
        operations = [{"op": "list_posts", "uid": account["platform_account_id"], "max_pages": pages, "page_size": 20}]
    response = run_provider(project, platform, args, operations)
    result = ((response.get("data") or {}).get("operations") or [{}])[0]
    capture = artifact(project, db, f"{platform}.sync", response)
    if response.get("status") != "ok" or result.get("status") != "ok":
        code = result.get("status", response.get("status", "provider_error"))
        db.execute("UPDATE tasks SET status=?,artifact_hash=?,error_code=?,updated_at=? WHERE id=?", (code, capture, code, now(), row["id"])); db.commit()
        return {"status": code, "task_id": row["id"]}
    for post in result["posts"]:
        db.execute("INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,0) ON CONFLICT(platform,platform_post_id) DO UPDATE SET creator_id=excluded.creator_id,title=excluded.title,published_at=excluded.published_at,content_type=excluded.content_type,metrics_json=excluded.metrics_json", (jid(), creator_id, platform, post["post_id"], post["title"], post.get("published_at"), post["content_type"], dump(post["public_metrics"])))
    db.execute("UPDATE tasks SET status='succeeded',artifact_hash=?,error_code=NULL,updated_at=? WHERE id=?", (capture, now(), row["id"])); db.commit()
    warnings = list(result.get("warnings", []))
    if "serial_low_page_jitter_enabled" not in warnings:
        warnings.append("serial_low_page_jitter_enabled")
    return {"status": "ok", "task_id": row["id"], "platform": platform, "posts": len(result["posts"]), "coverage": result["coverage"], "warnings": warnings, "acquisition_policy": policy}


def commenter_identity_mode(args: argparse.Namespace) -> str:
    """Version comment acquisition by HMAC availability without persisting a secret."""
    env_name = str(args.commenter_hmac_key_env or "")
    return f"hmac:{env_name}" if env_name and os.environ.get(env_name) else "unavailable"


def do_acquire(project: Path, db: sqlite3.Connection, post_id: str, args: argparse.Namespace, media: bool) -> dict[str, Any]:
    post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post: return {"status": "invalid_input", "error": "post_not_found"}
    platform = post["platform"]
    try:
        policy = acquisition_policy(args, platform)
    except ValueError as exc:
        return {"status": "invalid_input", "error": str(exc)}
    inputs = {
        "post_id": post_id,
        "media": media,
        "platform": platform,
        "provider": f"{platform}-bridge",
        "provider_mode": args.douyin_provider if platform == "douyin" else "cli",
        "provider_revision": f"{DOUYIN_PROVIDER_REVISION}:{args.douyin_adapter_revision}" if platform == "douyin" else "bilibili-cli",
        "commenter_identity_mode": commenter_identity_mode(args),
        "acquisition_policy": policy,
    }
    row = task(db, "acquire", post_id, inputs)
    if row["status"] == "succeeded": return {"status": "reused", "task_id": row["id"]}
    db.execute("UPDATE tasks SET status='running',attempts=attempts+1,updated_at=? WHERE id=?", (now(), row["id"])); db.commit()
    raw_id = post["platform_post_id"]
    if platform == "douyin":
        operations = [{"op": "fetch_post", "aweme_id": raw_id}, {"op": "fetch_comments", "aweme_id": raw_id, "max_pages": 1, "page_size": 20, "require_nonempty": False}]
        if media and post["content_type"] == "video": operations.append({"op": "fetch_media", "aweme_id": raw_id, "source_url": f"https://www.douyin.com/video/{raw_id}"})
    elif platform == "bilibili":
        operations = [{"op": "fetch_post", "bvid": raw_id}, {"op": "fetch_comments", "bvid": raw_id}]
        if media: operations.append({"op": "fetch_media", "bvid": raw_id})
    else:
        return {"status": "unsupported", "error": "post_platform_unsupported"}
    response = run_provider(project, platform, args, operations)
    capture = artifact(project, db, f"{platform}.acquire", response)
    status = response.get("status")
    db.execute("UPDATE tasks SET status=?,artifact_hash=?,error_code=?,updated_at=? WHERE id=?", ("succeeded" if status == "ok" else status, capture, None if status == "ok" else status, now(), row["id"])); db.commit()
    return {"status": status, "task_id": row["id"], "platform": platform, "artifact": capture, "acquisition_policy": policy}


def main(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if args.command == "init":
        project.mkdir(parents=True, exist_ok=True); db = connect(project)
        db.execute("INSERT OR IGNORE INTO projects VALUES ('project', ?, ?)", (args.name, now())); db.commit()
        print(dump({"status": "ok", "project": str(project), "schema_version": SCHEMA_VERSION})); return 0
    db = connect(project)
    if args.command == "creator-add":
        account_id = args.account_id or args.sec_user_id
        if not account_id:
            result = {"status": "invalid_input", "error": "account_id_required"}
        else:
            creator = jid(); db.execute("INSERT INTO creators VALUES (?,?,?)", (creator, args.name, now()))
            credential_ref = args.credential_ref or ("douyin-local-provider" if args.platform == "douyin" else "bilibili-cli-local")
            db.execute("INSERT INTO accounts VALUES (?,?,?,?,?)", (jid(), creator, args.platform, account_id, credential_ref)); db.commit()
            result = {"status": "ok", "creator_id": creator, "platform": args.platform}
    elif args.command == "sync": result = do_sync(project, db, args.creator_id, args.pages, args.platform, args)
    elif args.command == "sample":
        rows = db.execute("SELECT id FROM posts WHERE creator_id=? AND content_type='video' ORDER BY published_at DESC, id", (args.creator_id,)).fetchall()
        chosen = [row["id"] for row in rows[:args.count]]; db.executemany("UPDATE posts SET selected=1 WHERE id=?", [(value,) for value in chosen]); db.commit(); result = {"status": "ok", "post_ids": chosen}
    elif args.command == "acquire": result = do_acquire(project, db, args.post_id, args, args.media)
    elif args.command == "transcript-import": result = do_import_transcript(project, db, args.post_id, Path(args.segments_file).expanduser())
    elif args.command == "prepare-analysis": result = do_prepare_analysis(project, db, args.post_id)
    elif args.command == "model-job-input": result = do_model_job_input(project, args.job_artifact)
    elif args.command == "submit-evidence":
        try:
            payload = json.loads(Path(args.evidence_file).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result = {"status": "invalid_input", "error": "evidence_json_required"}
        else:
            result = commit_evidence(project, db, args.job_artifact, payload)
    elif args.command == "cluster": result = do_cluster(project, db)
    elif args.command == "content-prepare": result = do_content_prepare(project, db, args.cluster_id, Path(args.creator_project), args.snapshot_at)
    elif args.command == "creator-studio": result = do_creator_studio(project, Path(args.creator_project), args.candidate_id, Path(args.output_dir) if args.output_dir else None)
    elif args.command == "creator-attach": result = do_creator_attach(args)
    elif args.command == "creator-demo": result = do_creator_demo(project)
    elif args.command == "report": result = do_report(project, db, args.formal)
    elif args.command == "review": result = do_review(project, db, args.cluster_id, args.decision, args.rationale, args.traceability, args.clarity, args.actionability)
    elif args.command == "doctor": result = do_doctor(project, db, args)
    elif args.command == "douyin-login":
        try:
            command = browser_provider_command(project, args) + ["login", "--wait-seconds", str(args.wait_seconds)]
            result = provider_status(command, timeout=min(args.wait_seconds, 900) + 45)
            result = {"status": result, "provider": "douyin-browser", "notice": "Complete login in the browser window. Login state stays in the local persistent profile and is never read or copied by VDM."}
        except ValueError as exc:
            result = {"status": "invalid_input", "error": str(exc)}
    elif args.command == "acceptance": result = do_acceptance(project, db)
    elif args.command == "demo": result = do_demo(project, db)
    elif args.command == "resume":
        replayed = []
        terminal = ("succeeded", "coverage_insufficient", "requires_user_input", "invalid_input", "unsupported", "unrecoverable_task_input")
        placeholders = ",".join("?" for _ in terminal)
        query = f"SELECT * FROM tasks WHERE status NOT IN ({placeholders}) ORDER BY updated_at,id"
        for row in db.execute(query, terminal).fetchall():
            replay = replay_task(project, db, row, args)
            if replay.get("status") == "requires_user_input":
                db.execute("UPDATE tasks SET status='requires_user_input',error_code=?,updated_at=? WHERE id=?", (replay.get("error"), now(), row["id"]))
                db.commit()
            replayed.append(replay)
        result = {"status": "ok", "replayed": replayed}
    else:
        result = {"status": "ok", "creators": db.execute("SELECT count(*) FROM creators").fetchone()[0], "posts": db.execute("SELECT count(*) FROM posts").fetchone()[0], "tasks": [dict(row) for row in db.execute("SELECT status,count(*) AS count FROM tasks GROUP BY status").fetchall()]}
    print(dump(result)); return 0 if result.get("status") in {"ok", "reused"} else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--sidecar-url", default="http://127.0.0.1:18080")
    parser.add_argument("--bilibili-cli", default=os.getenv("VDM_BILIBILI_CLI", "bili"))
    parser.add_argument("--douyin-provider", choices=["auto", "sidecar", "browser"], default=os.getenv("VDM_DOUYIN_PROVIDER", "auto"))
    parser.add_argument("--douyin-browser-python", default=os.getenv("VDM_DOUYIN_BROWSER_PYTHON", sys.executable))
    parser.add_argument("--douyin-browser-profile-dir", default=os.getenv("VDM_DOUYIN_BROWSER_PROFILE_DIR", "~/.local/share/vlog-demand-miner/browser-profiles/douyin"))
    adapter_default = os.getenv("NEXTTAKE_DOUYIN_ADAPTER_DIR") or str(VENDORED_DOUYIN_ADAPTER)
    revision_default = os.getenv("NEXTTAKE_DOUYIN_ADAPTER_REVISION") or "bundled"
    parser.add_argument("--douyin-adapter-dir", dest="douyin_adapter_dir", default=adapter_default)
    parser.add_argument("--douyin-adapter-revision", dest="douyin_adapter_revision", default=revision_default)
    parser.add_argument("--commenter-hmac-key-env")
    parser.add_argument("--request-delay-min-seconds", default=os.getenv("VDM_REQUEST_DELAY_MIN_SECONDS", str(DEFAULT_REQUEST_DELAY_MIN_SECONDS)))
    parser.add_argument("--request-delay-max-seconds", default=os.getenv("VDM_REQUEST_DELAY_MAX_SECONDS", str(DEFAULT_REQUEST_DELAY_MAX_SECONDS)))
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init"); init.add_argument("--name", required=True)
    add = commands.add_parser("creator-add"); add.add_argument("--name", required=True); add.add_argument("--platform", choices=sorted(PROVIDERS), default="douyin"); add.add_argument("--account-id"); add.add_argument("--sec-user-id"); add.add_argument("--credential-ref")
    sync = commands.add_parser("sync"); sync.add_argument("--creator-id", required=True); sync.add_argument("--platform", choices=sorted(PROVIDERS)); sync.add_argument("--pages", type=int, default=1)
    sample = commands.add_parser("sample"); sample.add_argument("--creator-id", required=True); sample.add_argument("--count", type=int, default=6)
    acquire = commands.add_parser("acquire"); acquire.add_argument("--post-id", required=True); acquire.add_argument("--media", action="store_true")
    transcript = commands.add_parser("transcript-import"); transcript.add_argument("--post-id", required=True); transcript.add_argument("--segments-file", required=True)
    prepare = commands.add_parser("prepare-analysis"); prepare.add_argument("--post-id", required=True)
    job_input = commands.add_parser("model-job-input"); job_input.add_argument("--job-artifact", required=True)
    submit = commands.add_parser("submit-evidence"); submit.add_argument("--job-artifact", required=True); submit.add_argument("--evidence-file", required=True)
    commands.add_parser("cluster")
    content_prepare = commands.add_parser("content-prepare"); content_prepare.add_argument("--cluster-id", required=True); content_prepare.add_argument("--creator-project", required=True); content_prepare.add_argument("--snapshot-at", default=time.strftime("%Y-%m-%d", time.localtime()))
    studio = commands.add_parser("creator-studio"); studio.add_argument("--creator-project", required=True); studio.add_argument("--candidate-id", required=True); studio.add_argument("--output-dir")
    attach = commands.add_parser("creator-attach"); attach.add_argument("--creator-project", required=True); attach.add_argument("--candidate-id", required=True); attach.add_argument("--script-path", required=True); attach.add_argument("--prediction-path", required=True); attach.add_argument("--report-path", required=True); attach.add_argument("--performance-file", required=True); attach.add_argument("--audience-path", required=True); attach.add_argument("--recommendation-path", required=True); attach.add_argument("--next-script-path")
    commands.add_parser("creator-demo")
    report = commands.add_parser("report"); report.add_argument("--formal", action="store_true")
    review = commands.add_parser("review"); review.add_argument("--cluster-id", required=True); review.add_argument("--decision", required=True, choices=["accepted_for_research", "rejected", "needs_more_evidence"]); review.add_argument("--rationale", required=True); review.add_argument("--traceability", type=int, required=True); review.add_argument("--clarity", type=int, required=True); review.add_argument("--actionability", type=int, required=True)
    commands.add_parser("doctor")
    login = commands.add_parser("douyin-login"); login.add_argument("--wait-seconds", type=int, default=300)
    commands.add_parser("acceptance")
    commands.add_parser("demo")
    commands.add_parser("resume"); commands.add_parser("status")
    raise SystemExit(main(parser.parse_args()))
