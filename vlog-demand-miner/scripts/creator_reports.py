"""Safe, read-only Creator Studio projection for native cheat projects."""
from __future__ import annotations

import hashlib
from html import escape
import json
from pathlib import Path
import re
from typing import Any

import content


MAX_INPUT_BYTES = 2 * 1024 * 1024


class CreatorReportError(ValueError):
    """A projection failure safe to return from the CLI."""


def _project_path(project: Path, relative: str) -> Path:
    project = project.expanduser().resolve()
    target = (project / relative).resolve()
    try:
        target.relative_to(project)
    except ValueError as exc:
        raise CreatorReportError("creator_path_outside_project") from exc
    if not target.is_file():
        raise CreatorReportError(f"creator_file_not_found:{relative}")
    return target


def _read_text(path: Path) -> str:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise CreatorReportError("studio_payload_too_large")
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise CreatorReportError(f"invalid_json:{path.name}") from exc


def prediction_section_hash(markdown: str) -> str:
    start = markdown.find("## 预测")
    end = markdown.find("## 复盘", start + 1)
    if start < 0 or end < 0:
        raise CreatorReportError("prediction_sections_required")
    return hashlib.sha256(markdown[start:end].encode("utf-8")).hexdigest()


def _inline(value: str) -> str:
    safe = escape(value)
    safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
    safe = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", safe)
    return safe


def markdown_html(markdown: str) -> str:
    """Render a deliberately small, script-free Markdown subset."""
    output: list[str] = []
    paragraph: list[str] = []
    in_list = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            output.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            output.append("</ul>")
            in_list = False

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            flush_paragraph()
            close_list()
            continue
        if line.startswith("### "):
            flush_paragraph(); close_list(); output.append(f"<h4>{_inline(line[4:])}</h4>")
        elif line.startswith("## "):
            flush_paragraph(); close_list(); output.append(f"<h3>{_inline(line[3:])}</h3>")
        elif line.startswith("# "):
            flush_paragraph(); close_list(); output.append(f"<h2>{_inline(line[2:])}</h2>")
        elif line.startswith("- "):
            flush_paragraph()
            if not in_list:
                output.append("<ul>"); in_list = True
            output.append(f"<li>{_inline(line[2:])}</li>")
        elif line.startswith(">"):
            flush_paragraph(); close_list(); output.append(f"<blockquote>{_inline(line.lstrip('> ').strip())}</blockquote>")
        elif line == "---":
            flush_paragraph(); close_list(); output.append("<hr>")
        else:
            paragraph.append(line)
    flush_paragraph(); close_list()
    return "".join(output)


def script_display_markdown(markdown: str) -> str:
    """Keep the creator-facing title and body, hiding workflow metadata."""
    title = next((line.strip() for line in markdown.splitlines() if line.startswith("# ")), "# 文案")
    if "\n---\n" in markdown:
        body = markdown.split("\n---\n", 1)[1].strip()
        return f"{title}\n\n{body}\n"
    return markdown


def prediction_display_markdown(markdown: str) -> str:
    """Hide IDs, paths and integrity metadata while keeping the useful bet."""
    start = markdown.find("## 预测")
    end = markdown.find("## 复盘", start + 1)
    if start < 0 or end < 0:
        return markdown
    visible = []
    for line in markdown[start:end].splitlines():
        if "immutable" in line.casefold():
            continue
        visible.append(line)
    text = "\n".join(visible)
    replacements = {
        "## 预测 v1": "## 预期结果",
        "**Bucket**": "**预期播放区间**",
        "**内心概率分布**": "**可能结果**",
        "**一句话 reason**": "**判断依据**",
        "## 关键校准假设": "## 本期重点观察",
        "**我押**": "**预期**",
        "**证伪条件**": "**什么情况说明判断错了**",
        "Evidence": "证据",
        " -> ": "：",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return "# 发布前判断\n\n" + text.strip() + "\n"


def user_facing_markdown(markdown: str) -> str:
    text = re.sub(r"`?\[?[0-9a-f]{24}\]?`?", "原始评论证据", markdown, flags=re.IGNORECASE)
    text = re.sub(r"`?CMT-[A-Z0-9]+`?", "评论反馈", text)
    replacements = {
        "`refuted`": "被推翻",
        "`validated`": "已验证",
        "`inconclusive`": "暂时无法判断",
        "Demo performance data": "演示表现数据",
        "Evidence": "证据",
        "Pilot": "试点",
        "# 受众画像 audience.md": "# 当前受众画像",
        "**Confidence**": "**可信度**",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    lines = [line for line in text.splitlines() if not line.startswith("**Persona 版本**") and not line.startswith("**Last rebuilt**")]
    return "\n".join(lines)


def load_studio_payload(project: Path, candidate_id: str) -> dict[str, Any]:
    project = project.expanduser().resolve()
    link_path = _project_path(project, f".nexttake/links/{candidate_id}.json")
    link = _read_json(link_path)
    if not isinstance(link, dict) or link.get("candidate_id") != candidate_id:
        raise CreatorReportError("invalid_nexttake_link")
    required = ("source_json", "script_path", "prediction_path", "report_path", "audience_path", "recommendation_path", "performance_path")
    if any(not isinstance(link.get(field), str) or not link[field] for field in required):
        raise CreatorReportError("incomplete_nexttake_link")
    opportunity = _read_json(_project_path(project, link["source_json"]))
    index = _read_json(_project_path(project, link["opportunity_index"])) if isinstance(link.get("opportunity_index"), str) and link["opportunity_index"] else {"opportunities": [{
        "rank": 1,
        "cluster_id": opportunity.get("cluster_id"),
        "demand_score": opportunity.get("demand_score"),
        "confidence": opportunity.get("confidence"),
        "maturity": opportunity.get("maturity"),
        "summary": {"pain_statement": opportunity.get("audience_problem") or opportunity.get("title") or "Content opportunity"},
    }]}
    performance_raw = _read_json(_project_path(project, link["performance_path"]))
    if not isinstance(opportunity, dict) or not isinstance(index, dict) or not isinstance(index.get("opportunities"), list):
        raise CreatorReportError("invalid_opportunity_fixture")
    try:
        performance = content.validate_performance(performance_raw)
    except content.ContentError as exc:
        raise CreatorReportError(str(exc)) from exc
    prediction = _read_text(_project_path(project, link["prediction_path"]))
    return {
        "candidate_id": candidate_id,
        "link": link,
        "opportunity": opportunity,
        "opportunities": index["opportunities"],
        "script_markdown": _read_text(_project_path(project, link["script_path"])),
        "prediction_markdown": prediction,
        "prediction_hash": prediction_section_hash(prediction),
        "report_markdown": _read_text(_project_path(project, link["report_path"])),
        "audience_markdown": _read_text(_project_path(project, link["audience_path"])),
        "recommendation_markdown": _read_text(_project_path(project, link["recommendation_path"])),
        "next_script_markdown": _read_text(_project_path(project, link["next_script_path"])) if isinstance(link.get("next_script_path"), str) and link["next_script_path"] else "",
        "performance": performance,
    }


def _metric(label: str, value: str, note: str = "") -> str:
    return f"<div class='metric'><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small></div>"


def studio_html(payload: dict[str, Any]) -> str:
    opportunity = payload["opportunity"]
    performance = payload["performance"]
    ratios = performance["ratios"]
    evidence = "".join(f"<li><p>{escape(item['quote_snippet'])}</p></li>" for item in opportunity.get("supporting_evidence", []))
    limitations = "".join(f"<li>{escape(item)}</li>" for item in opportunity.get("limitations", []))
    opportunity_rows = "".join(
        f"<tr{' class=selected' if item.get('cluster_id') == opportunity.get('cluster_id') else ''}><td>{escape(str(item.get('rank', '')))}</td><td><strong>{escape(item['summary']['pain_statement'])}</strong></td><td>{item['demand_score']}</td></tr>"
        for item in payload["opportunities"]
    )
    comments = "".join(f"<li><p>{escape(item['text'])}</p></li>" for item in performance["top_comments"])
    demo_label = "<span class='demo'>演示数据</span>" if performance["demo_data"] else ""
    metrics = "".join([
        _metric("播放", f"{performance['views']:,}"),
        _metric("赞播比", f"{ratios['likes_per_view']:.2%}"),
        _metric("评播比", f"{ratios['comments_per_view']:.2%}"),
        _metric("藏播比", f"{ratios['saves_per_view']:.2%}"),
        _metric("分播比", f"{ratios['shares_per_view']:.2%}"),
        _metric("转粉率", f"{ratios['follows_per_view']:.2%}"),
    ])
    current_script = script_display_markdown(payload["script_markdown"])
    current_prediction = prediction_display_markdown(payload["prediction_markdown"])
    next_script = script_display_markdown(payload["next_script_markdown"]) if payload.get("next_script_markdown") else "# 下一期文案\n\n下一条方向已经确定，文案尚未生成。"
    report_markdown = user_facing_markdown(payload["report_markdown"])
    audience_markdown = user_facing_markdown(payload["audience_markdown"])
    recommendation_markdown = user_facing_markdown(payload["recommendation_markdown"])
    script_text = escape(current_script)
    next_script_text = escape(next_script)
    css = """
:root{color-scheme:light;--ink:#172027;--muted:#65727b;--line:#d8dee2;--paper:#ffffff;--wash:#f3f5f6;--red:#b42318;--green:#18794e;--blue:#175cd3;--yellow:#8a6100}*{box-sizing:border-box}html,body{max-width:100%;overflow-x:hidden}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;color:var(--ink);background:var(--paper);line-height:1.65}button,a{font:inherit}.shell{max-width:1180px;margin:auto;padding:0 24px}.masthead{border-bottom:1px solid var(--line);padding:28px 0 22px;background:#fff}.brand{display:flex;align-items:end;justify-content:space-between;gap:24px}.brand h1{font-size:32px;line-height:1;margin:0;letter-spacing:0}.brand p{margin:8px 0 0;color:var(--muted)}.demo{display:inline-block;padding:4px 8px;border:1px solid #f0b429;color:#6f4b00;background:#fff7d6;border-radius:4px;font-size:12px;font-weight:700}.nav{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line)}.nav .shell{display:flex;gap:4px;overflow:auto}.nav a{color:var(--ink);text-decoration:none;padding:13px 16px;border-bottom:3px solid transparent;white-space:nowrap}.nav a:hover,.nav a:focus{border-color:var(--red);outline:none}.band{padding:54px 0;border-bottom:1px solid var(--line)}.band.alt{background:var(--wash)}.section-head{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:24px}.section-head h2{font-size:24px;margin:0}.section-head p{margin:0;color:var(--muted);max-width:660px}.opportunity-table{width:100%;border-collapse:collapse;background:#fff}.opportunity-table th,.opportunity-table td{text-align:left;padding:14px;border-bottom:1px solid var(--line);vertical-align:top}.opportunity-table th{font-size:12px;color:var(--muted);text-transform:uppercase}.opportunity-table td small{display:block;color:var(--muted)}.opportunity-table tr.selected{background:#fff3f1;box-shadow:inset 4px 0 var(--red)}.split{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr);gap:28px}.panel{border:1px solid var(--line);border-radius:6px;background:#fff;padding:22px;min-width:0;overflow-wrap:anywhere}.panel h3:first-child,.panel h2:first-child{margin-top:0}.evidence-list,.comment-list{list-style:none;padding:0;margin:0}.evidence-list li,.comment-list li{padding:14px 0;border-bottom:1px solid var(--line)}.evidence-list p,.comment-list p{margin:5px 0 0}.limitations{border-left:4px solid #d6a000;padding-left:18px}.limitations li{margin:8px 0}.copy{border:1px solid var(--line);background:#fff;padding:8px 12px;border-radius:4px;cursor:pointer;font-weight:650}.copy:hover,.copy:focus{border-color:var(--blue);outline:2px solid #b9d1ff}.markdown h2{font-size:22px}.markdown h3{font-size:18px;margin-top:28px}.markdown h4{font-size:16px}.markdown blockquote{margin:16px 0;padding:12px 16px;border-left:4px solid var(--blue);background:#eef4ff}.markdown code{font-size:12px;color:#344054;overflow-wrap:anywhere}.metric-strip{display:grid;grid-template-columns:repeat(6,1fr);border:1px solid var(--line);background:#fff;margin-bottom:28px}.metric{padding:16px;border-right:1px solid var(--line);min-width:0}.metric:last-child{border-right:0}.metric span,.metric small{display:block;color:var(--muted);font-size:12px}.metric strong{display:block;font-size:22px;margin:3px 0}.hash{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;overflow-wrap:anywhere;color:var(--muted)}footer{padding:28px 0;color:var(--muted);font-size:13px}@media(max-width:800px){.shell{padding:0 16px}.brand,.section-head{display:block}.demo{margin-top:14px}.band{padding:38px 0}.split{grid-template-columns:1fr}.metric-strip{grid-template-columns:repeat(2,1fr)}.metric:nth-child(2n){border-right:0}.opportunity-table,.opportunity-table tbody,.opportunity-table tr,.opportunity-table td{display:block;width:100%}.opportunity-table thead{display:none}.opportunity-table tr{padding:14px 12px;border-bottom:1px solid var(--line)}.opportunity-table tr:last-child{border-bottom:0}.opportunity-table tr.selected{box-shadow:inset 4px 0 var(--red)}.opportunity-table td{border:0;padding:2px 8px}.opportunity-table td:first-child{font-size:12px;color:var(--muted)}.opportunity-table td:nth-child(3){margin-top:5px;font-size:13px;color:var(--muted)}.opportunity-table td:nth-child(3)::before{content:"需求分 ";font-weight:650}.opportunity-table td:nth-child(4),.opportunity-table td:nth-child(5){display:none}.section-head p{margin-top:8px}}
"""
    js = """
document.querySelectorAll('[data-copy]').forEach(function(button){button.addEventListener('click',function(){var target=document.getElementById(button.dataset.copy);var label=button.dataset.label;navigator.clipboard.writeText(target.textContent).then(function(){button.textContent='已复制';setTimeout(function(){button.textContent=label},1400)})})});
"""
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>下一条 NextTake Creator Studio</title><style>{css}</style></head><body>
<header class='masthead'><div class='shell brand'><div><h1>下一条 NextTake</h1><p>让上一条，决定下一条。</p></div>{demo_label}</div></header>
<nav class='nav'><div class='shell'><a href='#discover'>发现</a><a href='#create'>创作</a><a href='#learn'>复盘</a><a href='#next'>下一条</a></div></nav>
<main>
<section id='discover' class='band alt'><div class='shell'><div class='section-head'><div><h2>发现：从真实问题开始</h2><p>团播试点的 4 个内容机会。红色行是本次创作主题，需求分用于比较当前信号强弱，不代表流量承诺。</p></div></div><div class='panel'><table class='opportunity-table'><thead><tr><th>#</th><th>受众问题</th><th>需求分</th></tr></thead><tbody>{opportunity_rows}</tbody></table></div><div class='split' style='margin-top:28px'><div class='panel'><h3>观众原话</h3><ul class='evidence-list'>{evidence}</ul></div><aside class='panel limitations'><h3>使用时注意</h3><ul>{limitations}</ul></aside></div></div></section>
<section id='create' class='band'><div class='shell'><div class='section-head'><div><h2>本期文案</h2></div><button class='copy' data-copy='script-source' data-label='复制本期文案'>复制本期文案</button></div><div class='split'><article class='panel markdown'>{markdown_html(current_script)}</article><aside class='panel markdown'>{markdown_html(current_prediction)}</aside></div><pre id='script-source' hidden>{script_text}</pre></div></section>
<section id='learn' class='band alt'><div class='shell'><div class='section-head'><div><h2>本期复盘</h2><p>哪些判断成立、哪些需要调整，以及观众真正继续追问了什么。</p></div>{demo_label}</div><div class='metric-strip'>{metrics}</div><div class='split'><article class='panel markdown'>{markdown_html(report_markdown)}</article><aside class='panel'><h3>观众评论</h3><ul class='comment-list'>{comments}</ul></aside></div><div class='panel markdown' style='margin-top:28px'><h2>受众变化</h2>{markdown_html(audience_markdown)}</div></div></section>
<section id='next' class='band'><div class='shell'><div class='section-head'><div><h2>下一条</h2><p>根据本期表现和评论，继续生成可以直接修改和拍摄的下一期内容。</p></div><button class='copy' data-copy='next-script-source' data-label='复制下一期文案'>复制下一期文案</button></div><div class='split'><article class='panel markdown'>{markdown_html(recommendation_markdown)}</article><aside class='panel markdown'><h2>下一期文案</h2>{markdown_html(next_script)}</aside></div><pre id='next-script-source' hidden>{next_script_text}</pre></div></section>
</main><footer><div class='shell'>NextTake Creator Studio · 发布仍由创作者手动完成</div></footer><script>{js}</script></body></html>"""


def write_studio(project: Path, candidate_id: str, output_dir: Path) -> Path:
    payload = load_studio_payload(project, candidate_id)
    html = studio_html(payload)
    if len(html.encode("utf-8")) > MAX_INPUT_BYTES:
        raise CreatorReportError("studio_payload_too_large")
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "index.html"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(target)
    return target
