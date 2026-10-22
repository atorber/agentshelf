from __future__ import annotations

import hmac
import os
import secrets
import stat
from pathlib import Path


def ensure_token(path: Path) -> str:
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            _tighten(path)
            return token
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    _tighten(path)
    return token


def read_token(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def check_token(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def _tighten(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        return
