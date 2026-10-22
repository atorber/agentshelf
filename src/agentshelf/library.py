from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agentshelf.backup import create_backup, list_backups, resolve_backup, restore_backup
from agentshelf.config import Settings, app_version
from agentshelf.db import db_session, init_db, quick_check_ok
from agentshelf.errors import LibraryError
from agentshelf.extract import extract_text, preview_payload
from agentshelf.security import ensure_token
from agentshelf.semantic import (
    Embedder,
    cosine,
    load_local_embedder,
    pack_vector,
    sentence_transformers_available,
    unpack_vector,
    validate_model_dir,
)
from agentshelf.storage import (
    commit_blob,
    directory_size,
    guess_mime,
    relative_object_path,
    safe_filename,
    sha256_file,
    sniff_preview_kind,
)

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
logger = logging.getLogger("agentshelf")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_tags(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in raw.split(",") if part.strip()]


def make_snippet(text: str, query: str, window: int = 42) -> str:
    if not text:
        return ""
    haystack = text.replace("\n", " ")
    index = haystack.lower().find(query.lower())
    if index < 0:
        clipped = haystack[: window * 2].strip()
        return clipped + ("…" if len(haystack) > window * 2 else "")
    start = max(0, index - window)
    end = min(len(haystack), index + len(query) + window)
    prefix = "…" if start else ""
    suffix = "…" if end < len(haystack) else ""
    rel = index - start
    chunk = haystack[start:end]
    return prefix + chunk[:rel] + "【" + chunk[rel : rel + len(query)] + "】" + chunk[rel + len(query) :] + suffix


def fts_match_query(text: str) -> str | None:
    cleaned = "".join(ch for ch in text if ch not in {'"', "'", "*", ":", "(", ")", "^", "{", "}"})
    cleaned = " ".join(cleaned.split())
    if len(cleaned) < 3:
        return None
    return f'"{cleaned}"'


def like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class Library:
    def __init__(self, settings: Settings, embedder: Embedder | None = None) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self.token = ensure_token(settings.token_path)
        self.tokenizer = init_db(settings.db_path)
        self._embedder = embedder
        self._status_cache: tuple[float, dict] | None = None
        self.maintenance = False
        self._gc_staging()

    def require_available(self) -> None:
        if self.maintenance:
            raise LibraryError(503, "正在恢复备份，请稍后再试")

    def status(self) -> dict:
        now = time.monotonic()
        if self._status_cache is not None and now - self._status_cache[0] < 3:
            return self._status_cache[1]
        db_ok = quick_check_ok(self.settings.db_path)
        with db_session(self.settings.db_path) as conn:
            job_rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
            artifact_count = conn.execute("SELECT COUNT(*) AS n FROM artifacts").fetchone()["n"]
            blob_count = conn.execute("SELECT COUNT(*) AS n FROM file_objects").fetchone()["n"]
            version_count = conn.execute("SELECT COUNT(*) AS n FROM artifact_versions").fetchone()["n"]
            recent_jobs = conn.execute(
                """
                SELECT id, kind, status, error, attempts, created_at, updated_at
                FROM jobs ORDER BY id DESC LIMIT 8
                """
            ).fetchall()
            semantic = self._semantic_view(conn)
        jobs = {row["status"]: row["n"] for row in job_rows}
        db_bytes = _file_size(self.settings.db_path) + _file_size(self.settings.db_path.with_name("library.db-wal"))
        with db_session(self.settings.db_path) as conn:
            objects_bytes = int(conn.execute("SELECT COALESCE(SUM(size_bytes), 0) AS n FROM file_objects").fetchone()["n"])
        backup_bytes = directory_size(self.settings.backups_dir)
        payload = {
            "version": app_version(),
            "host": self.settings.host,
            "data_dir": str(self.settings.data_dir),
            "db_ok": db_ok,
            "fts_tokenizer": self.tokenizer,
            "jobs": {
                "pending": jobs.get("pending", 0),
                "running": jobs.get("running", 0),
                "failed": jobs.get("failed", 0),
                "done": jobs.get("done", 0),
                "recent": [dict(row) for row in recent_jobs],
            },
            "storage": {
                "data_dir": str(self.settings.data_dir),
                "db_bytes": db_bytes,
                "objects_bytes": objects_bytes,
                "backup_bytes": backup_bytes,
                "total_bytes": db_bytes + objects_bytes + backup_bytes,
                "artifact_count": artifact_count,
                "version_count": version_count,
                "blob_count": blob_count,
            },
            "semantic": semantic,
        }
        self._status_cache = (now, payload)
        return payload

    def list_jobs(self) -> list[dict]:
        with db_session(self.settings.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, kind, status, error, attempts, created_at, updated_at
                FROM jobs ORDER BY id DESC LIMIT 50
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def ingest_file(
        self,
        staging_path: Path,
        sha256: str,
        size_bytes: int,
        filename: str,
        *,
        title: str = "",
        description: str = "",
        project: str = "",
        tags: str = "",
        source_agent: str = "",
        decision: str | None = None,
        artifact_id: str | None = None,
    ) -> dict:
        self.require_available()
        filename = safe_filename(filename)
        decision = _clean_decision(decision)
        if decision == "new_version" and not (artifact_id or "").strip():
            raise LibraryError(400, "追加为新版本时必须指定要追加的知识")
        with db_session(self.settings.db_path) as conn:
            candidates = _candidates_for_hash(conn, sha256)
        if decision is None and candidates:
            _write_staging_meta(self.settings.staging_dir, sha256, filename, size_bytes)
            return {
                "status": "needs_decision",
                "staging_id": sha256,
                "sha256": sha256,
                "filename": filename,
                "size_bytes": size_bytes,
                "stored_new_blob": False,
                "message": "相同内容已存在。请明确选择新建一条知识，或追加为某一条的新版本。文件名不会用来覆盖已有知识。",
                "candidates": candidates,
            }
        if decision is None:
            decision = "new_artifact"
        return self._finalize(
            staging_path,
            sha256,
            size_bytes,
            filename,
            decision=decision,
            artifact_id=artifact_id,
            title=title,
            description=description,
            project=project,
            tags=tags,
            source_agent=source_agent,
        )

    def confirm(
        self,
        staging_id: str,
        decision: str,
        *,
        artifact_id: str | None = None,
        title: str = "",
        description: str = "",
        project: str = "",
        tags: str = "",
        source_agent: str = "",
        filename: str = "",
    ) -> dict:
        self.require_available()
        sha256 = _require_sha(staging_id)
        decision = _clean_decision(decision)
        if decision not in {"new_artifact", "new_version"}:
            raise LibraryError(400, "请明确选择新建一条知识或追加版本")
        manifest = _bundle_manifest_path(self.settings.staging_dir, sha256)
        if manifest.is_file():
            return self._finalize_bundle(
                _read_bundle_manifest(manifest),
                decision=decision,
                artifact_id=artifact_id,
                title=title,
                description=description,
                project=project,
                tags=tags,
                source_agent=source_agent,
            )
        staging = self.settings.staging_dir / sha256
        if not staging.is_file():
            raise LibraryError(404, "暂存文件不存在或已过期")
        meta = _read_staging_meta(self.settings.staging_dir, sha256)
        resolved_name = safe_filename(filename or meta.get("filename") or "artifact")
        return self._finalize(
            staging,
            sha256,
            staging.stat().st_size,
            resolved_name,
            decision=decision,
            artifact_id=artifact_id,
            title=title,
            description=description,
            project=project,
            tags=tags,
            source_agent=source_agent,
        )

    def ingest_bundle(
        self,
        staged: list[tuple[Path, str, int, str]],
        *,
        title: str = "",
        description: str = "",
        project: str = "",
        tags: str = "",
        source_agent: str = "",
        decision: str | None = None,
        artifact_id: str | None = None,
    ) -> dict:
        if len(staged) == 1:
            path, sha256, size_bytes, filename = staged[0]
            return self.ingest_file(
                path,
                sha256,
                size_bytes,
                filename,
                title=title,
                description=description,
                project=project,
                tags=tags,
                source_agent=source_agent,
                decision=decision,
                artifact_id=artifact_id,
            )
        self.require_available()
        decision = _clean_decision(decision)
        if decision == "new_version" and not (artifact_id or "").strip():
            raise LibraryError(400, "追加为新版本时必须指定要追加的知识")
        files = [
            {"path": path, "sha256": sha256, "size_bytes": size_bytes, "filename": safe_filename(filename)}
            for path, sha256, size_bytes, filename in staged
        ]
        signature = _bundle_signature([item["sha256"] for item in files])
        with db_session(self.settings.db_path) as conn:
            candidates = _candidates_for_signature(conn, [item["sha256"] for item in files])
        if decision is None and candidates:
            _write_bundle_manifest(self.settings.staging_dir, signature, files)
            return {
                "status": "needs_decision",
                "staging_id": signature,
                "sha256": signature,
                "filename": files[0]["filename"],
                "size_bytes": sum(item["size_bytes"] for item in files),
                "stored_new_blob": False,
                "message": "相同的一组文件已存在。请明确选择新建一条知识，或追加为某一条的新版本。",
                "candidates": candidates,
            }
        if decision is None:
            decision = "new_artifact"
        return self._finalize_bundle(
            files,
            decision=decision,
            artifact_id=artifact_id,
            title=title,
            description=description,
            project=project,
            tags=tags,
            source_agent=source_agent,
        )

    def query(
        self,
        *,
        q: str = "",
        project: str = "",
        tag: str = "",
        source: str = "",
        kind: str = "",
        mode: str = "keyword",
        limit: int = 40,
        offset: int = 0,
    ) -> dict:
        self.require_available()
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        query = (q or "").strip()
        mode = mode or "keyword"
        if query and mode in {"semantic", "hybrid"}:
            semantic_items = self._semantic_query(query, project, tag, source, kind, limit)
            if mode == "semantic":
                return {"items": semantic_items, "total": len(semantic_items), "mode": "semantic"}
            keyword = self._keyword_query(query, project, tag, source, kind, limit, offset)
            seen = {item["version_id"] for item in keyword["items"]}
            for item in semantic_items:
                if item["version_id"] not in seen:
                    keyword["items"].append(item)
                    seen.add(item["version_id"])
            keyword["mode"] = "hybrid"
            keyword["total"] = len(keyword["items"])
            return keyword
        if query and mode not in {"keyword", "semantic", "hybrid"}:
            raise LibraryError(400, "不支持的检索模式")
        if not query:
            result = self._list_current(project, tag, source, kind, limit, offset)
            result["mode"] = "list"
            return result
        result = self._keyword_query(query, project, tag, source, kind, limit, offset)
        result["mode"] = "keyword"
        return result

    def get_artifact(self, public_id: str) -> dict:
        with db_session(self.settings.db_path) as conn:
            return _artifact_detail(conn, public_id)

    def update_artifact(
        self,
        public_id: str,
        *,
        title: str,
        description: str,
        project: str,
        tags: str,
        source_agent: str,
    ) -> dict:
        self.require_available()
        cleaned_title = title.strip()
        if not cleaned_title:
            raise LibraryError(400, "名称不能为空")
        with db_session(self.settings.db_path, write=True) as conn:
            artifact = _require_artifact(conn, public_id)
            project_id = _resolve_project(conn, project)
            agent_id = _resolve_agent(conn, source_agent)
            ts = now_iso()
            conn.execute(
                """
                UPDATE artifacts
                SET title = ?, description = ?, project_id = ?, source_agent_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (cleaned_title, description.strip(), project_id, agent_id, ts, artifact["id"]),
            )
            _replace_tags(conn, int(artifact["id"]), parse_tags(tags))
            _reindex_artifact(conn, int(artifact["id"]))
        return self.get_artifact(public_id)

    def delete_artifact(self, public_id: str) -> dict:
        self.require_available()
        removed: list[str] = []
        with db_session(self.settings.db_path, write=True) as conn:
            artifact = _require_artifact(conn, public_id)
            versions = conn.execute(
                "SELECT id, file_object_id FROM artifact_versions WHERE artifact_id = ?",
                (artifact["id"],),
            ).fetchall()
            file_ids = [
                int(row["file_object_id"])
                for row in conn.execute(
                    """
                    SELECT vf.file_object_id
                    FROM version_files vf
                    JOIN artifact_versions v ON v.id = vf.version_id
                    WHERE v.artifact_id = ?
                    """,
                    (artifact["id"],),
                ).fetchall()
            ]
            file_ids.extend(int(version["file_object_id"]) for version in versions)
            for version in versions:
                conn.execute("DELETE FROM artifact_fts WHERE version_id = ?", (str(version["id"]),))
                conn.execute("DELETE FROM embeddings WHERE version_id = ?", (version["id"],))
            conn.execute("DELETE FROM artifact_versions WHERE artifact_id = ?", (artifact["id"],))
            conn.execute("DELETE FROM artifact_tags WHERE artifact_id = ?", (artifact["id"],))
            conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact["id"],))
            for file_id in dict.fromkeys(file_ids):
                relative = _gc_file_object(conn, file_id)
                if relative:
                    removed.append(relative)
        for relative in removed:
            (self.settings.objects_dir / relative).unlink(missing_ok=True)
        return {"ok": True, "id": public_id}

    def list_versions(self, public_id: str) -> list[dict]:
        with db_session(self.settings.db_path) as conn:
            artifact = _require_artifact(conn, public_id)
            rows = conn.execute(
                """
                SELECT * FROM artifact_versions
                WHERE artifact_id = ?
                ORDER BY version_number DESC
                """,
                (artifact["id"],),
            ).fetchall()
            current_id = artifact["current_version_id"]
            return [_version_dto(row, current_id, _files_for_version(conn, int(row["id"]))) for row in rows]

    def restore_version(self, public_id: str, version_public_id: str) -> dict:
        self.require_available()
        with db_session(self.settings.db_path, write=True) as conn:
            artifact = _require_artifact(conn, public_id)
            version = conn.execute(
                "SELECT * FROM artifact_versions WHERE public_id = ? AND artifact_id = ?",
                (version_public_id, artifact["id"]),
            ).fetchone()
            if version is None:
                raise LibraryError(404, "版本不存在")
            current = conn.execute(
                "SELECT * FROM artifact_versions WHERE id = ?",
                (artifact["current_version_id"],),
            ).fetchone()
            if current is not None and _version_signature(conn, int(current["id"])) == _version_signature(conn, int(version["id"])):
                detail = _artifact_detail(conn, public_id)
                detail["status"] = "already_current"
                detail["message"] = "当前内容已与该版本一致"
                return detail
            created = _insert_version(
                conn,
                artifact_pk=int(artifact["id"]),
                file_object_id=int(version["file_object_id"]),
                filename=version["original_filename"],
                mime=version["mime_type"],
                size_bytes=int(version["size_bytes"]),
                sha256=version["sha256"],
                preview_kind=version["preview_kind"],
                note=f"恢复自 v{version['version_number']}",
                extracted_text=version["extracted_text"],
                extract_status=version["extract_status"] or "done",
                members=_members_of(conn, int(version["id"])),
            )
            _touch_artifact(conn, int(artifact["id"]), int(created["id"]))
            _reindex_version(conn, int(created["id"]))
            _enqueue(conn, int(created["id"]))
        self._drain_if_sync()
        detail = self.get_artifact(public_id)
        detail["status"] = "restored"
        return detail

    def preview(self, public_id: str, version_public_id: str | None = None, file_public_id: str | None = None) -> dict:
        version, path = self._locate_file(public_id, version_public_id, file_public_id)
        kind = version["preview_kind"]
        try:
            payload = preview_payload(path, kind)
        except Exception as exc:  # noqa: BLE001
            logger.exception("preview failed")
            payload = {"error": f"预览失败：{exc}"[:300]}
            kind = "unsupported"
        return {
            "artifact_id": public_id,
            "version_id": version["public_id"],
            "file_id": version.get("file_id") or "",
            "version_number": version["version_number"],
            "filename": version["original_filename"],
            "mime_type": version["mime_type"],
            "preview_kind": kind,
            "size_bytes": version["size_bytes"],
            "sha256": version["sha256"],
            **payload,
        }

    def locate_download(self, public_id: str, version_public_id: str | None = None, file_public_id: str | None = None) -> tuple[Path, dict]:
        version, path = self._locate_file(public_id, version_public_id, file_public_id)
        return path, version

    def verify_file(self, public_id: str, version_public_id: str | None = None, file_public_id: str | None = None) -> dict:
        version, path = self._locate_file(public_id, version_public_id, file_public_id)
        actual = sha256_file(path)
        return {
            "ok": actual == version["sha256"],
            "expected": version["sha256"],
            "actual": actual,
            "size_bytes": path.stat().st_size,
            "version_id": version["public_id"],
            "file_id": version.get("file_id") or "",
        }

    def list_projects(self) -> list[dict]:
        with db_session(self.settings.db_path) as conn:
            rows = conn.execute(
                """
                SELECT p.*, COUNT(a.id) AS artifact_count
                FROM projects p
                LEFT JOIN artifacts a ON a.project_id = p.id
                GROUP BY p.id
                ORDER BY p.name COLLATE NOCASE
                """
            ).fetchall()
        return [_project_dto(row) for row in rows]

    def create_project(self, name: str, description: str = "") -> dict:
        self.require_available()
        cleaned = name.strip()
        if not cleaned:
            raise LibraryError(400, "项目名称不能为空")
        with db_session(self.settings.db_path, write=True) as conn:
            existing = conn.execute("SELECT public_id FROM projects WHERE name = ? COLLATE NOCASE", (cleaned,)).fetchone()
            if existing:
                raise LibraryError(409, "同名项目已存在")
            ts = now_iso()
            public_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO projects(public_id, name, description, created_at, updated_at) VALUES(?, ?, ?, ?, ?)",
                (public_id, cleaned, description.strip(), ts, ts),
            )
        return self._project_by_public_id(public_id)

    def update_project(self, public_id: str, name: str, description: str) -> dict:
        self.require_available()
        cleaned = name.strip()
        if not cleaned:
            raise LibraryError(400, "项目名称不能为空")
        with db_session(self.settings.db_path, write=True) as conn:
            row = _require_named(conn, "projects", public_id, "项目不存在")
            clash = conn.execute(
                "SELECT id FROM projects WHERE name = ? COLLATE NOCASE AND id != ?",
                (cleaned, row["id"]),
            ).fetchone()
            if clash:
                raise LibraryError(409, "同名项目已存在")
            conn.execute(
                "UPDATE projects SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                (cleaned, description.strip(), now_iso(), row["id"]),
            )
            artifacts = conn.execute("SELECT id FROM artifacts WHERE project_id = ?", (row["id"],)).fetchall()
            for artifact in artifacts:
                _reindex_artifact(conn, int(artifact["id"]))
        return self._project_by_public_id(public_id)

    def delete_project(self, public_id: str) -> dict:
        self.require_available()
        with db_session(self.settings.db_path, write=True) as conn:
            row = _require_named(conn, "projects", public_id, "项目不存在")
            artifacts = conn.execute("SELECT id FROM artifacts WHERE project_id = ?", (row["id"],)).fetchall()
            conn.execute("UPDATE artifacts SET project_id = NULL, updated_at = ? WHERE project_id = ?", (now_iso(), row["id"]))
            conn.execute("DELETE FROM projects WHERE id = ?", (row["id"],))
            for artifact in artifacts:
                _reindex_artifact(conn, int(artifact["id"]))
        return {"ok": True}

    def list_tags(self) -> list[dict]:
        with db_session(self.settings.db_path) as conn:
            rows = conn.execute(
                """
                SELECT t.*, COUNT(at.artifact_id) AS artifact_count
                FROM tags t
                LEFT JOIN artifact_tags at ON at.tag_id = t.id
                GROUP BY t.id
                ORDER BY t.name COLLATE NOCASE
                """
            ).fetchall()
        return [
            {
                "id": row["public_id"],
                "name": row["name"],
                "artifact_count": row["artifact_count"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def create_tag(self, name: str) -> dict:
        self.require_available()
        cleaned = name.strip()
        if not cleaned:
            raise LibraryError(400, "标签不能为空")
        with db_session(self.settings.db_path, write=True) as conn:
            existing = conn.execute("SELECT public_id FROM tags WHERE name = ? COLLATE NOCASE", (cleaned,)).fetchone()
            if existing:
                raise LibraryError(409, "同名标签已存在")
            public_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO tags(public_id, name, created_at) VALUES(?, ?, ?)",
                (public_id, cleaned, now_iso()),
            )
        return next(item for item in self.list_tags() if item["id"] == public_id)

    def update_tag(self, public_id: str, name: str) -> dict:
        self.require_available()
        cleaned = name.strip()
        if not cleaned:
            raise LibraryError(400, "标签不能为空")
        with db_session(self.settings.db_path, write=True) as conn:
            row = _require_named(conn, "tags", public_id, "标签不存在")
            clash = conn.execute(
                "SELECT id FROM tags WHERE name = ? COLLATE NOCASE AND id != ?",
                (cleaned, row["id"]),
            ).fetchone()
            if clash:
                raise LibraryError(409, "同名标签已存在")
            conn.execute("UPDATE tags SET name = ? WHERE id = ?", (cleaned, row["id"]))
            artifacts = conn.execute(
                "SELECT artifact_id FROM artifact_tags WHERE tag_id = ?",
                (row["id"],),
            ).fetchall()
            for artifact in artifacts:
                _reindex_artifact(conn, int(artifact["artifact_id"]))
        return next(item for item in self.list_tags() if item["id"] == public_id)

    def delete_tag(self, public_id: str) -> dict:
        self.require_available()
        with db_session(self.settings.db_path, write=True) as conn:
            row = _require_named(conn, "tags", public_id, "标签不存在")
            artifacts = conn.execute(
                "SELECT artifact_id FROM artifact_tags WHERE tag_id = ?",
                (row["id"],),
            ).fetchall()
            conn.execute("DELETE FROM artifact_tags WHERE tag_id = ?", (row["id"],))
            conn.execute("DELETE FROM tags WHERE id = ?", (row["id"],))
            for artifact in artifacts:
                _reindex_artifact(conn, int(artifact["artifact_id"]))
        return {"ok": True}

    def list_agents(self) -> list[dict]:
        with db_session(self.settings.db_path) as conn:
            rows = conn.execute(
                """
                SELECT s.*, COUNT(a.id) AS artifact_count
                FROM source_agents s
                LEFT JOIN artifacts a ON a.source_agent_id = s.id
                GROUP BY s.id
                ORDER BY s.name COLLATE NOCASE
                """
            ).fetchall()
        return [
            {
                "id": row["public_id"],
                "name": row["name"],
                "note": row["note"],
                "artifact_count": row["artifact_count"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def create_agent(self, name: str, note: str = "") -> dict:
        self.require_available()
        cleaned = name.strip()
        if not cleaned:
            raise LibraryError(400, "来源名称不能为空")
        with db_session(self.settings.db_path, write=True) as conn:
            existing = conn.execute(
                "SELECT public_id FROM source_agents WHERE name = ? COLLATE NOCASE",
                (cleaned,),
            ).fetchone()
            if existing:
                raise LibraryError(409, "同名来源已存在")
            public_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO source_agents(public_id, name, note, created_at) VALUES(?, ?, ?, ?)",
                (public_id, cleaned, note.strip(), now_iso()),
            )
        return next(item for item in self.list_agents() if item["id"] == public_id)

    def update_agent(self, public_id: str, name: str, note: str) -> dict:
        self.require_available()
        cleaned = name.strip()
        if not cleaned:
            raise LibraryError(400, "来源名称不能为空")
        with db_session(self.settings.db_path, write=True) as conn:
            row = _require_named(conn, "source_agents", public_id, "来源不存在")
            clash = conn.execute(
                "SELECT id FROM source_agents WHERE name = ? COLLATE NOCASE AND id != ?",
                (cleaned, row["id"]),
            ).fetchone()
            if clash:
                raise LibraryError(409, "同名来源已存在")
            conn.execute(
                "UPDATE source_agents SET name = ?, note = ? WHERE id = ?",
                (cleaned, note.strip(), row["id"]),
            )
            artifacts = conn.execute("SELECT id FROM artifacts WHERE source_agent_id = ?", (row["id"],)).fetchall()
            for artifact in artifacts:
                _reindex_artifact(conn, int(artifact["id"]))
        return next(item for item in self.list_agents() if item["id"] == public_id)

    def delete_agent(self, public_id: str) -> dict:
        self.require_available()
        with db_session(self.settings.db_path, write=True) as conn:
            row = _require_named(conn, "source_agents", public_id, "来源不存在")
            artifacts = conn.execute("SELECT id FROM artifacts WHERE source_agent_id = ?", (row["id"],)).fetchall()
            conn.execute(
                "UPDATE artifacts SET source_agent_id = NULL, updated_at = ? WHERE source_agent_id = ?",
                (now_iso(), row["id"]),
            )
            conn.execute("DELETE FROM source_agents WHERE id = ?", (row["id"],))
            for artifact in artifacts:
                _reindex_artifact(conn, int(artifact["id"]))
        return {"ok": True}

    def make_backup(self) -> dict:
        self.require_available()
        return create_backup(self.settings)

    def backups(self) -> list[dict]:
        return list_backups(self.settings)

    def backup_path(self, name: str) -> Path:
        return resolve_backup(self.settings, name)

    def restore_from(self, zip_path: Path) -> dict:
        self.maintenance = True
        try:
            restore_backup(self.settings, zip_path)
            self.tokenizer = init_db(self.settings.db_path)
        finally:
            self.maintenance = False
        return {"ok": True, "status": self.status()}

    def import_model(self, path_str: str) -> dict:
        self.require_available()
        try:
            info = validate_model_dir(Path(path_str).expanduser())
        except ValueError as exc:
            raise LibraryError(400, str(exc)) from exc
        with db_session(self.settings.db_path, write=True) as conn:
            _set_setting(conn, "semantic_model_path", info["path"])
            _set_setting(conn, "semantic_model_type", info["model_type"])
            _set_setting(conn, "semantic_enabled", "0")
            _set_setting(conn, "semantic_error", "")
        self._embedder = None
        return info

    def set_semantic_enabled(self, enabled: bool) -> dict:
        self.require_available()
        with db_session(self.settings.db_path, write=True) as conn:
            path = _get_setting(conn, "semantic_model_path", "")
            model_type = _get_setting(conn, "semantic_model_type", "")
        if enabled and self._embedder is None:
            if not path:
                raise LibraryError(400, "请先导入本地模型。未启用时，全文检索仍然可用。")
            try:
                validate_model_dir(Path(path))
            except ValueError as exc:
                raise LibraryError(400, str(exc)) from exc
            if not sentence_transformers_available():
                raise LibraryError(400, "未安装可选依赖 sentence-transformers。基础归档和全文检索不受影响。")
        with db_session(self.settings.db_path, write=True) as conn:
            _set_setting(conn, "semantic_enabled", "1" if enabled else "0")
            if not enabled:
                _set_setting(conn, "semantic_error", "")
            semantic = self._semantic_view(conn)
        semantic["model_type"] = semantic.get("model_type") or model_type
        return semantic

    def clear_semantic(self) -> dict:
        self.require_available()
        with db_session(self.settings.db_path, write=True) as conn:
            conn.execute("DELETE FROM embeddings")
            _set_setting(conn, "semantic_enabled", "0")
            _set_setting(conn, "semantic_error", "")
            return self._semantic_view(conn)

    def rebuild_semantic(self) -> dict:
        self.require_available()
        with db_session(self.settings.db_path) as conn:
            enabled = _get_setting(conn, "semantic_enabled", "0") == "1"
        if not enabled:
            raise LibraryError(400, "语义检索未启用")
        with db_session(self.settings.db_path, write=True) as conn:
            conn.execute("DELETE FROM embeddings")
            rows = conn.execute("SELECT id FROM artifact_versions").fetchall()
            for row in rows:
                _enqueue(conn, int(row["id"]))
            queued = len(rows)
        self._drain_if_sync()
        return {"ok": True, "queued": queued}

    def index_version(self, version_pk: int) -> None:
        with db_session(self.settings.db_path) as conn:
            row = conn.execute(
                """
                SELECT v.id, a.title
                FROM artifact_versions v
                JOIN artifacts a ON a.id = v.artifact_id
                WHERE v.id = ?
                """,
                (version_pk,),
            ).fetchone()
            members = _members_of(conn, version_pk) if row is not None else []
        if row is None:
            return
        if not members:
            with db_session(self.settings.db_path, write=True) as conn:
                conn.execute(
                    "UPDATE artifact_versions SET extract_status = 'failed', extract_error = ? WHERE id = ?",
                    ("原始文件缺失", version_pk),
                )
            return
        extracted: list[tuple[int, str, str, str]] = []
        parts: list[str] = []
        for member in members:
            path = self.settings.objects_dir / member["relative_path"]
            if not path.is_file():
                extracted.append((int(member["id"]), "", "failed", "原始文件缺失"))
                continue
            text, status, error = extract_text(path, member["preview_kind"])
            extracted.append((int(member["id"]), text, status, error))
            if text:
                parts.append(f"{member['filename']}\n{text}")
        text = "\n\n".join(parts)
        if any(item[2] == "failed" for item in extracted):
            status, error = "failed", next(item[3] for item in extracted if item[2] == "failed")
        elif any(item[2] == "pending" for item in extracted):
            status, error = "pending", ""
        else:
            status, error = "done", ""
        vector = None
        model_type = ""
        semantic_error = ""
        if self._semantic_enabled():
            try:
                embedder = self.get_embedder()
                if embedder is not None:
                    vector = embedder.embed([f"{row['title']}\n{text[:4000]}"])[0]
                    model_type = getattr(embedder, "model_type", "")
            except Exception as exc:  # noqa: BLE001
                semantic_error = str(exc)[:300]
                logger.warning("semantic index skipped: %s", semantic_error)
        with db_session(self.settings.db_path, write=True) as conn:
            for file_pk, file_text, file_status, file_error in extracted:
                conn.execute(
                    """
                    UPDATE version_files
                    SET extracted_text = ?, extract_status = ?, extract_error = ?
                    WHERE id = ?
                    """,
                    (file_text, file_status, file_error, file_pk),
                )
            conn.execute(
                """
                UPDATE artifact_versions
                SET extracted_text = ?, extract_status = ?, extract_error = ?
                WHERE id = ?
                """,
                (text, status, error, version_pk),
            )
            _reindex_version(conn, version_pk)
            if vector is not None:
                conn.execute(
                    """
                    INSERT INTO embeddings(version_id, dim, vector, model_type, updated_at)
                    VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(version_id) DO UPDATE SET
                      dim = excluded.dim,
                      vector = excluded.vector,
                      model_type = excluded.model_type,
                      updated_at = excluded.updated_at
                    """,
                    (version_pk, len(vector), pack_vector(vector), model_type, now_iso()),
                )
                _set_setting(conn, "semantic_error", "")
            elif semantic_error:
                _set_setting(conn, "semantic_error", semantic_error)

    def get_embedder(self) -> Embedder | None:
        if self._embedder is not None:
            return self._embedder
        with db_session(self.settings.db_path) as conn:
            path = _get_setting(conn, "semantic_model_path", "")
            enabled = _get_setting(conn, "semantic_enabled", "0") == "1"
        if not enabled or not path:
            return None
        self._embedder = load_local_embedder(path)
        return self._embedder

    def _semantic_enabled(self) -> bool:
        if self._embedder is not None:
            with db_session(self.settings.db_path) as conn:
                return _get_setting(conn, "semantic_enabled", "0") == "1"
        with db_session(self.settings.db_path) as conn:
            return _get_setting(conn, "semantic_enabled", "0") == "1"

    def _semantic_view(self, conn) -> dict:
        enabled = _get_setting(conn, "semantic_enabled", "0") == "1"
        path = _get_setting(conn, "semantic_model_path", "")
        model_type = _get_setting(conn, "semantic_model_type", "")
        error = _get_setting(conn, "semantic_error", "")
        package_ready = self._embedder is not None or sentence_transformers_available()
        path_ok = self._embedder is not None and enabled
        if path:
            try:
                validate_model_dir(Path(path))
                path_ok = True
            except ValueError as exc:
                error = error or str(exc)
                path_ok = self._embedder is not None
        if self._embedder is not None and enabled:
            reason = error or "已启用"
        elif not path:
            reason = "未导入本地模型"
        elif not path_ok:
            reason = error or "模型目录未通过校验"
        elif not package_ready:
            reason = "未安装可选依赖 sentence-transformers"
        elif not enabled:
            reason = "模型已导入，尚未启用"
        elif error:
            reason = error
        else:
            reason = "已启用"
        indexed = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"]
        return {
            "enabled": enabled and path_ok,
            "requested": enabled,
            "package_ready": package_ready,
            "model_path": path,
            "model_type": model_type,
            "indexed_versions": indexed,
            "reason": reason,
        }

    def _finalize(
        self,
        staging_path: Path,
        sha256: str,
        size_bytes: int,
        filename: str,
        *,
        decision: str,
        artifact_id: str | None,
        title: str,
        description: str,
        project: str,
        tags: str,
        source_agent: str,
        note: str = "",
    ) -> dict:
        if decision == "new_version":
            with db_session(self.settings.db_path) as conn:
                artifact = _require_artifact(conn, (artifact_id or "").strip())
                duplicate = conn.execute(
                    """
                    SELECT public_id, version_number FROM artifact_versions
                    WHERE artifact_id = ? AND sha256 = ?
                    ORDER BY version_number DESC LIMIT 1
                    """,
                    (artifact["id"], sha256),
                ).fetchone()
            if duplicate is not None:
                staging_path.unlink(missing_ok=True)
                _meta_path(self.settings.staging_dir, sha256).unlink(missing_ok=True)
                detail = self.get_artifact(artifact["public_id"])
                detail["status"] = "duplicate_version"
                detail["stored_new_blob"] = False
                detail["message"] = f"这条知识已包含相同内容（v{duplicate['version_number']}），未重复保存。"
                return detail

        head = staging_path.read_bytes()[:64] if staging_path.exists() else b""
        kind = sniff_preview_kind(staging_path, filename, "")
        mime = guess_mime(filename, kind, head)
        _path, stored_new = commit_blob(staging_path, self.settings.objects_dir, sha256)
        _meta_path(self.settings.staging_dir, sha256).unlink(missing_ok=True)
        tag_list = parse_tags(tags)
        resolved_title = title.strip() or Path(filename).stem or filename
        with db_session(self.settings.db_path, write=True) as conn:
            file_id, _ = _ensure_file_object(conn, sha256, size_bytes, mime, relative_object_path(sha256))
            if decision == "new_version":
                artifact = _require_artifact(conn, (artifact_id or "").strip())
                artifact_pk = int(artifact["id"])
                if title.strip() or description.strip() or project.strip() or tag_list or source_agent.strip():
                    _apply_metadata(conn, artifact_pk, resolved_title if title.strip() else None, description, project, source_agent, tag_list if tags.strip() else None)
                created = _insert_version(
                    conn,
                    artifact_pk=artifact_pk,
                    file_object_id=file_id,
                    filename=filename,
                    mime=mime,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    preview_kind=kind,
                    note=note,
                )
                _touch_artifact(conn, artifact_pk, int(created["id"]))
                _reindex_version(conn, int(created["id"]))
                _enqueue(conn, int(created["id"]))
                public_id = artifact["public_id"]
                status = "version_created"
            else:
                artifact_pk, public_id = _insert_artifact(conn, resolved_title, description.strip(), project, source_agent)
                _replace_tags(conn, artifact_pk, tag_list)
                created = _insert_version(
                    conn,
                    artifact_pk=artifact_pk,
                    file_object_id=file_id,
                    filename=filename,
                    mime=mime,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    preview_kind=kind,
                    note=note,
                )
                _touch_artifact(conn, artifact_pk, int(created["id"]))
                _reindex_version(conn, int(created["id"]))
                _enqueue(conn, int(created["id"]))
                status = "created"
        self._drain_if_sync()
        detail = self.get_artifact(public_id)
        detail["status"] = status
        detail["stored_new_blob"] = stored_new
        detail["message"] = "已新增一条知识" if status == "created" else "已追加新版本"
        return detail

    def _finalize_bundle(
        self,
        files: list[dict],
        *,
        decision: str,
        artifact_id: str | None,
        title: str,
        description: str,
        project: str,
        tags: str,
        source_agent: str,
    ) -> dict:
        signature = _bundle_signature([item["sha256"] for item in files])
        if decision == "new_version":
            with db_session(self.settings.db_path) as conn:
                artifact = _require_artifact(conn, (artifact_id or "").strip())
                duplicate = _version_with_signature(conn, int(artifact["id"]), [item["sha256"] for item in files])
            if duplicate is not None:
                self._discard_staged(files, signature)
                detail = self.get_artifact(artifact["public_id"])
                detail["status"] = "duplicate_version"
                detail["stored_new_blob"] = False
                detail["message"] = f"这条知识已包含相同的一组文件（v{duplicate['version_number']}），未重复保存。"
                return detail
        prepared: list[dict] = []
        for item in files:
            path = Path(item["path"]) if item.get("path") else self.settings.staging_dir / item["sha256"]
            head = path.read_bytes()[:64] if path.is_file() else b""
            kind = sniff_preview_kind(path, item["filename"], "")
            prepared.append(
                {
                    **item,
                    "path": path,
                    "preview_kind": kind,
                    "mime": guess_mime(item["filename"], kind, head),
                }
            )
        stored_new = False
        for item in prepared:
            _path, created = commit_blob(item["path"], self.settings.objects_dir, item["sha256"])
            stored_new = stored_new or created
        _bundle_manifest_path(self.settings.staging_dir, signature).unlink(missing_ok=True)
        for item in prepared:
            _meta_path(self.settings.staging_dir, item["sha256"]).unlink(missing_ok=True)
        tag_list = parse_tags(tags)
        first = prepared[0]
        resolved_title = title.strip() or Path(first["filename"]).stem or first["filename"]
        with db_session(self.settings.db_path, write=True) as conn:
            members = []
            for item in prepared:
                file_id, _stored = _ensure_file_object(
                    conn,
                    item["sha256"],
                    int(item["size_bytes"]),
                    item["mime"],
                    relative_object_path(item["sha256"]),
                )
                members.append(
                    {
                        "file_object_id": file_id,
                        "filename": item["filename"],
                        "mime": item["mime"],
                        "size_bytes": int(item["size_bytes"]),
                        "sha256": item["sha256"],
                        "preview_kind": item["preview_kind"],
                        "relative_path": relative_object_path(item["sha256"]),
                    }
                )
            primary = members[0]
            if decision == "new_version":
                artifact = _require_artifact(conn, (artifact_id or "").strip())
                artifact_pk = int(artifact["id"])
                if title.strip() or description.strip() or project.strip() or tag_list or source_agent.strip():
                    _apply_metadata(
                        conn,
                        artifact_pk,
                        resolved_title if title.strip() else None,
                        description,
                        project,
                        source_agent,
                        tag_list if tags.strip() else None,
                    )
                public_id = artifact["public_id"]
                status = "version_created"
            else:
                artifact_pk, public_id = _insert_artifact(conn, resolved_title, description.strip(), project, source_agent)
                _replace_tags(conn, artifact_pk, tag_list)
                status = "created"
            created = _insert_version(
                conn,
                artifact_pk=artifact_pk,
                file_object_id=int(primary["file_object_id"]),
                filename=primary["filename"],
                mime=primary["mime"],
                size_bytes=int(primary["size_bytes"]),
                sha256=primary["sha256"],
                preview_kind=primary["preview_kind"],
                members=members,
            )
            _touch_artifact(conn, artifact_pk, int(created["id"]))
            _reindex_version(conn, int(created["id"]))
            _enqueue(conn, int(created["id"]))
        self._drain_if_sync()
        detail = self.get_artifact(public_id)
        detail["status"] = status
        detail["stored_new_blob"] = stored_new
        count = len(prepared)
        detail["message"] = f"已新增一条知识，包含 {count} 个文件" if status == "created" else f"已追加新版本，包含 {count} 个文件"
        return detail

    def _discard_staged(self, files: list[dict], signature: str) -> None:
        for item in files:
            path = Path(item["path"]) if item.get("path") else self.settings.staging_dir / item["sha256"]
            path.unlink(missing_ok=True)
            _meta_path(self.settings.staging_dir, item["sha256"]).unlink(missing_ok=True)
        _bundle_manifest_path(self.settings.staging_dir, signature).unlink(missing_ok=True)

    def _keyword_query(self, query: str, project: str, tag: str, source: str, kind: str, limit: int, offset: int) -> dict:
        match = fts_match_query(query) if self.tokenizer == "trigram" else fts_match_query(query)
        if match and self.tokenizer == "unicode61":
            match = " ".join(f'"{part}"' for part in query.split() if part)
        if match:
            try:
                return self._fts_query(match, query, project, tag, source, kind, limit, offset)
            except Exception:
                logger.exception("fts query failed, falling back to like")
        return self._like_query(query, project, tag, source, kind, limit, offset)

    def _fts_query(self, match: str, raw: str, project: str, tag: str, source: str, kind: str, limit: int, offset: int) -> dict:
        with db_session(self.settings.db_path) as conn:
            clauses, params = _filter_clauses(project, tag, source, kind)
            where = " AND ".join(["artifact_fts MATCH ?"] + clauses)
            sql = f"""
                SELECT a.public_id AS artifact_id, v.public_id AS version_id, v.version_number,
                       a.title, a.description, a.updated_at, v.original_filename AS filename,
                       v.mime_type, v.preview_kind, v.sha256, v.extracted_text,
                       p.name AS project_name, s.name AS source_name,
                       a.current_version_id = v.id AS is_current,
                       snippet(artifact_fts, 5, '【', '】', '…', 18) AS body_snippet,
                       snippet(artifact_fts, 2, '【', '】', '…', 12) AS title_snippet
                FROM artifact_fts
                JOIN artifact_versions v ON v.id = artifact_fts.version_id
                JOIN artifacts a ON a.id = v.artifact_id
                LEFT JOIN projects p ON p.id = a.project_id
                LEFT JOIN source_agents s ON s.id = a.source_agent_id
                WHERE {where}
                ORDER BY rank
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(sql, [match, *params, limit, offset]).fetchall()
            count_sql = f"""
                SELECT COUNT(*) AS n
                FROM artifact_fts
                JOIN artifact_versions v ON v.id = artifact_fts.version_id
                JOIN artifacts a ON a.id = v.artifact_id
                LEFT JOIN projects p ON p.id = a.project_id
                LEFT JOIN source_agents s ON s.id = a.source_agent_id
                WHERE {where}
            """
            total = conn.execute(count_sql, [match, *params]).fetchone()["n"]
            items = [_search_row(conn, row, raw) for row in rows]
        return {"items": items, "total": total}

    def _like_query(self, query: str, project: str, tag: str, source: str, kind: str, limit: int, offset: int) -> dict:
        pattern = like_pattern(query)
        with db_session(self.settings.db_path) as conn:
            clauses, params = _filter_clauses(project, tag, source, kind)
            text_clause = """(
                a.title LIKE ? ESCAPE '\\' OR a.description LIKE ? ESCAPE '\\'
                OR v.original_filename LIKE ? ESCAPE '\\' OR v.extracted_text LIKE ? ESCAPE '\\'
                OR EXISTS (
                    SELECT 1 FROM version_files vf
                    WHERE vf.version_id = v.id AND vf.original_filename LIKE ? ESCAPE '\\'
                )
            )"""
            where = " AND ".join([text_clause] + clauses)
            sql = f"""
                SELECT a.public_id AS artifact_id, v.public_id AS version_id, v.version_number,
                       a.title, a.description, a.updated_at, v.original_filename AS filename,
                       v.mime_type, v.preview_kind, v.sha256, v.extracted_text,
                       p.name AS project_name, s.name AS source_name,
                       a.current_version_id = v.id AS is_current
                FROM artifact_versions v
                JOIN artifacts a ON a.id = v.artifact_id
                LEFT JOIN projects p ON p.id = a.project_id
                LEFT JOIN source_agents s ON s.id = a.source_agent_id
                WHERE {where}
                ORDER BY a.updated_at DESC
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(sql, [pattern, pattern, pattern, pattern, pattern, *params, limit, offset]).fetchall()
            total = conn.execute(
                f"""
                SELECT COUNT(*) AS n
                FROM artifact_versions v
                JOIN artifacts a ON a.id = v.artifact_id
                LEFT JOIN projects p ON p.id = a.project_id
                LEFT JOIN source_agents s ON s.id = a.source_agent_id
                WHERE {where}
                """,
                [pattern, pattern, pattern, pattern, pattern, *params],
            ).fetchone()["n"]
            items = []
            for row in rows:
                item = _search_row(conn, row, query)
                item["snippet"] = make_snippet(row["extracted_text"] or row["title"] or "", query)
                items.append(item)
        return {"items": items, "total": total}

    def _list_current(self, project: str, tag: str, source: str, kind: str, limit: int, offset: int) -> dict:
        with db_session(self.settings.db_path) as conn:
            clauses, params = _filter_clauses(project, tag, source, kind)
            where = " AND ".join(clauses) if clauses else "1 = 1"
            sql = f"""
                SELECT a.public_id AS artifact_id, v.public_id AS version_id, v.version_number,
                       a.title, a.description, a.updated_at, v.original_filename AS filename,
                       v.mime_type, v.preview_kind, v.sha256, v.extracted_text,
                       p.name AS project_name, s.name AS source_name,
                       1 AS is_current
                FROM artifacts a
                JOIN artifact_versions v ON v.id = a.current_version_id
                LEFT JOIN projects p ON p.id = a.project_id
                LEFT JOIN source_agents s ON s.id = a.source_agent_id
                WHERE {where}
                ORDER BY a.updated_at DESC
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(sql, [*params, limit, offset]).fetchall()
            total = conn.execute(
                f"""
                SELECT COUNT(*) AS n
                FROM artifacts a
                JOIN artifact_versions v ON v.id = a.current_version_id
                LEFT JOIN projects p ON p.id = a.project_id
                LEFT JOIN source_agents s ON s.id = a.source_agent_id
                WHERE {where}
                """,
                params,
            ).fetchone()["n"]
            items = [_search_row(conn, row, "") for row in rows]
        return {"items": items, "total": total}

    def _semantic_query(self, query: str, project: str, tag: str, source: str, kind: str, limit: int) -> list[dict]:
        with db_session(self.settings.db_path) as conn:
            view = self._semantic_view(conn)
        if not view["enabled"]:
            raise LibraryError(409, f"语义检索不可用：{view['reason']}。全文检索仍然可用。", semantic=view)
        embedder = self.get_embedder()
        if embedder is None:
            raise LibraryError(409, "语义检索不可用，全文检索仍然可用。")
        vector = embedder.embed([query])[0]
        with db_session(self.settings.db_path) as conn:
            rows = conn.execute("SELECT version_id, vector FROM embeddings").fetchall()
            scored: list[tuple[float, int]] = []
            for row in rows:
                scored.append((cosine(vector, unpack_vector(row["vector"])), int(row["version_id"])))
            scored.sort(key=lambda item: item[0], reverse=True)
            items = []
            for score, version_pk in scored:
                if score <= 0:
                    continue
                row = _version_search_row(conn, version_pk)
                if row is None:
                    continue
                if project and (row["project_name"] or "").casefold() != project.casefold():
                    continue
                if source and (row["source_name"] or "").casefold() != source.casefold():
                    continue
                if kind and row["preview_kind"] != kind:
                    matched = conn.execute(
                        """
                        SELECT 1
                        FROM version_files vf
                        JOIN artifact_versions versions ON versions.id = vf.version_id
                        WHERE versions.public_id = ? AND vf.preview_kind = ?
                        """,
                        (row["version_id"], kind),
                    ).fetchone()
                    if matched is None:
                        continue
                if tag:
                    names = _tag_names(conn, row["artifact_pk"])
                    if tag.casefold() not in {name.casefold() for name in names}:
                        continue
                item = _search_row(conn, row, query)
                item["snippet"] = make_snippet(row["extracted_text"] or row["title"], query) or row["title"]
                item["score"] = round(score, 4)
                items.append(item)
                if len(items) >= limit:
                    break
        return items

    def _locate_file(self, public_id: str, version_public_id: str | None, file_public_id: str | None = None) -> tuple[dict, Path]:
        with db_session(self.settings.db_path) as conn:
            artifact = _require_artifact(conn, public_id)
            if version_public_id:
                version = conn.execute(
                    "SELECT * FROM artifact_versions WHERE public_id = ? AND artifact_id = ?",
                    (version_public_id, artifact["id"]),
                ).fetchone()
            else:
                version = conn.execute(
                    "SELECT * FROM artifact_versions WHERE id = ?",
                    (artifact["current_version_id"],),
                ).fetchone()
            chosen = None
            if version is not None:
                if file_public_id:
                    chosen = conn.execute(
                        "SELECT * FROM version_files WHERE public_id = ? AND version_id = ?",
                        (file_public_id, version["id"]),
                    ).fetchone()
                else:
                    chosen = conn.execute(
                        "SELECT * FROM version_files WHERE version_id = ? ORDER BY position, id LIMIT 1",
                        (version["id"],),
                    ).fetchone()
        if version is None:
            raise LibraryError(404, "版本不存在")
        if file_public_id and chosen is None:
            raise LibraryError(404, "文件不存在")
        sha256 = chosen["sha256"] if chosen is not None else version["sha256"]
        filename = chosen["original_filename"] if chosen is not None else version["original_filename"]
        preview_kind = chosen["preview_kind"] if chosen is not None else version["preview_kind"]
        mime_type = chosen["mime_type"] if chosen is not None else version["mime_type"]
        size_bytes = chosen["size_bytes"] if chosen is not None else version["size_bytes"]
        path = self.settings.objects_dir / relative_object_path(sha256)
        if not path.is_file():
            raise LibraryError(404, "原始文件缺失")
        located = {
            "public_id": version["public_id"],
            "file_id": chosen["public_id"] if chosen is not None else "",
            "version_number": version["version_number"],
            "original_filename": filename,
            "preview_kind": preview_kind,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "sha256": sha256,
        }
        return located, path

    def _project_by_public_id(self, public_id: str) -> dict:
        with db_session(self.settings.db_path) as conn:
            row = conn.execute(
                """
                SELECT p.*, COUNT(a.id) AS artifact_count
                FROM projects p
                LEFT JOIN artifacts a ON a.project_id = p.id
                WHERE p.public_id = ?
                GROUP BY p.id
                """,
                (public_id,),
            ).fetchone()
        if row is None:
            raise LibraryError(404, "项目不存在")
        return _project_dto(row)

    def _drain_if_sync(self) -> None:
        if self.settings.sync_index:
            from agentshelf.worker import drain_jobs

            drain_jobs(self)

    def _gc_staging(self) -> None:
        cutoff = datetime.now(timezone.utc).timestamp() - 48 * 3600
        for path in self.settings.staging_dir.glob("*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue


def _clean_decision(decision: str | None) -> str | None:
    if decision is None:
        return None
    value = decision.strip().lower()
    if value in {"", "auto"}:
        return None
    if value not in {"new_artifact", "new_version"}:
        raise LibraryError(400, "decision 只能是 new_artifact 或 new_version")
    return value


def _require_sha(value: str) -> str:
    sha = (value or "").strip().lower()
    if not SHA_RE.fullmatch(sha):
        raise LibraryError(400, "暂存编号无效")
    return sha


def _write_staging_meta(staging_dir: Path, sha256: str, filename: str, size_bytes: int) -> None:
    _meta_path(staging_dir, sha256).write_text(
        json.dumps({"filename": filename, "size": size_bytes}, ensure_ascii=False),
        encoding="utf-8",
    )


def _read_staging_meta(staging_dir: Path, sha256: str) -> dict:
    path = _meta_path(staging_dir, sha256)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _meta_path(staging_dir: Path, sha256: str) -> Path:
    return staging_dir / f"{sha256}.json"


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def _set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _require_artifact(conn, public_id: str):
    row = conn.execute("SELECT * FROM artifacts WHERE public_id = ?", (public_id,)).fetchone()
    if row is None:
        raise LibraryError(404, "找不到这条知识")
    return row


def _require_named(conn, table: str, public_id: str, message: str):
    if table not in {"projects", "tags", "source_agents"}:
        raise LibraryError(500, "内部错误")
    row = conn.execute(f"SELECT * FROM {table} WHERE public_id = ?", (public_id,)).fetchone()
    if row is None:
        raise LibraryError(404, message)
    return row


def _candidates_for_hash(conn, sha256: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT a.public_id AS artifact_id, a.title, v.version_number, v.public_id AS version_id,
               vf.original_filename AS filename
        FROM version_files vf
        JOIN artifact_versions v ON v.id = vf.version_id
        JOIN artifacts a ON a.id = v.artifact_id
        WHERE vf.sha256 = ?
        ORDER BY a.updated_at DESC, v.version_number DESC
        """,
        (sha256,),
    ).fetchall()
    grouped: dict[str, dict] = {}
    for row in rows:
        item = grouped.get(row["artifact_id"])
        if item is None:
            item = {
                "artifact_id": row["artifact_id"],
                "title": row["title"],
                "filename": row["filename"],
                "versions": [],
            }
            grouped[row["artifact_id"]] = item
        if row["version_number"] not in item["versions"]:
            item["versions"].append(row["version_number"])
    return list(grouped.values())


def _resolve_project(conn, name: str) -> int | None:
    cleaned = name.strip()
    if not cleaned:
        return None
    row = conn.execute("SELECT id FROM projects WHERE name = ? COLLATE NOCASE", (cleaned,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO projects(public_id, name, description, created_at, updated_at) VALUES(?, ?, '', ?, ?)",
        (str(uuid.uuid4()), cleaned, now_iso(), now_iso()),
    )
    return int(cur.lastrowid)


def _resolve_agent(conn, name: str) -> int | None:
    cleaned = name.strip()
    if not cleaned:
        return None
    row = conn.execute("SELECT id FROM source_agents WHERE name = ? COLLATE NOCASE", (cleaned,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO source_agents(public_id, name, note, created_at) VALUES(?, ?, '', ?)",
        (str(uuid.uuid4()), cleaned, now_iso()),
    )
    return int(cur.lastrowid)


def _get_or_create_tag(conn, name: str) -> int:
    row = conn.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO tags(public_id, name, created_at) VALUES(?, ?, ?)",
        (str(uuid.uuid4()), name, now_iso()),
    )
    return int(cur.lastrowid)


def _replace_tags(conn, artifact_pk: int, tags: list[str]) -> None:
    conn.execute("DELETE FROM artifact_tags WHERE artifact_id = ?", (artifact_pk,))
    seen: set[str] = set()
    for name in tags:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        conn.execute(
            "INSERT OR IGNORE INTO artifact_tags(artifact_id, tag_id) VALUES(?, ?)",
            (artifact_pk, _get_or_create_tag(conn, name)),
        )


def _ensure_file_object(conn, sha256: str, size_bytes: int, mime: str, relative: str) -> tuple[int, bool]:
    row = conn.execute("SELECT id FROM file_objects WHERE sha256 = ?", (sha256,)).fetchone()
    if row:
        return int(row["id"]), False
    cur = conn.execute(
        """
        INSERT INTO file_objects(sha256, size_bytes, mime_type, relative_path, created_at)
        VALUES(?, ?, ?, ?, ?)
        """,
        (sha256, size_bytes, mime, relative, now_iso()),
    )
    return int(cur.lastrowid), True


def _insert_artifact(conn, title: str, description: str, project: str, source_agent: str) -> tuple[int, str]:
    public_id = str(uuid.uuid4())
    ts = now_iso()
    cur = conn.execute(
        """
        INSERT INTO artifacts(public_id, title, description, project_id, source_agent_id, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (public_id, title, description, _resolve_project(conn, project), _resolve_agent(conn, source_agent), ts, ts),
    )
    return int(cur.lastrowid), public_id


def _insert_version(
    conn,
    *,
    artifact_pk: int,
    file_object_id: int,
    filename: str,
    mime: str,
    size_bytes: int,
    sha256: str,
    preview_kind: str,
    note: str = "",
    extracted_text: str = "",
    extract_status: str = "pending",
    members: list[dict] | None = None,
) -> dict:
    if not members:
        members = [
            {
                "file_object_id": file_object_id,
                "filename": filename,
                "mime": mime,
                "size_bytes": size_bytes,
                "sha256": sha256,
                "preview_kind": preview_kind,
                "extracted_text": "",
                "extract_status": "pending",
                "extract_error": "",
            }
        ]
    first = members[0]
    number_row = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) AS n FROM artifact_versions WHERE artifact_id = ?",
        (artifact_pk,),
    ).fetchone()
    number = int(number_row["n"]) + 1
    public_id = str(uuid.uuid4())
    cur = conn.execute(
        """
        INSERT INTO artifact_versions(
          public_id, artifact_id, version_number, file_object_id, original_filename, mime_type,
          size_bytes, sha256, note, preview_kind, extracted_text, extract_status, created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            public_id,
            artifact_pk,
            number,
            int(first["file_object_id"]),
            first["filename"],
            first["mime"],
            int(first["size_bytes"]),
            first["sha256"],
            note,
            first["preview_kind"],
            extracted_text,
            extract_status,
            now_iso(),
        ),
    )
    version_pk = int(cur.lastrowid)
    for position, member in enumerate(members):
        conn.execute(
            """
            INSERT INTO version_files(
              public_id, version_id, position, file_object_id, original_filename, mime_type,
              size_bytes, sha256, preview_kind, extracted_text, extract_status, extract_error
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                version_pk,
                position,
                int(member["file_object_id"]),
                member["filename"],
                member["mime"],
                int(member["size_bytes"]),
                member["sha256"],
                member["preview_kind"],
                member.get("extracted_text") or "",
                member.get("extract_status") or "pending",
                member.get("extract_error") or "",
            ),
        )
    return {"id": version_pk, "public_id": public_id, "version_number": number}


def _touch_artifact(conn, artifact_pk: int, version_pk: int) -> None:
    conn.execute(
        "UPDATE artifacts SET current_version_id = ?, updated_at = ? WHERE id = ?",
        (version_pk, now_iso(), artifact_pk),
    )


def _apply_metadata(conn, artifact_pk: int, title: str | None, description: str, project: str, source_agent: str, tags: list[str] | None) -> None:
    sets = ["updated_at = ?"]
    params: list[object] = [now_iso()]
    if title is not None:
        sets.append("title = ?")
        params.append(title)
    if description.strip():
        sets.append("description = ?")
        params.append(description.strip())
    if project.strip():
        sets.append("project_id = ?")
        params.append(_resolve_project(conn, project))
    if source_agent.strip():
        sets.append("source_agent_id = ?")
        params.append(_resolve_agent(conn, source_agent))
    params.append(artifact_pk)
    conn.execute(f"UPDATE artifacts SET {', '.join(sets)} WHERE id = ?", params)
    if tags is not None:
        _replace_tags(conn, artifact_pk, tags)


def _enqueue(conn, version_pk: int) -> None:
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO jobs(kind, payload, status, created_at, updated_at)
        VALUES('index_version', ?, 'pending', ?, ?)
        """,
        (json.dumps({"version_id": version_pk}), ts, ts),
    )


def _reindex_artifact(conn, artifact_pk: int) -> None:
    rows = conn.execute("SELECT id FROM artifact_versions WHERE artifact_id = ?", (artifact_pk,)).fetchall()
    for row in rows:
        _reindex_version(conn, int(row["id"]))


def _reindex_version(conn, version_pk: int) -> None:
    row = conn.execute(
        """
        SELECT v.id, v.artifact_id, v.original_filename, v.extracted_text,
               a.title, a.description, p.name AS project_name, s.name AS source_name
        FROM artifact_versions v
        JOIN artifacts a ON a.id = v.artifact_id
        LEFT JOIN projects p ON p.id = a.project_id
        LEFT JOIN source_agents s ON s.id = a.source_agent_id
        WHERE v.id = ?
        """,
        (version_pk,),
    ).fetchone()
    if row is None:
        return
    tags = " ".join(_tag_names_by_pk(conn, int(row["artifact_id"])))
    filenames = [
        item["original_filename"]
        for item in conn.execute(
            "SELECT original_filename FROM version_files WHERE version_id = ? ORDER BY position, id",
            (version_pk,),
        ).fetchall()
    ]
    filename = " ".join(filenames) or row["original_filename"] or ""
    conn.execute("DELETE FROM artifact_fts WHERE version_id = ?", (str(version_pk),))
    conn.execute(
        """
        INSERT INTO artifact_fts(version_id, artifact_id, title, description, filename, body, tags, project, source)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(row["id"]),
            str(row["artifact_id"]),
            row["title"] or "",
            row["description"] or "",
            filename,
            row["extracted_text"] or "",
            tags,
            row["project_name"] or "",
            row["source_name"] or "",
        ),
    )


def _tag_names_by_pk(conn, artifact_pk: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT t.name FROM tags t
        JOIN artifact_tags at ON at.tag_id = t.id
        WHERE at.artifact_id = ?
        ORDER BY t.name COLLATE NOCASE
        """,
        (artifact_pk,),
    ).fetchall()
    return [row["name"] for row in rows]


def _tag_names(conn, artifact_pk: int) -> list[str]:
    return _tag_names_by_pk(conn, artifact_pk)


def _gc_file_object(conn, file_object_id: int) -> str | None:
    versions = conn.execute(
        "SELECT COUNT(*) AS n FROM artifact_versions WHERE file_object_id = ?",
        (file_object_id,),
    ).fetchone()
    files = conn.execute(
        "SELECT COUNT(*) AS n FROM version_files WHERE file_object_id = ?",
        (file_object_id,),
    ).fetchone()
    if int(versions["n"]) > 0 or int(files["n"]) > 0:
        return None
    obj = conn.execute("SELECT relative_path FROM file_objects WHERE id = ?", (file_object_id,)).fetchone()
    conn.execute("DELETE FROM file_objects WHERE id = ?", (file_object_id,))
    if obj is None:
        return None
    return str(obj["relative_path"])


def _filter_clauses(project: str, tag: str, source: str, kind: str) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if project:
        clauses.append("p.name = ? COLLATE NOCASE")
        params.append(project)
    if source:
        clauses.append("s.name = ? COLLATE NOCASE")
        params.append(source)
    if kind:
        clauses.append(
            """(
                v.preview_kind = ? OR EXISTS (
                    SELECT 1 FROM version_files vf
                    WHERE vf.version_id = v.id AND vf.preview_kind = ?
                )
            )"""
        )
        params.extend([kind, kind])
    if tag:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM artifact_tags at
                JOIN tags t ON t.id = at.tag_id
                WHERE at.artifact_id = a.id AND t.name = ? COLLATE NOCASE
            )"""
        )
        params.append(tag)
    return clauses, params


def _search_row(conn, row, query: str) -> dict:
    artifact_pk = row["artifact_pk"] if "artifact_pk" in row.keys() else None
    if artifact_pk is None:
        found = conn.execute("SELECT id FROM artifacts WHERE public_id = ?", (row["artifact_id"],)).fetchone()
        artifact_pk = int(found["id"]) if found else 0
    snippet = ""
    if query:
        body = row["body_snippet"] if "body_snippet" in row.keys() else ""
        title = row["title_snippet"] if "title_snippet" in row.keys() else ""
        snippet = body or title or ""
    counted = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM version_files vf
        JOIN artifact_versions v ON v.id = vf.version_id
        WHERE v.public_id = ?
        """,
        (row["version_id"],),
    ).fetchone()
    file_count = int(counted["n"]) if counted else 1
    return {
        "artifact_id": row["artifact_id"],
        "version_id": row["version_id"],
        "version_number": row["version_number"],
        "title": row["title"],
        "description": row["description"] or "",
        "filename": row["filename"],
        "mime_type": row["mime_type"],
        "preview_kind": row["preview_kind"],
        "sha256": row["sha256"],
        "project": row["project_name"],
        "source_agent": row["source_name"],
        "tags": _tag_names(conn, int(artifact_pk)) if artifact_pk else [],
        "updated_at": row["updated_at"],
        "is_current": bool(row["is_current"]),
        "file_count": file_count or 1,
        "snippet": snippet,
    }


def _version_search_row(conn, version_pk: int):
    return conn.execute(
        """
        SELECT a.id AS artifact_pk, a.public_id AS artifact_id, v.public_id AS version_id, v.version_number,
               a.title, a.description, a.updated_at, v.original_filename AS filename,
               v.mime_type, v.preview_kind, v.sha256, v.extracted_text,
               p.name AS project_name, s.name AS source_name,
               a.current_version_id = v.id AS is_current
        FROM artifact_versions v
        JOIN artifacts a ON a.id = v.artifact_id
        LEFT JOIN projects p ON p.id = a.project_id
        LEFT JOIN source_agents s ON s.id = a.source_agent_id
        WHERE v.id = ?
        """,
        (version_pk,),
    ).fetchone()


def _artifact_detail(conn, public_id: str) -> dict:
    row = conn.execute(
        """
        SELECT a.*, p.public_id AS project_public_id, p.name AS project_name,
               s.public_id AS agent_public_id, s.name AS agent_name
        FROM artifacts a
        LEFT JOIN projects p ON p.id = a.project_id
        LEFT JOIN source_agents s ON s.id = a.source_agent_id
        WHERE a.public_id = ?
        """,
        (public_id,),
    ).fetchone()
    if row is None:
        raise LibraryError(404, "找不到这条知识")
    versions = conn.execute(
        "SELECT * FROM artifact_versions WHERE artifact_id = ? ORDER BY version_number DESC",
        (row["id"],),
    ).fetchall()
    current = next((item for item in versions if item["id"] == row["current_version_id"]), None)
    return {
        "id": row["public_id"],
        "title": row["title"],
        "description": row["description"],
        "project": None
        if row["project_name"] is None
        else {"id": row["project_public_id"], "name": row["project_name"]},
        "source_agent": None
        if row["agent_name"] is None
        else {"id": row["agent_public_id"], "name": row["agent_name"]},
        "tags": _tag_names(conn, int(row["id"])),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version_count": len(versions),
        "current_version": None
        if current is None
        else _version_dto(current, row["current_version_id"], _files_for_version(conn, int(current["id"]))),
        "versions": [_version_dto(item, row["current_version_id"], _files_for_version(conn, int(item["id"]))) for item in versions],
    }


def _version_dto(row, current_id: int | None, files: list[dict] | None = None) -> dict:
    listed = files or []
    return {
        "id": row["public_id"],
        "version_number": row["version_number"],
        "filename": row["original_filename"],
        "mime_type": row["mime_type"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "note": row["note"],
        "preview_kind": row["preview_kind"],
        "extract_status": row["extract_status"],
        "extract_error": row["extract_error"],
        "created_at": row["created_at"],
        "is_current": row["id"] == current_id,
        "file_count": len(listed) or 1,
        "files": listed,
    }


def _file_dto(row) -> dict:
    return {
        "id": row["public_id"],
        "filename": row["original_filename"],
        "mime_type": row["mime_type"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "preview_kind": row["preview_kind"],
        "extract_status": row["extract_status"],
        "extract_error": row["extract_error"],
    }


def _files_for_version(conn, version_pk: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM version_files WHERE version_id = ? ORDER BY position, id",
        (version_pk,),
    ).fetchall()
    return [_file_dto(row) for row in rows]


def _members_of(conn, version_pk: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT vf.*, f.relative_path
        FROM version_files vf
        JOIN file_objects f ON f.id = vf.file_object_id
        WHERE vf.version_id = ?
        ORDER BY vf.position, vf.id
        """,
        (version_pk,),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "file_object_id": int(row["file_object_id"]),
            "filename": row["original_filename"],
            "mime": row["mime_type"],
            "size_bytes": int(row["size_bytes"]),
            "sha256": row["sha256"],
            "preview_kind": row["preview_kind"],
            "extracted_text": row["extracted_text"],
            "extract_status": row["extract_status"],
            "extract_error": row["extract_error"],
            "relative_path": row["relative_path"],
        }
        for row in rows
    ]


def _version_signature(conn, version_pk: int) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT sha256 FROM version_files WHERE version_id = ? ORDER BY sha256",
        (version_pk,),
    ).fetchall()
    if rows:
        return tuple(row["sha256"] for row in rows)
    version = conn.execute("SELECT sha256 FROM artifact_versions WHERE id = ?", (version_pk,)).fetchone()
    if version is None:
        return ()
    return (version["sha256"],)


def _version_with_signature(conn, artifact_pk: int, shas: list[str]):
    target = tuple(sorted(shas))
    versions = conn.execute("SELECT id, version_number FROM artifact_versions WHERE artifact_id = ?", (artifact_pk,)).fetchall()
    for version in versions:
        if _version_signature(conn, int(version["id"])) == target:
            return version
    return None


def _bundle_signature(shas: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(shas)).encode()).hexdigest()


def _bundle_manifest_path(staging_dir: Path, signature: str) -> Path:
    return staging_dir / f"{signature}.bundle.json"


def _write_bundle_manifest(staging_dir: Path, signature: str, files: list[dict]) -> None:
    payload = {
        "files": [
            {"sha256": item["sha256"], "filename": item["filename"], "size_bytes": int(item["size_bytes"])} for item in files
        ]
    }
    path = _bundle_manifest_path(staging_dir, signature)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, path)


def _read_bundle_manifest(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("files") or [])


def _candidates_for_signature(conn, shas: list[str]) -> list[dict]:
    target = tuple(sorted(shas))
    rows = conn.execute(
        """
        SELECT a.public_id AS artifact_id, a.title, a.updated_at, v.id AS version_pk, v.version_number,
               v.original_filename AS filename
        FROM artifact_versions v
        JOIN artifacts a ON a.id = v.artifact_id
        ORDER BY a.updated_at DESC, v.version_number DESC
        """
    ).fetchall()
    grouped: dict[str, dict] = {}
    for row in rows:
        if _version_signature(conn, int(row["version_pk"])) != target:
            continue
        item = grouped.get(row["artifact_id"])
        if item is None:
            item = {
                "artifact_id": row["artifact_id"],
                "title": row["title"],
                "filename": row["filename"],
                "versions": [],
            }
            grouped[row["artifact_id"]] = item
        if row["version_number"] not in item["versions"]:
            item["versions"].append(row["version_number"])
    return list(grouped.values())


def _project_dto(row) -> dict:
    return {
        "id": row["public_id"],
        "name": row["name"],
        "description": row["description"],
        "artifact_count": row["artifact_count"] if "artifact_count" in row.keys() else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
