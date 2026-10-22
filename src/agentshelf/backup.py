from __future__ import annotations

import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from agentshelf.config import Settings, app_version
from agentshelf.db import integrity_ok
from agentshelf.errors import LibraryError

BACKUP_VERSION = 1


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def create_backup(settings: Settings) -> dict:
    settings.ensure_dirs()
    stamp = _stamp()
    dest = settings.backups_dir / f"agentshelf-{stamp}.zip"
    partial_db = settings.backups_dir / f".partial-{stamp}.db"
    partial_zip = settings.backups_dir / f".partial-{stamp}.zip"
    source = sqlite3.connect(settings.db_path)
    target = sqlite3.connect(partial_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    manifest = {
        "agentshelf_backup": BACKUP_VERSION,
        "app_version": app_version(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with zipfile.ZipFile(partial_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(partial_db, "library.db")
        if settings.objects_dir.exists():
            for item in settings.objects_dir.rglob("*"):
                if item.is_file():
                    archive.write(item, f"objects/{item.relative_to(settings.objects_dir).as_posix()}")
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    partial_db.unlink(missing_ok=True)
    os.replace(partial_zip, dest)
    return {
        "name": dest.name,
        "size_bytes": dest.stat().st_size,
        "created_at": manifest["created_at"],
    }


def list_backups(settings: Settings) -> list[dict]:
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(settings.backups_dir.glob("agentshelf-*.zip"), reverse=True):
        if not _backup_name_ok(path.name):
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        )
    return items


def resolve_backup(settings: Settings, name: str) -> Path:
    if not _backup_name_ok(name):
        raise LibraryError(400, "备份名称无效")
    path = settings.backups_dir / name
    if not path.is_file():
        raise LibraryError(404, "备份不存在")
    return path


def restore_backup(settings: Settings, zip_path: Path) -> None:
    if not zip_path.is_file():
        raise LibraryError(404, "备份文件不存在")
    staging = settings.data_dir / f".restore-{_stamp()}"
    aside = settings.data_dir / f".recovery-{_stamp()}"
    staging.mkdir(parents=True, exist_ok=True)
    try:
        _extract_backup(zip_path, staging)
        restored_db = staging / "library.db"
        if not integrity_ok(restored_db):
            raise LibraryError(400, "备份中的数据库未通过完整性检查")
        _checkpoint(settings.db_path)
        aside.mkdir(parents=True, exist_ok=True)
        _move_current_aside(settings, aside)
        os.replace(restored_db, settings.db_path)
        objects_src = staging / "objects"
        if objects_src.exists():
            os.replace(objects_src, settings.objects_dir)
        else:
            settings.objects_dir.mkdir(parents=True, exist_ok=True)
        if not integrity_ok(settings.db_path):
            raise LibraryError(500, "恢复后的数据库完整性检查失败")
    except Exception:
        _rollback(settings, aside)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(aside, ignore_errors=True)


def _backup_name_ok(name: str) -> bool:
    if Path(name).name != name:
        return False
    if not name.startswith("agentshelf-") or not name.endswith(".zip"):
        return False
    stamp = name[len("agentshelf-") : -len(".zip")]
    return len(stamp) == 15 and stamp[8] == "-" and stamp.replace("-", "").isdigit()


def _extract_backup(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        for name in names:
            _ensure_safe_member(name)
        if "manifest.json" not in names or "library.db" not in names:
            raise LibraryError(400, "备份缺少 manifest.json 或 library.db")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("agentshelf_backup") != BACKUP_VERSION:
            raise LibraryError(400, "无法识别的备份版本")
        for name in names:
            archive.extract(name, dest)


def _ensure_safe_member(name: str) -> None:
    if not name or name.startswith("/") or name.startswith("\\"):
        raise LibraryError(400, "备份包包含不安全路径")
    parts = Path(name).parts
    if ".." in parts:
        raise LibraryError(400, "备份包包含不安全路径")


def _checkpoint(db_path: Path) -> None:
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _move_current_aside(settings: Settings, aside: Path) -> None:
    for name in ("library.db", "library.db-wal", "library.db-shm"):
        current = settings.data_dir / name
        if current.exists():
            os.replace(current, aside / name)
    if settings.objects_dir.exists():
        os.replace(settings.objects_dir, aside / "objects")


def _rollback(settings: Settings, aside: Path) -> None:
    if not aside.exists():
        return
    broken = settings.data_dir / "library.db"
    if broken.exists() and (aside / "library.db").exists():
        bad = settings.data_dir / "library.db.failed"
        if bad.exists():
            bad.unlink()
        os.replace(broken, bad)
    for name in ("library.db", "library.db-wal", "library.db-shm"):
        saved = aside / name
        if saved.exists():
            os.replace(saved, settings.data_dir / name)
    saved_objects = aside / "objects"
    if saved_objects.exists():
        if settings.objects_dir.exists():
            shutil.rmtree(settings.objects_dir, ignore_errors=True)
        os.replace(saved_objects, settings.objects_dir)
