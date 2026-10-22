from __future__ import annotations

import hashlib
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from agentshelf.config import Settings, load_settings
from agentshelf.errors import LibraryError
from agentshelf.library import Library
from agentshelf.security import check_token
from agentshelf.storage import ensure_space, safe_filename
from agentshelf.worker import Worker

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def create_app(settings: Settings | None = None, *, testing: bool = False, embedder=None) -> FastAPI:
    resolved = settings or load_settings()
    library = Library(resolved, embedder=embedder)
    worker = Worker(library)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not resolved.sync_index:
            worker.start()
        yield
        worker.stop()
        if getattr(app.state, "advertise_port", None):
            _clear_runtime(resolved)

    app = FastAPI(title="AgentShelf", version="0.1.0", lifespan=lifespan)
    app.state.library = library
    app.state.worker = worker
    app.state.testing = testing
    app.state.settings = resolved

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(tauri://localhost|https?://(localhost|127\.0\.0\.1)(:\d+)?|https?://tauri\.localhost)$",
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Content-SHA256"],
    )

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.client.host if request.client else ""
        allowed = set(LOCAL_HOSTS)
        if app.state.testing:
            allowed.add("testclient")
        if host not in allowed:
            return JSONResponse(status_code=403, content={"detail": "仅允许本机访问"})
        return await call_next(request)

    @app.exception_handler(LibraryError)
    async def on_library_error(_request: Request, exc: LibraryError):
        body = {"detail": exc.message, **exc.extra}
        return JSONResponse(status_code=exc.status, content=body)

    def require_token(
        authorization: Annotated[str | None, Header()] = None,
        x_agentshelf_token: Annotated[str | None, Header()] = None,
    ) -> None:
        provided = ""
        if authorization and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        elif x_agentshelf_token:
            provided = x_agentshelf_token.strip()
        if not check_token(provided, library.token):
            raise HTTPException(status_code=401, detail="无效的本地访问令牌")

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": "0.1.0"}

    @app.get("/api/status", dependencies=[Depends(require_token)])
    def status():
        return library.status()

    @app.get("/api/jobs", dependencies=[Depends(require_token)])
    def jobs():
        return {"items": library.list_jobs()}

    @app.post("/api/ingest", dependencies=[Depends(require_token)])
    async def ingest(
        file: UploadFile | None = File(None),
        files: list[UploadFile] | None = File(None),
        title: str = Form(""),
        description: str = Form(""),
        project: str = Form(""),
        tags: str = Form(""),
        source_agent: str = Form(""),
        decision: str = Form(""),
        artifact_id: str = Form(""),
    ):
        selected = [item for item in [file, *(files or [])] if item is not None and (item.filename or "").strip()]
        if not selected:
            raise HTTPException(status_code=400, detail="请选择文件")
        staged: list[tuple[Path, str, int, str]] = []
        for item in selected:
            filename = safe_filename(item.filename or "")
            staging, sha256, size_bytes = await _save_upload(item, resolved.staging_dir, resolved.max_upload_bytes)
            staged.append((staging, sha256, size_bytes, filename))
        fields = {
            "title": title,
            "description": description,
            "project": project,
            "tags": tags,
            "source_agent": source_agent,
            "decision": decision,
            "artifact_id": artifact_id or None,
        }
        if len(staged) == 1:
            staging, sha256, size_bytes, filename = staged[0]
            result = library.ingest_file(staging, sha256, size_bytes, filename, **fields)
        else:
            result = library.ingest_bundle(staged, **fields)
        return _outcome(result)

    @app.post("/api/ingest/confirm", dependencies=[Depends(require_token)])
    def confirm(body: ConfirmIn):
        result = library.confirm(
            body.staging_id,
            body.decision,
            artifact_id=body.artifact_id,
            title=body.title,
            description=body.description,
            project=body.project,
            tags=body.tags,
            source_agent=body.source_agent,
            filename=body.filename,
        )
        return _outcome(result)

    @app.get("/api/artifacts", dependencies=[Depends(require_token)])
    def artifacts(
        q: str = "",
        project: str = "",
        tag: str = "",
        source: str = "",
        kind: str = "",
        mode: str = "keyword",
        limit: int = 40,
        offset: int = 0,
    ):
        return library.query(q=q, project=project, tag=tag, source=source, kind=kind, mode=mode, limit=limit, offset=offset)

    @app.get("/api/search", dependencies=[Depends(require_token)])
    def search(
        q: str = "",
        project: str = "",
        tag: str = "",
        source: str = "",
        kind: str = "",
        mode: str = "keyword",
        limit: int = 40,
        offset: int = 0,
    ):
        return library.query(q=q, project=project, tag=tag, source=source, kind=kind, mode=mode, limit=limit, offset=offset)

    @app.get("/api/artifacts/{artifact_id}", dependencies=[Depends(require_token)])
    def get_artifact(artifact_id: str):
        return library.get_artifact(artifact_id)

    @app.patch("/api/artifacts/{artifact_id}", dependencies=[Depends(require_token)])
    def patch_artifact(artifact_id: str, body: ArtifactUpdate):
        return library.update_artifact(
            artifact_id,
            title=body.title,
            description=body.description,
            project=body.project,
            tags=body.tags,
            source_agent=body.source_agent,
        )

    @app.delete("/api/artifacts/{artifact_id}", dependencies=[Depends(require_token)])
    def delete_artifact(artifact_id: str):
        return library.delete_artifact(artifact_id)

    @app.get("/api/artifacts/{artifact_id}/versions", dependencies=[Depends(require_token)])
    def versions(artifact_id: str):
        return {"items": library.list_versions(artifact_id)}

    @app.post("/api/artifacts/{artifact_id}/versions/{version_id}/restore", dependencies=[Depends(require_token)])
    def restore(artifact_id: str, version_id: str):
        return library.restore_version(artifact_id, version_id)

    @app.get("/api/artifacts/{artifact_id}/preview", dependencies=[Depends(require_token)])
    def preview(artifact_id: str, version_id: str | None = None, file_id: str | None = None):
        return library.preview(artifact_id, version_id, file_id)

    @app.get("/api/artifacts/{artifact_id}/download", dependencies=[Depends(require_token)])
    def download(artifact_id: str, version_id: str | None = None, file_id: str | None = None):
        path, version = library.locate_download(artifact_id, version_id, file_id)
        filename = quote(version["original_filename"])
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=version["original_filename"],
            headers={
                "X-Content-SHA256": version["sha256"],
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            },
        )

    @app.get("/api/artifacts/{artifact_id}/verify", dependencies=[Depends(require_token)])
    def verify(artifact_id: str, version_id: str | None = None, file_id: str | None = None):
        return library.verify_file(artifact_id, version_id, file_id)

    @app.get("/api/projects", dependencies=[Depends(require_token)])
    def list_projects():
        return {"items": library.list_projects()}

    @app.post("/api/projects", dependencies=[Depends(require_token)])
    def create_project(body: ProjectIn):
        return library.create_project(body.name, body.description)

    @app.patch("/api/projects/{project_id}", dependencies=[Depends(require_token)])
    def update_project(project_id: str, body: ProjectIn):
        return library.update_project(project_id, body.name, body.description)

    @app.delete("/api/projects/{project_id}", dependencies=[Depends(require_token)])
    def delete_project(project_id: str):
        return library.delete_project(project_id)

    @app.get("/api/tags", dependencies=[Depends(require_token)])
    def list_tags():
        return {"items": library.list_tags()}

    @app.post("/api/tags", dependencies=[Depends(require_token)])
    def create_tag(body: NameIn):
        return library.create_tag(body.name)

    @app.patch("/api/tags/{tag_id}", dependencies=[Depends(require_token)])
    def update_tag(tag_id: str, body: NameIn):
        return library.update_tag(tag_id, body.name)

    @app.delete("/api/tags/{tag_id}", dependencies=[Depends(require_token)])
    def delete_tag(tag_id: str):
        return library.delete_tag(tag_id)

    @app.get("/api/agents", dependencies=[Depends(require_token)])
    def list_agents():
        return {"items": library.list_agents()}

    @app.post("/api/agents", dependencies=[Depends(require_token)])
    def create_agent(body: AgentIn):
        return library.create_agent(body.name, body.note)

    @app.patch("/api/agents/{agent_id}", dependencies=[Depends(require_token)])
    def update_agent(agent_id: str, body: AgentIn):
        return library.update_agent(agent_id, body.name, body.note)

    @app.delete("/api/agents/{agent_id}", dependencies=[Depends(require_token)])
    def delete_agent(agent_id: str):
        return library.delete_agent(agent_id)

    @app.get("/api/backups", dependencies=[Depends(require_token)])
    def backups():
        return {"items": library.backups()}

    @app.post("/api/backups", dependencies=[Depends(require_token)])
    def create_backup():
        return library.make_backup()

    @app.get("/api/backups/{name}/download", dependencies=[Depends(require_token)])
    def download_backup(name: str):
        path = library.backup_path(name)
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @app.post("/api/backups/{name}/restore", dependencies=[Depends(require_token)])
    def restore_named(name: str):
        path = library.backup_path(name)
        return _restore(path)

    @app.post("/api/backups/upload-restore", dependencies=[Depends(require_token)])
    async def restore_upload(file: UploadFile = File(...)):
        safe_filename(file.filename or "backup.zip")
        target = resolved.backups_dir / f".upload-{uuid.uuid4().hex}.zip"
        size = 0
        try:
            with target.open("wb") as handle:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 2 * 1024 * 1024 * 1024:
                        raise LibraryError(413, "备份文件过大")
                    handle.write(chunk)
            return _restore(target)
        finally:
            target.unlink(missing_ok=True)

    @app.post("/api/semantic/import", dependencies=[Depends(require_token)])
    def import_model(body: PathIn):
        return library.import_model(body.path)

    @app.post("/api/semantic/enable", dependencies=[Depends(require_token)])
    def enable_semantic(body: EnableIn):
        return library.set_semantic_enabled(body.enabled)

    @app.post("/api/semantic/rebuild", dependencies=[Depends(require_token)])
    def rebuild_semantic():
        return library.rebuild_semantic()

    @app.delete("/api/semantic", dependencies=[Depends(require_token)])
    def clear_semantic():
        return library.clear_semantic()

    @app.post("/api/admin/shutdown", dependencies=[Depends(require_token)])
    def shutdown():
        server = getattr(app.state, "uvicorn_server", None)
        if server is not None:
            server.should_exit = True
        return {"ok": True}

    def _restore(path: Path) -> dict:
        worker.stop()
        try:
            return library.restore_from(path)
        finally:
            if not resolved.sync_index:
                worker.start()

    return app


class ConfirmIn(BaseModel):
    staging_id: str
    decision: str
    artifact_id: str | None = None
    title: str = ""
    description: str = ""
    project: str = ""
    tags: str = ""
    source_agent: str = ""
    filename: str = ""


class ArtifactUpdate(BaseModel):
    title: str
    description: str = ""
    project: str = ""
    tags: str = ""
    source_agent: str = ""


class ProjectIn(BaseModel):
    name: str
    description: str = ""


class NameIn(BaseModel):
    name: str = Field(min_length=1)


class AgentIn(BaseModel):
    name: str
    note: str = ""


class PathIn(BaseModel):
    path: str


class EnableIn(BaseModel):
    enabled: bool


def _outcome(result: dict) -> JSONResponse:
    status = result.get("status")
    code = 201 if status == "created" else 200
    if status == "needs_decision":
        code = 409
    return JSONResponse(status_code=code, content=result)


async def _save_upload(upload: UploadFile, staging_dir: Path, max_bytes: int) -> tuple[Path, str, int]:
    ensure_space(staging_dir, 1)
    temporary = staging_dir / f".upload-{uuid.uuid4().hex}"
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise LibraryError(413, "文件超过大小限制")
                ensure_space(staging_dir, len(chunk))
                digest.update(chunk)
                handle.write(chunk)
        sha256 = digest.hexdigest()
        final = staging_dir / sha256
        if final.exists():
            temporary.unlink()
        else:
            os.replace(temporary, final)
        return final, sha256, size
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _clear_runtime(settings: Settings) -> None:
    runtime = settings.runtime_path
    try:
        if runtime.exists():
            runtime.unlink()
    except OSError:
        return
