from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from agentshelf.errors import LibraryError


def free_bytes(path: Path) -> int:
    target = path if path.exists() else path.parent
    return shutil.disk_usage(target).free


def ensure_space(path: Path, needed: int) -> None:
    if free_bytes(path) < needed + 32 * 1024 * 1024:
        raise LibraryError(507, "磁盘剩余空间不足，已拒绝写入")


def safe_filename(filename: str) -> str:
    name = Path(filename or "").name.strip()
    if not name or name in {".", ".."} or "\x00" in name:
        raise LibraryError(400, "文件名无效")
    return name[:180]


def object_path(objects_dir: Path, sha256: str) -> Path:
    return objects_dir / sha256[:2] / sha256


def relative_object_path(sha256: str) -> str:
    return f"{sha256[:2]}/{sha256}"


def commit_blob(staging: Path, objects_dir: Path, sha256: str) -> tuple[Path, bool]:
    """把暂存文件移动到内容寻址目录。已存在则复用，不重复保存物理文件。"""
    dest = object_path(objects_dir, sha256)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        staging.unlink(missing_ok=True)
        return dest, False
    tmp = dest.with_name(dest.name + ".part")
    if tmp.exists():
        tmp.unlink()
    os.replace(staging, tmp)
    os.replace(tmp, dest)
    return dest, True


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guess_mime(filename: str, kind: str, head: bytes) -> str:
    import mimetypes

    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if kind == "markdown":
        return "text/markdown"
    if kind == "html":
        return "text/html"
    if kind == "csv":
        return "text/csv"
    if kind == "json":
        return "application/json"
    if kind == "text":
        return "text/plain"
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def sniff_preview_kind(path: Path, filename: str, mime: str) -> str:
    head = b""
    try:
        with path.open("rb") as handle:
            head = handle.read(64)
    except OSError:
        return "unsupported"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff") or head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image"
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image"
    ext = Path(filename).suffix.lower()
    mime_l = (mime or "").lower()
    if ext == ".svg" or mime_l == "image/svg+xml":
        return "unsupported"
    if ext in {".html", ".htm"} or mime_l == "text/html":
        return "html"
    if ext in {".md", ".markdown"} or mime_l == "text/markdown":
        return "markdown"
    if ext == ".csv" or mime_l == "text/csv":
        return "csv"
    if ext == ".json" or mime_l == "application/json":
        return "json"
    if ext in {".txt", ".log", ".text"} or mime_l.startswith("text/"):
        return "text"
    if ext in {".mp4", ".webm", ".mov", ".m4v", ".ogv"} or mime_l.startswith("video/"):
        return "video"
    if mime_l.startswith("image/"):
        return "unsupported"
    return "unsupported"
