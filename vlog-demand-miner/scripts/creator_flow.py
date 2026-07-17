"""Thin filesystem bridge from VDM artifacts to cheat-on-content projects."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

import content


class CreatorFlowError(ValueError):
    """A creator-project integration failure safe to show in the CLI."""


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def require_creator_project(project: Path) -> Path:
    project = project.expanduser().resolve()
    if not project.is_dir():
        raise CreatorFlowError("creator_project_not_found")
    if not (project / ".cheat-state.json").is_file():
        raise CreatorFlowError("cheat_init_required")
    return project


def _candidate_document(existing: str, candidate_id: str, entry: str) -> str:
    start = f"<!-- nexttake:{candidate_id}:start -->"
    end = f"<!-- nexttake:{candidate_id}:end -->"
    block = f"{start}\n{entry.rstrip()}\n{end}"
    if start in existing and end in existing:
        prefix, remainder = existing.split(start, 1)
        _, suffix = remainder.split(end, 1)
        return f"{prefix}{block}{suffix}"
    if not existing.strip():
        existing = "# 候选选题池\n\n## 候选项\n"
    return existing.rstrip() + "\n\n" + block + "\n"


def write_opportunity(project: Path, opportunity: dict[str, Any], snapshot_at: str) -> dict[str, Any]:
    project = require_creator_project(project)
    candidate_id = str(opportunity["candidate_id"])
    source_dir = project / ".nexttake" / "sources"
    link_dir = project / ".nexttake" / "links"
    source_json = source_dir / f"{candidate_id}.json"
    source_markdown = source_dir / f"{candidate_id}.md"
    link_path = link_dir / f"{candidate_id}.json"
    relative_source = source_markdown.relative_to(project).as_posix()

    _write_atomic(source_json, json.dumps(opportunity, ensure_ascii=False, indent=2) + "\n")
    _write_atomic(source_markdown, content.source_pack_markdown(opportunity))

    candidates = project / "candidates.md"
    existing = candidates.read_text(encoding="utf-8") if candidates.is_file() else ""
    entry = content.candidate_markdown(opportunity, relative_source, snapshot_at)
    _write_atomic(candidates, _candidate_document(existing, candidate_id, entry))

    existing_link: dict[str, Any] = {}
    if link_path.is_file():
        try:
            parsed = json.loads(link_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict) and parsed.get("candidate_id") == candidate_id:
                existing_link = parsed
        except json.JSONDecodeError:
            pass
    link = {
        **existing_link,
        "schema_version": content.SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "cluster_id": opportunity["cluster_id"],
        "opportunity_artifact": opportunity["opportunity_artifact"],
        "source_cluster_artifact": opportunity["source_cluster_artifact"],
        "source_pack": relative_source,
        "source_json": source_json.relative_to(project).as_posix(),
    }
    link.setdefault("script_path", None)
    link.setdefault("prediction_path", None)
    _write_atomic(link_path, json.dumps(link, ensure_ascii=False, indent=2) + "\n")
    return {
        "candidate_id": candidate_id,
        "candidates_file": str(candidates),
        "source_pack": str(source_markdown),
        "source_json": str(source_json),
        "link_file": str(link_path),
        "next_action": {
            "skill": "cheat-seed",
            "source_pack": str(source_markdown),
            "instruction": f"基于 {relative_source} 讨论并生成这一条内容草稿",
        },
    }


def _relative_existing(project: Path, value: str, field: str) -> str:
    target = Path(value).expanduser()
    if not target.is_absolute():
        target = project / target
    target = target.resolve()
    try:
        relative = target.relative_to(project)
    except ValueError as exc:
        raise CreatorFlowError(f"{field}_outside_creator_project") from exc
    if not target.is_file():
        raise CreatorFlowError(f"{field}_not_found")
    return relative.as_posix()


def attach_lifecycle(
    project: Path,
    candidate_id: str,
    *,
    script_path: str,
    prediction_path: str,
    report_path: str,
    performance_file: str,
    audience_path: str,
    recommendation_path: str,
    next_script_path: str | None = None,
) -> dict[str, Any]:
    project = require_creator_project(project)
    link_path = project / ".nexttake" / "links" / f"{candidate_id}.json"
    if not link_path.is_file():
        raise CreatorFlowError("nexttake_link_not_found")
    try:
        link = json.loads(link_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CreatorFlowError("invalid_nexttake_link") from exc
    if not isinstance(link, dict) or link.get("candidate_id") != candidate_id:
        raise CreatorFlowError("invalid_nexttake_link")
    try:
        raw_performance = json.loads(Path(performance_file).expanduser().read_text(encoding="utf-8"))
        content.validate_performance(raw_performance)
    except (OSError, json.JSONDecodeError):
        raise CreatorFlowError("performance_json_required")
    except content.ContentError as exc:
        raise CreatorFlowError(str(exc)) from exc
    performance_path = project / ".nexttake" / "performance" / f"{candidate_id}.json"
    _write_atomic(performance_path, json.dumps(raw_performance, ensure_ascii=False, indent=2) + "\n")
    link.update({
        "script_path": _relative_existing(project, script_path, "script"),
        "prediction_path": _relative_existing(project, prediction_path, "prediction"),
        "report_path": _relative_existing(project, report_path, "report"),
        "performance_path": performance_path.relative_to(project).as_posix(),
        "audience_path": _relative_existing(project, audience_path, "audience"),
        "recommendation_path": _relative_existing(project, recommendation_path, "recommendation"),
    })
    if next_script_path:
        link["next_script_path"] = _relative_existing(project, next_script_path, "next_script")
    _write_atomic(link_path, json.dumps(link, ensure_ascii=False, indent=2) + "\n")
    fields = ("script_path", "prediction_path", "report_path", "performance_path", "audience_path", "recommendation_path", "next_script_path")
    return {"candidate_id": candidate_id, "link_file": str(link_path), **{field: link.get(field) for field in fields}}
