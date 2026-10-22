from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from agentshelf.backup import _backup_name_ok, _checkpoint, create_backup
from agentshelf.config import Settings
from agentshelf.db import integrity_ok
from agentshelf.errors import LibraryError
from agentshelf.s3 import S3Client
from agentshelf.security import write_private

_SKIP_FILES = {"token", "cloud.json", "runtime.json", "desktop.json"}
_SKIP_DIRS = {"logs", "staging"}
_SYNC_TREES = ("objects", "backups", "models")

_BUCKET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{1,61}[A-Za-z0-9]$")
_REGION = re.compile(r"^[a-z0-9-]{1,32}$")


@dataclass
class CloudConfig:
    endpoint: str
    region: str
    bucket: str
    prefix: str
    access_key_id: str
    secret_access_key: str
    path_style: bool
    sync_bucket: str = ""
    sync_prefix: str = ""

    def public(self) -> dict:
        connected = bool(self.access_key_id and self.secret_access_key)
        return {
            "configured": bool(self.bucket and connected),
            "endpoint": self.endpoint,
            "region": self.region,
            "bucket": self.bucket,
            "prefix": self.prefix,
            "access_key_id": self.access_key_id,
            "secret_set": bool(self.secret_access_key),
            "path_style": self.path_style,
            "sync_bucket": self.sync_bucket,
            "sync_prefix": self.sync_prefix,
            "sync_configured": bool(connected and self.sync_bucket and self.sync_prefix),
        }


def empty_config() -> CloudConfig:
    return CloudConfig("", "us-east-1", "", "", "", "", True)


def cloud_path(settings: Settings) -> Path:
    return settings.data_dir / "cloud.json"


def load_config(settings: Settings) -> CloudConfig:
    path = cloud_path(settings)
    if not path.is_file():
        return empty_config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LibraryError(500, "云端配置无法读取") from exc
    if not isinstance(raw, dict):
        raise LibraryError(500, "云端配置无法读取")
    return CloudConfig(
        endpoint=str(raw.get("endpoint") or ""),
        region=str(raw.get("region") or "us-east-1"),
        bucket=str(raw.get("bucket") or ""),
        prefix=str(raw.get("prefix") or ""),
        access_key_id=str(raw.get("access_key_id") or ""),
        secret_access_key=str(raw.get("secret_access_key") or ""),
        path_style=bool(raw.get("path_style", True)),
        sync_bucket=str(raw.get("sync_bucket") or ""),
        sync_prefix=str(raw.get("sync_prefix") or ""),
    )


def save_config(settings: Settings, incoming: dict) -> CloudConfig:
    current = load_config(settings)
    secret = str(incoming.get("secret_access_key") or "").strip() or current.secret_access_key
    config = _validate(
        endpoint=str(incoming.get("endpoint") or ""),
        region=str(incoming.get("region") or "us-east-1"),
        bucket=str(incoming.get("bucket") or ""),
        prefix=str(incoming.get("prefix") or ""),
        access_key_id=str(incoming.get("access_key_id") or ""),
        secret_access_key=secret,
        path_style=bool(incoming.get("path_style", True)),
    )
    stored = _stored(config)
    stored["sync_bucket"] = current.sync_bucket
    stored["sync_prefix"] = current.sync_prefix
    write_private(cloud_path(settings), json.dumps(stored, ensure_ascii=False, indent=2) + "\n")
    return CloudConfig(**stored)


def save_sync(settings: Settings, incoming: dict) -> CloudConfig:
    current = load_config(settings)
    if not current.access_key_id or not current.secret_access_key:
        raise LibraryError(400, "请先保存 S3 连接")
    bucket = str(incoming.get("bucket") or "").strip()
    if not _BUCKET.fullmatch(bucket):
        raise LibraryError(400, "Bucket 名称无效")
    prefix = _prefix(str(incoming.get("prefix") or ""))
    if not prefix:
        raise LibraryError(400, "请指定云同步目录")
    stored = _stored(current)
    stored["sync_bucket"] = bucket
    stored["sync_prefix"] = prefix
    write_private(cloud_path(settings), json.dumps(stored, ensure_ascii=False, indent=2) + "\n")
    return CloudConfig(**stored)


def test_connection(settings: Settings, incoming: dict | None = None) -> dict:
    config = _config_for_use(settings, incoming)
    client = _client(config)
    client.list_objects(config.prefix)
    location = f"{config.bucket}/{config.prefix}" if config.prefix else config.bucket
    return {"ok": True, "message": f"已连接到 {location}"}


def backup_to_cloud(settings: Settings) -> dict:
    config = _config_for_use(settings, None)
    created = create_backup(settings)
    path = settings.backups_dir / created["name"]
    key = f"{config.prefix}{created['name']}"
    try:
        _client(config).put_file(key, path)
    except LibraryError as exc:
        raise LibraryError(exc.status, f"本地备份已创建，上传失败：{exc.message}") from exc
    return {**created, "key": key, "prefix": config.prefix}


def list_cloud_backups(settings: Settings) -> list[dict]:
    config = _config_for_use(settings, None)
    items = []
    for item in _client(config).list_objects(config.prefix):
        if _backup_name_ok(item["name"]):
            items.append(item)
    return items


def push_storage(settings: Settings) -> dict:
    config = _sync_ready(settings)
    local = _storage_files(settings)
    client = _client(config, bucket=config.sync_bucket)
    remote = {item["name"]: item for item in client.list_tree(config.sync_prefix)}
    uploaded = 0
    for rel, path in local.items():
        size = path.stat().st_size
        current = remote.get(rel)
        if current and current["size_bytes"] == size and current["etag"] == _md5_file(path):
            continue
        client.put_file(f"{config.sync_prefix}{rel}", path, content_type="application/octet-stream")
        uploaded += 1
    deleted = 0
    for rel in remote:
        if rel not in local and _sync_rel_ok(rel):
            client.delete(f"{config.sync_prefix}{rel}")
            deleted += 1
    return {"uploaded": uploaded, "deleted": deleted, "files": len(local), "prefix": config.sync_prefix, "bucket": config.sync_bucket}


def download_storage(settings: Settings) -> Path:
    config = _sync_ready(settings)
    client = _client(config, bucket=config.sync_bucket)
    chosen = []
    for item in client.list_tree(config.sync_prefix):
        if _sync_rel_ok(item["name"]):
            chosen.append(item)
    if not any(item["name"] == "library.db" for item in chosen):
        raise LibraryError(400, "云端目录里没有 library.db")
    staging = settings.data_dir / f".sync-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        for item in chosen:
            dest = staging / item["name"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            client.download(f"{config.sync_prefix}{item['name']}", dest)
        if not integrity_ok(staging / "library.db"):
            raise LibraryError(400, "云端数据库未通过完整性检查")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def install_storage_tree(settings: Settings, staging: Path) -> None:
    database = staging / "library.db"
    if not database.is_file() or not integrity_ok(database):
        raise LibraryError(400, "云端数据库未通过完整性检查")
    aside = settings.data_dir / f".sync-aside-{uuid.uuid4().hex}"
    aside.mkdir()
    try:
        _checkpoint(settings.db_path)
        for name in ("library.db", "library.db-wal", "library.db-shm"):
            current = settings.data_dir / name
            if current.exists():
                os.replace(current, aside / name)
        for name in _SYNC_TREES:
            current = settings.data_dir / name
            if current.exists():
                os.replace(current, aside / name)
        os.replace(database, settings.db_path)
        for name in _SYNC_TREES:
            source = staging / name
            target = settings.data_dir / name
            if source.exists():
                os.replace(source, target)
            else:
                target.mkdir(parents=True, exist_ok=True)
        if not integrity_ok(settings.db_path):
            raise LibraryError(500, "拉取后的数据库完整性检查失败")
    except Exception:
        _restore_aside(settings, aside)
        raise
    finally:
        shutil.rmtree(aside, ignore_errors=True)


def download_cloud_backup(settings: Settings, name: str) -> Path:
    if not _backup_name_ok(name):
        raise LibraryError(400, "备份名称无效")
    config = _config_for_use(settings, None)
    dest = settings.backups_dir / f".cloud-{uuid.uuid4().hex}.zip"
    _client(config).download(f"{config.prefix}{name}", dest)
    return dest


def _config_for_use(settings: Settings, incoming: dict | None) -> CloudConfig:
    if incoming is None:
        config = load_config(settings)
    else:
        current = load_config(settings)
        secret = str(incoming.get("secret_access_key") or "").strip() or current.secret_access_key
        config = _validate(
            endpoint=str(incoming.get("endpoint") or ""),
            region=str(incoming.get("region") or "us-east-1"),
            bucket=str(incoming.get("bucket") or ""),
            prefix=str(incoming.get("prefix") or ""),
            access_key_id=str(incoming.get("access_key_id") or ""),
            secret_access_key=secret,
            path_style=bool(incoming.get("path_style", True)),
        )
    if not config.bucket or not config.access_key_id or not config.secret_access_key:
        raise LibraryError(400, "请先填写并保存 S3 配置")
    return config


def _validate(*, endpoint: str, region: str, bucket: str, prefix: str, access_key_id: str, secret_access_key: str, path_style: bool) -> CloudConfig:
    endpoint = endpoint.strip().rstrip("/")
    region = (region.strip() or "us-east-1").lower()
    bucket = bucket.strip()
    access_key_id = access_key_id.strip()
    secret_access_key = secret_access_key.strip()
    if endpoint:
        parts = urlsplit(endpoint)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"}:
            raise LibraryError(400, "访问地址需要是 http 或 https 的主机地址")
        endpoint = f"{parts.scheme}://{parts.netloc}"
    else:
        endpoint = f"https://s3.{region}.amazonaws.com"
    if not _REGION.fullmatch(region):
        raise LibraryError(400, "区域格式无效")
    if not _BUCKET.fullmatch(bucket):
        raise LibraryError(400, "Bucket 名称无效")
    if not access_key_id or any(char in access_key_id for char in "\r\n"):
        raise LibraryError(400, "请填写 Access Key")
    if not secret_access_key or any(char in secret_access_key for char in "\r\n"):
        raise LibraryError(400, "请填写 Secret Key")
    return CloudConfig(endpoint, region, bucket, _prefix(prefix), access_key_id, secret_access_key, path_style)


def _prefix(value: str) -> str:
    text = value.strip().replace("\\", "/")
    while text.startswith("/"):
        text = text[1:]
    parts = [part for part in text.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise LibraryError(400, "目录不能包含 ..")
    if any(any(char in part for char in "\r\n") for part in parts):
        raise LibraryError(400, "目录无效")
    return f"{'/'.join(parts)}/" if parts else ""


def _stored(config: CloudConfig) -> dict:
    shown_endpoint = "" if config.endpoint == f"https://s3.{config.region}.amazonaws.com" else config.endpoint
    return {
        "endpoint": shown_endpoint,
        "region": config.region,
        "bucket": config.bucket,
        "prefix": config.prefix,
        "access_key_id": config.access_key_id,
        "secret_access_key": config.secret_access_key,
        "path_style": config.path_style,
    }


def _client(config: CloudConfig, transport=None, bucket: str | None = None) -> S3Client:
    endpoint = config.endpoint or f"https://s3.{config.region}.amazonaws.com"
    return S3Client(
        endpoint=endpoint,
        region=config.region,
        bucket=bucket or config.bucket,
        access_key_id=config.access_key_id,
        secret_access_key=config.secret_access_key,
        path_style=config.path_style,
        transport=transport,
    )


def _sync_ready(settings: Settings) -> CloudConfig:
    config = load_config(settings)
    if not config.access_key_id or not config.secret_access_key:
        raise LibraryError(400, "请先保存 S3 连接")
    if not _BUCKET.fullmatch(config.sync_bucket) or not config.sync_prefix:
        raise LibraryError(400, "请先保存云同步目录")
    return config


def _storage_files(settings: Settings) -> dict[str, Path]:
    _checkpoint(settings.db_path)
    found: dict[str, Path] = {}
    root = settings.data_dir
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if relative.parts[0] in _SKIP_DIRS or relative.name in _SKIP_FILES:
            continue
        if relative.name.endswith(("-wal", "-shm")):
            continue
        key = relative.as_posix()
        if _sync_rel_ok(key):
            found[key] = path
    if "library.db" not in found:
        raise LibraryError(500, "本地数据库不存在")
    return found


def _sync_rel_ok(name: str) -> bool:
    if not name or name.startswith("/") or any(char in name for char in "\\\r\n"):
        return False
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    if name == "library.db":
        return True
    return bool(path.parts) and path.parts[0] in _SYNC_TREES


def _md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _restore_aside(settings: Settings, aside: Path) -> None:
    if not aside.exists():
        return
    for name in ("library.db", "library.db-wal", "library.db-shm"):
        saved = aside / name
        current = settings.data_dir / name
        if not saved.exists():
            continue
        if current.exists():
            current.unlink()
        os.replace(saved, current)
    for name in _SYNC_TREES:
        saved = aside / name
        current = settings.data_dir / name
        if not saved.exists():
            continue
        if current.exists():
            shutil.rmtree(current)
        os.replace(saved, current)
