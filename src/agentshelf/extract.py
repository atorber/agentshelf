from __future__ import annotations

import csv
import io
import json
from html.parser import HTMLParser
from pathlib import Path

TEXT_LIMIT = 500_000
PREVIEW_TEXT_LIMIT = 200_000
CSV_PREVIEW_ROWS = 200
CSV_PREVIEW_COLS = 40


def extract_text(path: Path, kind: str) -> tuple[str, str, str]:
    """返回 (text, status, error)。损坏文件只影响本条索引，不向外抛出。"""
    try:
        if kind == "pdf":
            return _pdf_text(path), "done", ""
        if kind == "html":
            return _html_text(path), "done", ""
        if kind in {"markdown", "text", "csv", "json"}:
            return _read_text(path), "done", ""
        if kind == "image":
            return "", "skipped", ""
        return "", "skipped", ""
    except Exception as exc:  # noqa: BLE001 — 预览与索引必须吞掉单文件错误
        return "", "failed", str(exc)[:300]


def _read_text(path: Path) -> str:
    data = path.read_bytes()[: TEXT_LIMIT + 1]
    text = data.decode("utf-8", errors="replace")
    if len(text) > TEXT_LIMIT:
        return text[:TEXT_LIMIT]
    return text


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    total = 0
    for index, page in enumerate(reader.pages):
        if index >= 40 or total >= TEXT_LIMIT:
            break
        try:
            piece = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            piece = ""
        parts.append(piece)
        total += len(piece)
    return "\n".join(parts)[:TEXT_LIMIT]


def preview_payload(path: Path, kind: str) -> dict:
    if kind == "html":
        text = _html_text(path)
        truncated = len(text) > PREVIEW_TEXT_LIMIT
        return {"text": text[:PREVIEW_TEXT_LIMIT], "truncated": truncated}
    if kind in {"markdown", "text"}:
        text = _read_text(path)
        truncated = len(text) > PREVIEW_TEXT_LIMIT
        return {"text": text[:PREVIEW_TEXT_LIMIT], "truncated": truncated}
    if kind == "csv":
        text = _read_text(path)
        rows, truncated = _csv_rows(text)
        return {"text": text[:PREVIEW_TEXT_LIMIT], "rows": rows, "truncated": truncated or len(text) > PREVIEW_TEXT_LIMIT}
    if kind == "json":
        text = _read_text(path)
        truncated = len(text) > PREVIEW_TEXT_LIMIT
        shown = text[:PREVIEW_TEXT_LIMIT]
        parsed = None
        error = ""
        if not truncated:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                error = "JSON 无法解析，已按文本展示"
        return {"text": shown, "json": parsed, "truncated": truncated, "error": error}
    if kind == "pdf":
        page_count = None
        error = ""
        try:
            from pypdf import PdfReader

            page_count = len(PdfReader(str(path)).pages)
        except Exception as exc:  # noqa: BLE001
            error = f"PDF 结构无法读取：{exc}"[:300]
        return {"page_count": page_count, "error": error}
    if kind in {"image", "video"}:
        return {}
    return {"error": "此格式暂不支持直接预览，可以下载原始文件。"}


class _VisibleHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag.lower() in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "title"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _html_text(path: Path) -> str:
    parser = _VisibleHtml()
    parser.feed(_read_text(path))
    return " ".join("".join(parser.parts).split())[:TEXT_LIMIT]


def _csv_rows(text: str) -> tuple[list[list[str]], bool]:
    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = []
    truncated = False
    for index, row in enumerate(reader):
        if index >= CSV_PREVIEW_ROWS:
            truncated = True
            break
        rows.append([cell[:500] for cell in row[:CSV_PREVIEW_COLS]])
    return rows, truncated
