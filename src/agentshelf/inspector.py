from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from agentshelf.config import Settings
from agentshelf.db import db_session
from agentshelf.errors import LibraryError

PARSER_VERSION = "1.0"
SCHEMA_VERSION = "1.0"
MAX_FILES = 80
MAX_FILE_BYTES = 512 * 1024
TEXT_SUFFIXES = {
    ".md",
    ".mdx",
    ".txt",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".sh",
    ".bash",
    ".zsh",
    ".css",
    ".html",
    ".xml",
    ".csv",
    ".ini",
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "logs", "cache", "dist"}
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|password)\s*[:=]\s*\S+"),
]
INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all |any )?(previous|prior) instructions"),
    re.compile(r"忽略(之前|以上|全部)?的?(指令|规则)"),
]


def discover_skills(settings: Settings) -> dict:
    imported = _imported_index(settings)
    items: list[dict] = []
    seen: set[str] = set()
    for root, label in _skill_roots():
        if not root.is_dir():
            continue
        for skill_md in root.rglob("SKILL.md"):
            if not skill_md.is_file() or skill_md.is_symlink() or _escapes(root, skill_md):
                continue
            directory = skill_md.parent
            key = str(directory)
            if key in seen:
                continue
            seen.add(key)
            items.append(_catalog_item(directory, label, imported.get(key)))
    for key, record in imported.items():
        if key not in seen:
            path = Path(key)
            items.append(
                {
                    "id": record["id"],
                    "name": record["name"],
                    "description": record["description"],
                    "path": key,
                    "source_label": "手动导入",
                    "readable": path.is_dir() and (path / "SKILL.md").is_file(),
                    "status": "missing" if not path.exists() else _change_status(path, record),
                    "report_id": record["report_id"],
                    "analyzed_at": record["analyzed_at"],
                    "mode": record["mode"],
                }
            )
    items.sort(key=lambda item: (item["source_label"], item["name"].lower()))
    return {"items": items}


def analyze_skill(settings: Settings, raw_path: str, mode: str = "quick", *, force: bool = False) -> dict:
    mode = _mode(mode)
    directory = _skill_directory(raw_path)
    files, findings = _collect_files(directory, mode)
    skill_md = next(item for item in files if item["relative_path"] == "SKILL.md")
    meta, _body, _start = parse_frontmatter(skill_md["text"])
    name = str(meta.get("name") or directory.name).strip() or directory.name
    description = str(meta.get("description") or "").strip()
    content_hash = _snapshot_hash(mode, files)
    now = _now()
    with db_session(settings.db_path, write=True) as conn:
        existing = conn.execute("SELECT * FROM inspector_skills WHERE source_uri = ?", (str(directory),)).fetchone()
        if existing:
            skill_id = existing["id"]
            conn.execute(
                "UPDATE inspector_skills SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                (name, description, now, skill_id),
            )
        else:
            skill_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO inspector_skills(id, name, description, source_type, source_uri, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (skill_id, name, description, "directory" if mode == "deep" else "file", str(directory), now, now),
            )
        previous = conn.execute(
            """
            SELECT v.id AS version_id, r.id AS report_id
            FROM inspector_versions v
            JOIN inspector_reports r ON r.version_id = v.id
            WHERE v.skill_id = ? AND v.content_hash = ? AND v.mode = ?
            ORDER BY r.created_at DESC LIMIT 1
            """,
            (skill_id, content_hash, mode),
        ).fetchone()
        if previous and not force:
            report = _load_report(conn, previous["report_id"])
            report["reused"] = True
            return report
        version_id = str(uuid.uuid4())
        manifest = [{"path": item["relative_path"], "sha256": item["sha256"], "size_bytes": item["size_bytes"]} for item in files]
        conn.execute(
            """
            INSERT INTO inspector_versions(id, skill_id, content_hash, mode, manifest_json, parser_version, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (version_id, skill_id, content_hash, mode, json.dumps(manifest, ensure_ascii=False), PARSER_VERSION, now),
        )
        stored_files = []
        for item in files:
            file_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO inspector_files(id, version_id, relative_path, file_type, content_hash, size_bytes, content_text, metadata_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    version_id,
                    item["relative_path"],
                    item["file_type"],
                    item["sha256"],
                    item["size_bytes"],
                    item["text"],
                    json.dumps({"redacted": item["redacted"], "skipped": item["skipped"]}, ensure_ascii=False),
                ),
            )
            stored_files.append({**item, "id": file_id})
        report_body = build_report(name, description, mode, stored_files, findings)
        job_id = str(uuid.uuid4())
        report_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO inspector_jobs(id, version_id, mode, status, stage, error_code, error_message, created_at, finished_at)
            VALUES(?, ?, ?, 'completed', 'saved', NULL, NULL, ?, ?)
            """,
            (job_id, version_id, mode, now, now),
        )
        conn.execute(
            """
            INSERT INTO inspector_reports(id, job_id, version_id, schema_version, overview_json, report_json, model_info_json, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                job_id,
                version_id,
                SCHEMA_VERSION,
                json.dumps(report_body["overview"], ensure_ascii=False),
                json.dumps(report_body, ensure_ascii=False),
                json.dumps({"provider": "static", "note": "首版由静态分析生成解释，不调用外部模型。"}, ensure_ascii=False),
                now,
            ),
        )
    report_body["id"] = report_id
    report_body["skillId"] = skill_id
    report_body["skillVersionId"] = version_id
    report_body["reused"] = False
    report_body["createdAt"] = now
    return report_body


def get_report(settings: Settings, report_id: str) -> dict:
    with db_session(settings.db_path) as conn:
        return _load_report(conn, report_id)


def get_file(settings: Settings, report_id: str, file_id: str) -> dict:
    with db_session(settings.db_path) as conn:
        row = conn.execute(
            """
            SELECT f.relative_path, f.content_text, f.file_type, f.size_bytes
            FROM inspector_files f
            JOIN inspector_reports r ON r.version_id = f.version_id
            WHERE r.id = ? AND f.id = ?
            """,
            (report_id, file_id),
        ).fetchone()
    if row is None:
        raise LibraryError(404, "报告里没有这份文件。")
    return {
        "id": file_id,
        "path": row["relative_path"],
        "fileType": row["file_type"],
        "sizeBytes": row["size_bytes"],
        "text": row["content_text"] or "",
    }


def ask_question(settings: Settings, report_id: str, question: str) -> dict:
    text = question.strip()
    if not text:
        raise LibraryError(400, "请先写下问题。")
    if len(text) > 2000:
        raise LibraryError(400, "问题过长。")
    report = get_report(settings, report_id)
    result = answer_from_report(report, text)
    now = _now()
    with db_session(settings.db_path, write=True) as conn:
        conn.execute(
            "INSERT INTO inspector_messages(id, report_id, role, body, evidence_json, created_at) VALUES(?, ?, 'user', ?, '[]', ?)",
            (str(uuid.uuid4()), report_id, text, now),
        )
        conn.execute(
            "INSERT INTO inspector_messages(id, report_id, role, body, evidence_json, created_at) VALUES(?, ?, 'assistant', ?, ?, ?)",
            (str(uuid.uuid4()), report_id, result["answer"], json.dumps(result["evidence"], ensure_ascii=False), now),
        )
    return result


def export_markdown(settings: Settings, report_id: str) -> str:
    report = get_report(settings, report_id)
    lines = [f"# {report['overview'].get('name') or 'Skill'} 学习报告", ""]
    lines.append(report["overview"].get("purpose") or "")
    lines.append("")
    lines.append("本报告来自静态分析。推断已单独标出，不代表真实运行轨迹。")
    lines.append("")
    for section in report.get("sections") or []:
        lines.append(f"## {section['title']}")
        lines.append("")
        for paragraph in section.get("paragraphs") or []:
            lines.append(paragraph)
            lines.append("")
    if report.get("findings"):
        lines.append("## 局限与风险")
        lines.append("")
        for finding in report["findings"]:
            lines.append(f"- {finding['message']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def delete_skill(settings: Settings, skill_id: str) -> dict:
    with db_session(settings.db_path, write=True) as conn:
        deleted = conn.execute("DELETE FROM inspector_skills WHERE id = ?", (skill_id,)).rowcount
    if not deleted:
        raise LibraryError(404, "没有这份 Skill 记录。")
    return {"ok": True}


def parse_frontmatter(text: str) -> tuple[dict[str, str], str, int]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, 1
    end = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        return {}, text, 1
    meta: dict[str, str] = {}
    key = ""
    bucket: list[str] = []

    def flush() -> None:
        nonlocal key, bucket
        if key:
            meta[key] = "\n".join(part for part in bucket if part).strip()
        key = ""
        bucket = []

    for line in lines[1:end]:
        if line.startswith((" ", "\t")) and key:
            bucket.append(line.strip())
            continue
        if ":" in line and not line.startswith((" ", "\t")):
            flush()
            raw_key, _, raw_value = line.partition(":")
            key = raw_key.strip()
            value = raw_value.strip()
            if value not in {"", "|", ">", "|-", ">-"}:
                bucket = [value]
            continue
        if key:
            bucket.append(line.strip())
    flush()
    body = "\n".join(lines[end + 1 :])
    return meta, body, end + 2


def build_report(name: str, description: str, mode: str, files: list[dict], findings: list[dict]) -> dict:
    by_path = {item["relative_path"]: item for item in files}
    skill = by_path.get("SKILL.md")
    if skill is None:
        raise LibraryError(400, "目录里没有 SKILL.md。")
    _meta, body, body_start = parse_frontmatter(skill["text"])
    steps = _steps(body, body_start)
    tools = _tools(files)
    http_tools = [item for item in tools if item["kind"] == "http"]
    if len(http_tools) > 8:
        kept = {id(item) for item in http_tools[:8]}
        tools = [item for item in tools if item["kind"] != "http" or id(item) in kept]
        findings.append({"severity": "warning", "message": "网络地址较多，报告只保留前 8 个。", "evidenceType": "static"})
    nodes = _nodes(description, steps, tools, skill)
    edges = [{"id": f"edge-{index}", "from": nodes[index]["id"], "to": nodes[index + 1]["id"], "label": ""} for index in range(len(nodes) - 1)]
    _attach_evidence(nodes, by_path)
    _attach_evidence(tools, by_path)
    sections = _sections(name, description, mode, files, nodes, tools, findings)
    overview = {
        "name": name,
        "purpose": description or _first_paragraph(body) or "这份 Skill 没有写出用途说明。",
        "triggerConditions": [description] if description else [],
        "limitations": [
            "静态分析只根据文件内容推断流程，不能知道 Agent 运行时实际选择了哪条分支。",
            "单文件分析只读取 SKILL.md，不会把未出现的脚本行为写成事实。" if mode == "quick" else "目录分析只读取授权根目录内的文本文件。",
        ],
        "mode": mode,
        "parserVersion": PARSER_VERSION,
        "fileCount": len(files),
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "overview": overview,
        "nodes": nodes,
        "edges": edges,
        "tools": tools,
        "files": [
            {
                "id": item["id"],
                "path": item["relative_path"],
                "fileType": item["file_type"],
                "sizeBytes": item["size_bytes"],
                "sha256": item["sha256"],
            }
            for item in files
        ],
        "sections": sections,
        "findings": findings,
        "openQuestions": [item["message"] for item in findings if item["severity"] == "unknown"],
    }


def answer_from_report(report: dict, question: str) -> dict:
    terms = _terms(question)
    candidates: list[tuple[int, str, str, dict]] = []
    for node in report.get("nodes") or []:
        candidates.append((_score(terms, f"{node.get('title', '')} {node.get('description', '')}"), "node", node.get("title") or "", node))
    for tool in report.get("tools") or []:
        candidates.append((_score(terms, f"{tool.get('name', '')} {tool.get('purpose', '')}"), "tool", tool.get("name") or "", tool))
    for section in report.get("sections") or []:
        blob = section["title"] + " " + " ".join(section.get("paragraphs") or [])
        candidates.append((_score(terms, blob), "section", section["title"], section))
    ranked = [item for item in candidates if item[0] > 0]
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        return {
            "answer": "当前报告里没有足够证据回答这个问题。静态分析没有看到与问题对应的指令、工具或文件。",
            "evidence": [],
            "claims": [],
            "unknowns": ["报告中没有与问题对应的原文。"],
        }
    picked = ranked[:3]
    evidence = []
    claims = []
    sentences = []
    for _score_value, kind, title, payload in picked:
        refs = payload.get("sourceRefs") or payload.get("source_refs") or []
        if kind == "section":
            sentences.append(f"「{title}」中写到：{(payload.get('paragraphs') or [''])[0]}")
            claims.append({"text": (payload.get("paragraphs") or [""])[0], "evidenceType": "static"})
        else:
            evidence_type = payload.get("evidenceType") or "static"
            sentences.append(f"{title}：{payload.get('description') or payload.get('purpose') or ''}")
            claims.append({"text": payload.get("description") or payload.get("purpose") or title, "evidenceType": evidence_type})
            for ref in refs[:2]:
                if ref not in evidence:
                    evidence.append(ref)
    return {
        "answer": "根据当前这份静态分析报告：" + " ".join(sentence.strip() for sentence in sentences if sentence.strip()),
        "evidence": evidence,
        "claims": claims,
        "unknowns": [] if evidence else ["匹配到了报告中的说明，但没有精确到文件行号。"],
    }


def _collect_files(directory: Path, mode: str) -> tuple[list[dict], list[dict]]:
    findings: list[dict] = []
    selected: list[Path] = []
    skill_md = directory / "SKILL.md"
    selected = [skill_md]
    if mode == "deep":
        for path in directory.rglob("*"):
            if path == skill_md or not path.is_file() or path.is_symlink() or _escapes(directory, path):
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(directory).parts):
                continue
            selected.append(path)
            if len(selected) > MAX_FILES:
                findings.append({"severity": "warning", "message": f"文件超过 {MAX_FILES} 个，其余文件没有纳入这次分析。", "evidenceType": "static"})
                break
    files = []
    for path in selected:
        relative = path.relative_to(directory).as_posix()
        if ".." in Path(relative).parts:
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        skipped = ""
        text = ""
        redacted = False
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != "SKILL.md":
            skipped = "binary"
        elif len(data) > MAX_FILE_BYTES:
            skipped = "too_large"
            findings.append({"severity": "warning", "message": f"{relative} 超过大小限制，没有读取正文。", "evidenceType": "static"})
        else:
            text = data.decode("utf-8", errors="replace")
            text, redacted = _redact(text)
            if redacted:
                findings.append({"severity": "warning", "message": f"{relative} 中有疑似密钥，报告里的正文已脱敏。原始文件没有修改。", "evidenceType": "static"})
            if any(pattern.search(text) for pattern in INJECTION_PATTERNS):
                findings.append({"severity": "warning", "message": f"{relative} 含有要求忽略既有规则的文本。分析时只把它当作不可信内容。", "evidenceType": "static"})
        files.append(
            {
                "relative_path": relative,
                "file_type": path.suffix.lower().lstrip(".") or "markdown",
                "sha256": digest,
                "size_bytes": len(data),
                "text": text,
                "redacted": redacted,
                "skipped": skipped,
            }
        )
    if mode == "deep":
        mentioned = _mentioned_paths(files)
        present = {item["relative_path"] for item in files}
        for relative in sorted(mentioned):
            if relative not in present and not (directory / relative).is_file():
                findings.append({"severity": "unknown", "message": f"指令引用了 {relative}，目录里没有这个文件。", "evidenceType": "inferred"})
    return files, findings


def _steps(body: str, body_start: int) -> list[dict]:
    lines = body.splitlines()
    heading = ""
    heading_line = body_start
    numbered: list[dict] = []
    headings: list[dict] = []
    for offset, line in enumerate(lines):
        absolute = body_start + offset
        if re.match(r"^#{1,3}\s+", line):
            heading = re.sub(r"^#{1,3}\s+", "", line).strip()
            heading_line = absolute
            if heading:
                headings.append({"title": heading[:120], "description": heading, "start_line": absolute, "end_line": absolute, "kind": "step"})
            continue
        matched = re.match(r"^(\d+)[.)]\s+(\S.*)", line.strip())
        if matched:
            title = matched.group(2).strip()
            kind = "decision" if re.search(r"如果|若|假如", title) else "step"
            numbered.append({"title": title[:160], "description": title, "heading": heading, "start_line": absolute, "end_line": absolute, "kind": kind, "heading_line": heading_line})
    return numbered or headings[:12]


def _tools(files: list[dict]) -> list[dict]:
    found: dict[tuple[str, str], dict] = {}
    skill = next((item for item in files if item["relative_path"] == "SKILL.md"), None)
    if skill:
        meta, _body, _start = parse_frontmatter(skill["text"])
        declared = meta.get("tools") or meta.get("allowed-tools") or meta.get("allowed_tools") or ""
        for name in re.split(r"[,，\s]+", declared):
            if name:
                _add_tool(found, name, "cli", "declared", "SKILL.md", 1, "前置信息里声明了这个工具。")
    for item in files:
        if not item["text"]:
            continue
        for index, line in enumerate(item["text"].splitlines(), start=1):
            for kind, pattern, purpose in (
                ("cli", re.compile(r"`((?:python3?|pip3?|npm|npx|curl|gh|git|bash|sh|node|pnpm|yarn)\b[^`]*)`"), "指令中的命令引用。"),
                ("http", re.compile(r"(https?://[^\s)`\"']+)"), "文本中的网络地址。"),
                ("script", re.compile(r"((?:scripts|bin)/[\w./-]+\.(?:py|sh|js|ts))"), "引用了目录中的脚本。"),
                ("mcp", re.compile(r"\b(mcp__[A-Za-z0-9_]+)\b"), "文本中的 MCP 工具名。"),
            ):
                for match in pattern.finditer(line):
                    name = match.group(1).strip()
                    if kind == "http":
                        name = name[:80]
                    _add_tool(found, name, kind, "referenced", item["relative_path"], index, purpose)
    return list(found.values())


def _nodes(description: str, steps: list[dict], tools: list[dict], skill: dict) -> list[dict]:
    nodes = [
        {
            "id": "trigger",
            "nodeType": "trigger",
            "title": "触发与输入",
            "description": description or "使用这份 Skill 时触发。",
            "evidenceType": "static" if description else "inferred",
            "confidence": None,
            "sourceRefs": [{"path": "SKILL.md", "start_line": 1, "end_line": 1, "precision": "line"}] if description else [],
        }
    ]
    for index, step in enumerate(steps, start=1):
        kind = "script" if "脚本" in step["title"] or step["title"].endswith(".py") else step["kind"]
        nodes.append(
            {
                "id": f"step-{index}",
                "nodeType": kind,
                "title": step["title"],
                "description": step["description"],
                "evidenceType": "static",
                "confidence": None,
                "sourceRefs": [{"path": "SKILL.md", "start_line": step["start_line"], "end_line": step["end_line"], "precision": "line"}],
            }
        )
    for index, tool in enumerate(tools[:8], start=1):
        nodes.append(
            {
                "id": f"tool-{index}",
                "nodeType": "tool_call",
                "title": tool["name"],
                "description": tool["purpose"],
                "evidenceType": tool["evidenceType"],
                "confidence": None,
                "sourceRefs": tool["sourceRefs"],
            }
        )
    nodes.append(
        {
            "id": "output",
            "nodeType": "output",
            "title": "最终输出",
            "description": "Skill 完成指令后给出的结果。具体产物以原文中的输出要求为准。",
            "evidenceType": "inferred",
            "confidence": None,
            "sourceRefs": [{"path": skill["relative_path"], "start_line": None, "end_line": None, "precision": "file"}],
        }
    )
    return nodes


def _sections(name: str, description: str, mode: str, files: list[dict], nodes: list[dict], tools: list[dict], findings: list[dict]) -> list[dict]:
    file_lines = [f"{item['relative_path']}（{item['file_type']}，{item['size_bytes']} 字节）" for item in files]
    step_lines = [f"{node['title']}（{node['evidenceType']}）" for node in nodes if node["nodeType"] not in {"trigger", "output"}]
    tool_lines = [f"{tool['name']} · {tool['kind']} · {tool['evidenceType']}" for tool in tools] or ["没有识别到明确的工具声明或调用。"]
    return [
        {"id": "what", "title": "01 Skill 是什么", "paragraphs": [description or f"{name} 没有在前置信息里写明用途。"]},
        {"id": "files", "title": "02 文件结构与职责", "paragraphs": [f"本次为{'单文件' if mode == 'quick' else '目录'}分析，纳入 {len(files)} 个文件。", *file_lines]},
        {"id": "flow", "title": "03 工作流程详解", "paragraphs": step_lines or ["正文里没有编号步骤或标题，无法整理出流程。"]},
        {"id": "tools", "title": "04 工具与依赖", "paragraphs": tool_lines},
        {
            "id": "principle",
            "title": "05 关键设计原理",
            "paragraphs": [
                "流程节点来自 SKILL.md 的标题和编号步骤，证据类型为 static 的内容可以直接回到原文行号。",
                "工具用途和最终输出如果原文没有写明，会标成 inferred，不能当成已经确认的行为。",
            ],
        },
        {"id": "io", "title": "06 输入输出与数据流", "paragraphs": [description or "输入条件见触发说明。", "输出以指令中明确写出的结果为准。没有写明的数据流保持未知。"]},
        {"id": "risk", "title": "07 局限与风险", "paragraphs": [item["message"] for item in findings] or ["这次分析没有发现缺失引用、密钥或提示词注入文本。"]},
        {"id": "summary", "title": "08 学习总结", "paragraphs": [f"先看 SKILL.md 的用途说明，再按流程图核对每一步的原文，最后用工具清单区分声明、引用和推断。"]},
    ]


def _attach_evidence(items: list[dict], by_path: dict[str, dict]) -> None:
    for item in items:
        checked = []
        for ref in item.get("sourceRefs") or []:
            path = ref.get("path")
            target = by_path.get(path or "")
            if target is None:
                checked.append({**ref, "precision": "file_missing", "start_line": None, "end_line": None})
                continue
            line_count = target["text"].count("\n") + 1 if target.get("text") else 0
            start = ref.get("start_line")
            end = ref.get("end_line")
            if isinstance(start, int) and 1 <= start <= line_count:
                checked.append({**ref, "fileId": target.get("id"), "end_line": end if isinstance(end, int) and start <= end <= line_count else start, "precision": "line"})
            else:
                checked.append({"path": path, "fileId": target.get("id"), "start_line": None, "end_line": None, "precision": "file"})
        item["sourceRefs"] = checked


def _add_tool(found: dict, name: str, kind: str, evidence: str, path: str, line: int, purpose: str) -> None:
    key = (kind, name)
    current = found.get(key)
    ref = {"path": path, "start_line": line, "end_line": line, "precision": "line"}
    if current is None:
        found[key] = {"id": f"tool-ref-{len(found) + 1}", "name": name, "kind": kind, "evidenceType": evidence, "purpose": purpose, "sourceRefs": [ref]}
        return
    if ref not in current["sourceRefs"]:
        current["sourceRefs"].append(ref)
    if evidence == "declared":
        current["evidenceType"] = "declared"


def _mentioned_paths(files: list[dict]) -> set[str]:
    found: set[str] = set()
    pattern = re.compile(r"(?<![\w./-])((?:[\w.-]+/)+[\w.-]+\.(?:md|mdx|py|sh|js|ts|json|ya?ml))")
    for item in files:
        for match in pattern.finditer(item["text"] or ""):
            relative = match.group(1)
            if ".." not in Path(relative).parts:
                found.add(relative)
    return found


def _terms(question: str) -> list[str]:
    terms: list[str] = []
    for part in re.findall(r"[\w\u4e00-\u9fff]{2,}", question.lower()):
        terms.append(part)
        if re.search(r"[\u4e00-\u9fff]", part):
            terms.extend(part[index : index + 2] for index in range(len(part) - 1))
    return terms


def _score(terms: list[str], text: str) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if term in lowered)


def _first_paragraph(body: str) -> str:
    for block in re.split(r"\n\s*\n", body.strip()):
        cleaned = block.strip()
        if cleaned and not cleaned.startswith("#"):
            return cleaned[:400]
    return ""


def _redact(text: str) -> tuple[str, bool]:
    redacted = False
    for pattern in SECRET_PATTERNS:
        text, count = pattern.subn("[已脱敏]", text)
        redacted = redacted or count > 0
    return text, redacted


def _snapshot_hash(mode: str, files: list[dict]) -> str:
    digest = hashlib.sha256()
    digest.update(mode.encode())
    for item in sorted(files, key=lambda entry: entry["relative_path"]):
        digest.update(item["relative_path"].encode())
        digest.update(item["sha256"].encode())
    return digest.hexdigest()


def _skill_directory(raw_path: str) -> Path:
    if not raw_path or "\x00" in raw_path:
        raise LibraryError(400, "请选择 SKILL.md 或包含它的目录。")
    path = Path(raw_path).expanduser()
    try:
        path = path.resolve()
    except OSError as exc:
        raise LibraryError(400, "无法读取指定的 Skill 文件。") from exc
    if path.is_file() and path.name == "SKILL.md":
        path = path.parent
    skill_md = path / "SKILL.md"
    if not path.is_dir() or not skill_md.is_file():
        raise LibraryError(400, "目录里没有 SKILL.md。")
    if skill_md.is_symlink() or _escapes(path, skill_md):
        raise LibraryError(400, "SKILL.md 指向了目录之外。")
    return path


def _mode(mode: str) -> str:
    if mode not in {"quick", "deep"}:
        raise LibraryError(400, "分析方式只能是快速分析或深度分析。")
    return mode


def _skill_roots() -> list[tuple[Path, str]]:
    home = Path.home()
    return [
        (home / ".cursor" / "skills", "Cursor"),
        (home / ".claude" / "skills", "Claude"),
        (home / ".agents" / "skills", "Agents"),
        (home / ".codex" / "skills", "Codex"),
    ]


def _catalog_item(directory: Path, label: str, record: dict | None) -> dict:
    meta, _body, _start = parse_frontmatter(_read_skill(directory / "SKILL.md"))
    status = "discovered"
    if record:
        status = _change_status(directory, record)
    return {
        "id": None if record is None else record["id"],
        "name": str(meta.get("name") or directory.name),
        "description": str(meta.get("description") or "")[:280],
        "path": str(directory),
        "source_label": label,
        "readable": True,
        "status": status,
        "report_id": None if record is None else record["report_id"],
        "analyzed_at": None if record is None else record["analyzed_at"],
        "mode": None if record is None else record["mode"],
    }


def _change_status(directory: Path, record: dict) -> str:
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        return "missing"
    digest = hashlib.sha256(skill_md.read_bytes()).hexdigest()
    if digest != record.get("skill_sha256"):
        return "changed"
    return "analyzed"


def _imported_index(settings: Settings) -> dict[str, dict]:
    with db_session(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.name, s.description, s.source_uri, r.id AS report_id, r.created_at AS analyzed_at, v.mode, f.content_hash AS skill_sha256
            FROM inspector_skills s
            LEFT JOIN inspector_versions v ON v.id = (
              SELECT id FROM inspector_versions WHERE skill_id = s.id ORDER BY created_at DESC LIMIT 1
            )
            LEFT JOIN inspector_reports r ON r.version_id = v.id
            LEFT JOIN inspector_files f ON f.version_id = v.id AND f.relative_path = 'SKILL.md'
            """
        ).fetchall()
    return {
        row["source_uri"]: {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "report_id": row["report_id"],
            "analyzed_at": row["analyzed_at"],
            "mode": row["mode"],
            "skill_sha256": row["skill_sha256"],
        }
        for row in rows
    }


def _load_report(conn, report_id: str) -> dict:
    row = conn.execute(
        """
        SELECT r.id, r.version_id, r.created_at, r.report_json, s.id AS skill_id, s.source_uri
        FROM inspector_reports r
        JOIN inspector_versions v ON v.id = r.version_id
        JOIN inspector_skills s ON s.id = v.skill_id
        WHERE r.id = ?
        """,
        (report_id,),
    ).fetchone()
    if row is None:
        raise LibraryError(404, "没有这份学习报告。")
    body = json.loads(row["report_json"])
    body["id"] = row["id"]
    body["skillId"] = row["skill_id"]
    body["skillVersionId"] = row["version_id"]
    body["sourcePath"] = row["source_uri"]
    body["createdAt"] = row["created_at"]
    body["reused"] = False
    return body


def _read_skill(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > MAX_FILE_BYTES:
        data = data[:MAX_FILE_BYTES]
    return data.decode("utf-8", errors="replace")


def _escapes(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return True
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnalyzeIn(BaseModel):
    path: str
    mode: str = "quick"
    force: bool = False


class QuestionIn(BaseModel):
    question: str


def register_inspector(app, settings: Settings, require_token) -> None:
    @app.get("/api/inspector/skills", dependencies=[Depends(require_token)])
    def list_inspector_skills():
        return discover_skills(settings)

    @app.post("/api/inspector/analyses", dependencies=[Depends(require_token)])
    def create_inspector_analysis(body: AnalyzeIn):
        return analyze_skill(settings, body.path, body.mode, force=body.force)

    @app.get("/api/inspector/reports/{report_id}", dependencies=[Depends(require_token)])
    def read_inspector_report(report_id: str):
        return get_report(settings, report_id)

    @app.get("/api/inspector/reports/{report_id}/files/{file_id}", dependencies=[Depends(require_token)])
    def read_inspector_file(report_id: str, file_id: str):
        return get_file(settings, report_id, file_id)

    @app.post("/api/inspector/reports/{report_id}/questions", dependencies=[Depends(require_token)])
    def ask_inspector(report_id: str, body: QuestionIn):
        return ask_question(settings, report_id, body.question)

    @app.get("/api/inspector/reports/{report_id}/export", dependencies=[Depends(require_token)])
    def export_inspector(report_id: str):
        return PlainTextResponse(export_markdown(settings, report_id), media_type="text/markdown; charset=utf-8")

    @app.delete("/api/inspector/skills/{skill_id}", dependencies=[Depends(require_token)])
    def remove_inspector_skill(skill_id: str):
        return delete_skill(settings, skill_id)
