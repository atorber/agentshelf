from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs

from agentshelf import __version__

APP_NAME = "AgentShelf"
DEFAULT_PORT = 8765
PORT_SCAN_END = 8865
DEFAULT_MAX_UPLOAD = 200 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD
    sync_index: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def objects_dir(self) -> Path:
        return self.data_dir / "objects"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "token"

    @property
    def runtime_path(self) -> Path:
        return self.data_dir / "runtime.json"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.objects_dir,
            self.staging_dir,
            self.backups_dir,
            self.logs_dir,
            self.models_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def default_data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False, ensure_exists=False))


def load_settings() -> Settings:
    override = os.environ.get("AGENTSHELF_DATA_DIR", "").strip()
    data_dir = Path(override).expanduser() if override else default_data_dir()
    host = os.environ.get("AGENTSHELF_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("AgentShelf 只允许监听回环地址")
    port = int(os.environ.get("AGENTSHELF_PORT", str(DEFAULT_PORT)))
    max_upload = int(os.environ.get("AGENTSHELF_MAX_UPLOAD", str(DEFAULT_MAX_UPLOAD)))
    sync_index = os.environ.get("AGENTSHELF_SYNC_INDEX", "").strip() in {"1", "true", "yes"}
    return Settings(
        data_dir=data_dir,
        host="127.0.0.1",
        port=port,
        max_upload_bytes=max_upload,
        sync_index=sync_index,
    )


def app_version() -> str:
    return __version__
