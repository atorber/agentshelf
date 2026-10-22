from __future__ import annotations

import base64
import hashlib
import io
import threading
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[1]
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTSHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENTSHELF_SYNC_INDEX", "1")
    monkeypatch.delenv("AGENTSHELF_HOST", raising=False)
    return tmp_path


@pytest.fixture
def client(data_dir):
    from agentshelf.app import create_app
    from agentshelf.config import load_settings

    app = create_app(load_settings(), testing=True)
    with TestClient(app) as test_client:
        token = (data_dir / "token").read_text(encoding="utf-8").strip()
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


def upload(client: TestClient, filename: str, content: bytes, **fields: str):
    data = {key: value for key, value in fields.items() if value is not None}
    return client.post("/api/ingest", data=data, files={"file": (filename, content, "application/octet-stream")})


def test_health_is_public_and_other_routes_need_token(data_dir):
    from agentshelf.app import create_app
    from agentshelf.config import load_settings

    app = create_app(load_settings(), testing=True)
    with TestClient(app) as test_client:
        assert test_client.get("/api/health").json()["ok"] is True
        denied = test_client.get("/api/artifacts")
        assert denied.status_code == 401


def test_rejects_non_loopback_host(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTSHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENTSHELF_HOST", "0.0.0.0")
    from agentshelf.config import load_settings

    with pytest.raises(RuntimeError):
        load_settings()


def test_token_file_is_user_only(data_dir, client):
    from agentshelf.security import is_user_only

    assert is_user_only(data_dir / "token")
    assert client.get("/api/status").json()["host"] == "127.0.0.1"


def test_filename_does_not_decide_identity_or_overwrite(client):
    first = upload(client, "same.txt", b"alpha-body")
    second = upload(client, "../same.txt", b"beta-body")
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert second.json()["current_version"]["filename"] == "same.txt"


def test_duplicate_content_requires_explicit_choice_and_shares_blob(client, data_dir):
    content = b"identical-final-artifact"
    created = upload(client, "one.md", content, title="第一份")
    assert created.status_code == 201
    pending = upload(client, "two.md", content, title="第二份")
    assert pending.status_code == 409
    body = pending.json()
    assert body["status"] == "needs_decision"
    assert body["candidates"][0]["artifact_id"] == created.json()["id"]
    listed = client.get("/api/artifacts")
    assert listed.json()["total"] == 1

    confirmed = client.post(
        "/api/ingest/confirm",
        json={"staging_id": body["staging_id"], "decision": "new_artifact", "title": "第二份"},
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["stored_new_blob"] is False
    blobs = [path for path in (data_dir / "objects").rglob("*") if path.is_file()]
    assert len(blobs) == 1
    assert hashlib.sha256(blobs[0].read_bytes()).hexdigest() == created.json()["current_version"]["sha256"]


def test_explicit_new_version_and_restore(client):
    created = upload(client, "note.md", b"version-one", title="笔记")
    artifact_id = created.json()["id"]
    appended = upload(
        client,
        "note.md",
        b"version-two",
        title="笔记",
        decision="new_version",
        artifact_id=artifact_id,
    )
    assert appended.status_code == 200
    assert appended.json()["status"] == "version_created"
    assert appended.json()["version_count"] == 2
    first = next(item for item in appended.json()["versions"] if item["version_number"] == 1)
    restored = client.post(f"/api/artifacts/{artifact_id}/versions/{first['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["current_version"]["sha256"] == first["sha256"]
    assert restored.json()["version_count"] == 3
    again = upload(client, "note.md", b"version-two", decision="new_version", artifact_id=artifact_id)
    assert again.json()["status"] == "duplicate_version"


def test_partial_batch_keeps_successful_file(client, monkeypatch):
    kept = upload(client, "kept.txt", b"keep-me")
    assert kept.status_code == 201
    monkeypatch.setenv("AGENTSHELF_MAX_UPLOAD", "8")
    from agentshelf.app import create_app
    from agentshelf.config import load_settings

    limited = create_app(load_settings(), testing=True)
    with TestClient(limited) as other:
        token = kept.json()  # token already on original client
        del token
        other.headers["Authorization"] = client.headers["Authorization"]
        failed = upload(other, "big.txt", b"0123456789abcdef")
        assert failed.status_code == 413
    fetched = client.get(f"/api/artifacts/{kept.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "kept.txt" or fetched.json()["current_version"]["filename"] == "kept.txt"


def test_search_filters_and_snippet(client):
    upload(
        client,
        "report.md",
        "星港归档检索词出现在正文里。".encode(),
        title="周报",
        project="研发",
        tags="报告,内部",
        source_agent="cursor",
        description="本周最终稿",
    )
    upload(client, "other.txt", "无关内容".encode(), title="备忘", project="生活", tags="杂项")
    found = client.get("/api/search", params={"q": "星港归档检索词"})
    assert found.status_code == 200
    items = found.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "周报"
    assert "【" in items[0]["snippet"] and "】" in items[0]["snippet"]
    filtered = client.get("/api/artifacts", params={"project": "研发", "tag": "报告", "source": "cursor", "kind": "markdown"})
    assert filtered.json()["total"] == 1
    empty = client.get("/api/artifacts", params={"project": "生活", "q": "星港归档检索词"})
    assert empty.json()["total"] == 0


def test_previews_for_supported_and_corrupt_files(client):
    samples = {
        "note.md": ("# 标题\n\n正文", "markdown"),
        "plain.txt": ("纯文本", "text"),
        "table.csv": ("name,qty\napple,1\n", "csv"),
        "data.json": ('{"ok": true, "n": 1}', "json"),
    }
    for filename, (text, kind) in samples.items():
        created = upload(client, filename, text.encode())
        preview = client.get(f"/api/artifacts/{created.json()['id']}/preview")
        assert preview.status_code == 200
        body = preview.json()
        assert body["preview_kind"] == kind
        assert not body.get("error")

    csv_id = upload(client, "rows.csv", b"name,qty\napple,2\n").json()["id"]
    csv_preview = client.get(f"/api/artifacts/{csv_id}/preview")
    assert csv_preview.json()["rows"][0] == ["name", "qty"]
    parsed = client.get(f"/api/artifacts/{upload(client, 'obj.json', b'{\"ok\": true}').json()['id']}/preview")
    assert parsed.json()["json"]["ok"] is True

    image = upload(client, "pixel.png", PNG)
    image_preview = client.get(f"/api/artifacts/{image.json()['id']}/preview")
    assert image_preview.json()["preview_kind"] == "image"

    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(72, 72)
    writer.write(buffer)
    pdf = upload(client, "blank.pdf", buffer.getvalue())
    pdf_preview = client.get(f"/api/artifacts/{pdf.json()['id']}/preview")
    assert pdf_preview.json()["preview_kind"] == "pdf"
    assert pdf_preview.json()["page_count"] == 1

    corrupt = upload(client, "broken.pdf", b"%PDF-1.4\nnot-a-real-cross-reference")
    corrupt_preview = client.get(f"/api/artifacts/{corrupt.json()['id']}/preview")
    assert corrupt_preview.status_code == 200
    assert client.get("/api/health").status_code == 200

    disguised = upload(client, "evil.png", b"<script>alert(1)</script>")
    assert disguised.json()["current_version"]["preview_kind"] == "unsupported"
    unsupported = client.get(f"/api/artifacts/{disguised.json()['id']}/preview")
    assert unsupported.json()["preview_kind"] == "unsupported"


def test_one_artifact_can_hold_multiple_files(client):
    created = client.post(
        "/api/ingest",
        data={"title": "方案"},
        files=[
            ("files", ("设计.md", "# 设计\n正文".encode(), "text/markdown")),
            ("files", ("图.png", PNG, "image/png")),
        ],
    )
    assert created.status_code == 201, created.text
    body = created.json()
    version = body["current_version"]
    assert version["file_count"] == 2
    assert [item["filename"] for item in version["files"]] == ["设计.md", "图.png"]
    listed = client.get("/api/artifacts")
    assert listed.json()["items"][0]["file_count"] == 2
    markdown = version["files"][0]
    preview = client.get(f"/api/artifacts/{body['id']}/preview", params={"file_id": markdown["id"]})
    assert preview.status_code == 200
    assert "设计" in preview.json()["text"]
    image = client.get(f"/api/artifacts/{body['id']}/preview", params={"file_id": version["files"][1]["id"]})
    assert image.json()["preview_kind"] == "image"
    found = client.get("/api/artifacts", params={"q": "正文"})
    assert found.json()["total"] == 1
    again = client.post(
        "/api/ingest",
        data={"title": "方案"},
        files=[
            ("files", ("设计.md", "# 设计\n正文".encode(), "text/markdown")),
            ("files", ("图.png", PNG, "image/png")),
        ],
    )
    assert again.status_code == 409
    assert again.json()["status"] == "needs_decision"


def test_download_matches_recorded_hash(client):
    content = "原始文件内容".encode()
    created = upload(client, "raw.txt", content)
    artifact_id = created.json()["id"]
    downloaded = client.get(f"/api/artifacts/{artifact_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == content
    assert downloaded.headers["x-content-sha256"] == hashlib.sha256(content).hexdigest()
    verified = client.get(f"/api/artifacts/{artifact_id}/verify")
    assert verified.json()["ok"] is True


def test_backup_and_restore_roundtrip(client):
    created = upload(client, "keep.md", b"please-restore-me", title="要恢复")
    artifact_id = created.json()["id"]
    backup = client.post("/api/backups")
    assert backup.status_code == 200
    name = backup.json()["name"]
    assert client.delete(f"/api/artifacts/{artifact_id}").status_code == 200
    assert client.get(f"/api/artifacts/{artifact_id}").status_code == 404
    restored = client.post(f"/api/backups/{name}/restore")
    assert restored.status_code == 200
    fetched = client.get(f"/api/artifacts/{artifact_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "要恢复"
    downloaded = client.get(f"/api/artifacts/{artifact_id}/download")
    assert downloaded.content == b"please-restore-me"


def test_rejects_path_traversal_in_backup(client, tmp_path):
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as archive:
        archive.writestr("../evil.txt", "nope")
        archive.writestr("manifest.json", '{"agentshelf_backup": 1}')
        archive.writestr("library.db", "not-a-database")
    response = client.post(
        "/api/backups/upload-restore",
        files={"file": ("agentshelf-20000101-000000.zip", blob.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert not (tmp_path.parent / "evil.txt").exists()


def test_reopen_preserves_library(data_dir):
    from agentshelf.app import create_app
    from agentshelf.config import load_settings

    settings = load_settings()
    app = create_app(settings, testing=True)
    with TestClient(app) as first:
        token = (data_dir / "token").read_text(encoding="utf-8").strip()
        first.headers["Authorization"] = f"Bearer {token}"
        created = upload(first, "persist.txt", b"still-here", title="持久化")
        artifact_id = created.json()["id"]
    reopened = create_app(load_settings(), testing=True)
    with TestClient(reopened) as second:
        second.headers["Authorization"] = f"Bearer {token}"
        fetched = second.get(f"/api/artifacts/{artifact_id}")
        assert fetched.status_code == 200
        assert fetched.json()["title"] == "持久化"


def test_running_jobs_are_requeued_after_restart(data_dir):
    from agentshelf.app import create_app
    from agentshelf.config import load_settings
    from agentshelf.db import db_session
    from agentshelf.library import now_iso
    from agentshelf.worker import recover_interrupted_jobs

    create_app(load_settings(), testing=True)
    with db_session(data_dir / "library.db", write=True) as conn:
        conn.execute(
            """
            INSERT INTO jobs(kind, payload, status, created_at, updated_at)
            VALUES('index_version', '{"version_id": 1}', 'running', ?, ?)
            """,
            (now_iso(), now_iso()),
        )
    assert recover_interrupted_jobs(data_dir / "library.db") == 1
    with db_session(data_dir / "library.db") as conn:
        status = conn.execute("SELECT status FROM jobs").fetchone()["status"]
    assert status == "pending"


def test_disk_full_is_rejected(client, monkeypatch):
    monkeypatch.setattr("agentshelf.storage.free_bytes", lambda _path: 0)
    response = upload(client, "late.txt", b"data")
    assert response.status_code == 507


def test_semantic_is_optional_and_keyword_still_works(client):
    upload(client, "base.txt", "关键词海岸线".encode(), title="海岸")
    keyword = client.get("/api/search", params={"q": "关键词海岸线"})
    assert keyword.json()["total"] == 1
    semantic = client.get("/api/search", params={"q": "海岸", "mode": "semantic"})
    assert semantic.status_code == 409
    status = client.get("/api/status").json()["semantic"]
    assert status["enabled"] is False


def test_semantic_search_uses_injected_local_embedder(data_dir):
    from agentshelf.app import create_app
    from agentshelf.config import load_settings

    class FakeEmbedder:
        dim = 4
        model_type = "fake"

        def embed(self, texts):
            vectors = []
            for text in texts:
                if "苹果" in text:
                    vectors.append([1.0, 0.0, 0.0, 0.0])
                elif "香蕉" in text:
                    vectors.append([0.0, 1.0, 0.0, 0.0])
                else:
                    vectors.append([0.0, 0.0, 1.0, 0.0])
            return vectors

    app = create_app(load_settings(), testing=True, embedder=FakeEmbedder())
    with TestClient(app) as test_client:
        token = (data_dir / "token").read_text(encoding="utf-8").strip()
        test_client.headers["Authorization"] = f"Bearer {token}"
        enabled = test_client.post("/api/semantic/enable", json={"enabled": True})
        assert enabled.status_code == 200
        upload(test_client, "apple.txt", "这是苹果".encode(), title="苹果")
        upload(test_client, "banana.txt", "这是香蕉".encode(), title="香蕉")
        found = test_client.get("/api/search", params={"q": "苹果", "mode": "semantic"})
        assert found.status_code == 200
        assert found.json()["items"][0]["title"] == "苹果"
        cleared = test_client.delete("/api/semantic")
        assert cleared.json()["enabled"] is False
        still = test_client.get("/api/search", params={"q": "苹果"})
        assert still.status_code == 200
        assert still.json()["total"] >= 1


def test_sources_do_not_reference_external_services():
    needles = ("openai.com", "cdn.jsdelivr.net", "fonts.googleapis.com", "sentry.io", "telemetry.cursor.sh")
    allowed_suffixes = {".py", ".ts", ".tsx", ".html", ".css", ".js"}
    for path in ROOT.rglob("*"):
        if any(part in {".venv", "node_modules", "target", ".git", "tests"} for part in path.parts):
            continue
        if path.suffix not in allowed_suffixes or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in needles:
            assert needle not in text, f"{path} 包含外部地址 {needle}"


def test_cli_archives_through_the_local_api(data_dir, tmp_path):
    from agentshelf.cli import app as cli_app
    from agentshelf.server import pick_port, serve, stop_running
    from typer.testing import CliRunner

    port = pick_port("127.0.0.1", 8765)
    thread = threading.Thread(target=lambda: serve(port), daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        if (data_dir / "runtime.json").exists():
            break
        time.sleep(0.05)
    else:
        raise AssertionError("服务没有在预期时间内就绪")
    target = tmp_path / "final.md"
    target.write_text("命令行归档的最终稿", encoding="utf-8")
    try:
        result = CliRunner().invoke(cli_app, ["archive", str(target), "--title", "命令行产物", "--project", "CLI"])
        assert result.exit_code == 0, result.output
        assert "命令行产物" in result.output
        search = CliRunner().invoke(cli_app, ["search", "命令行归档"])
        assert search.exit_code == 0, search.output
        assert "命令行产物" in search.output
    finally:
        stop_running()
        thread.join(timeout=5)


def test_cli_and_skill_report_the_package_version():
    from agentshelf import __version__
    from agentshelf.cli import app as cli_app
    from typer.testing import CliRunner

    skill = (ROOT / "skill" / "agentshelf-archive" / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = skill.split("---", 2)[1]
    assert f"version: {__version__}" in frontmatter
    result = CliRunner().invoke(cli_app, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == __version__


def test_release_launcher_names_match_the_skill():
    from agentshelf.release_assets import RELEASE_DOWNLOAD, checksum_filename, install_path, launcher_filename

    skill = (ROOT / "skill" / "agentshelf-archive" / "SKILL.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    cases = [
        ("Darwin", "arm64"),
        ("Darwin", "x86_64"),
        ("Linux", "x86_64"),
        ("Linux", "aarch64"),
        ("Windows", "AMD64"),
    ]
    deploy = skill.split("## 部署", 1)[1].split("## 归档", 1)[0]
    steps = "\n".join(line for line in deploy.splitlines() if line.startswith(("1. ", "2. ", "3. ", "4. ", "5. ")))
    assert "git clone" not in skill
    assert RELEASE_DOWNLOAD in skill
    assert steps.index("runtime.json") < steps.index("agentshelf-launcher")
    assert steps.index("agentshelf-launcher") < steps.index("GitHub Release")
    assert steps.index("GitHub Release") < steps.index("~/.agentshelf/app")
    assert steps.index("~/.agentshelf/app") < steps.index("当前工作区包含 `scripts/launch.py`")
    assert "launcher_stem" in workflow
    assert "gh release upload" in workflow
    assert "types: [published]" in workflow
    for system, machine in cases:
        assert launcher_filename(system, machine) in skill
        assert checksum_filename(system, machine).endswith(".sha256")
    assert "~/.agentshelf/bin/agentshelf-launcher" in skill
    assert install_path(Path.home(), "windows") == Path.home() / ".agentshelf" / "bin" / "agentshelf-launcher.exe"


def test_release_launcher_rejects_unknown_platforms():
    import pytest
    from agentshelf.release_assets import launcher_filename

    with pytest.raises(ValueError):
        launcher_filename("Windows", "ARM64")


def test_ui_server_serves_the_interface_and_injects_the_token(tmp_path, monkeypatch):
    import json
    import urllib.error
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from agentshelf.ui_server import InterfaceServer, make_handler, safe_static

    monkeypatch.setenv("AGENTSHELF_DATA_DIR", str(tmp_path))
    (tmp_path / "token").write_text("secret-token\n", encoding="utf-8")
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "index.html").write_text("<html>shelf</html>", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    assert safe_static(desktop, "/") == desktop / "index.html"
    assert safe_static(desktop, "/../secret.txt") is None
    assert safe_static(desktop, "/%2e%2e/secret.txt") is None

    seen: dict[str, str] = {}

    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen["authorization"] = self.headers.get("Authorization") or ""
            seen["path"] = self.path
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    backend_port = backend.server_address[1]
    (tmp_path / "runtime.json").write_text(
        json.dumps({"port": backend_port, "pid": 1, "host": "127.0.0.1"}),
        encoding="utf-8",
    )
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    ui = InterfaceServer(("127.0.0.1", 0), make_handler(desktop))
    ui_port = ui.server_address[1]
    ui_thread = threading.Thread(target=ui.serve_forever, daemon=True)
    ui_thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{ui_port}/", timeout=3) as response:
            assert b"shelf" in response.read()
        with urllib.request.urlopen(f"http://127.0.0.1:{ui_port}/api/health", timeout=3) as response:
            assert response.status == 200
            assert json.loads(response.read())["ok"] is True
        assert seen["authorization"] == "Bearer secret-token"
        assert seen["path"] == "/api/health"
        backend.shutdown()
        backend.server_close()
        with pytest.raises(urllib.error.HTTPError) as unavailable:
            urllib.request.urlopen(f"http://127.0.0.1:{ui_port}/api/health", timeout=3)
        assert unavailable.value.code == 502
        assert "本地服务不可用" in unavailable.value.read().decode("utf-8")
        with urllib.request.urlopen(f"http://127.0.0.1:{ui_port}/", timeout=3) as response:
            assert b"shelf" in response.read()
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(f"http://127.0.0.1:{ui_port}/../secret.txt", timeout=3)
        assert rejected.value.code == 404
    finally:
        ui.shutdown()
        ui.server_close()
        backend.shutdown()
        backend.server_close()
