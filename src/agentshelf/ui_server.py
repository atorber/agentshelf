"""把构建好的界面以本机静态站点提供，并把 /api 转到本地后端。"""

from __future__ import annotations

import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from agentshelf.config import DEFAULT_MAX_UPLOAD, load_settings
from agentshelf.server import read_runtime

UI_HOST = "127.0.0.1"
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def bundled_desktop() -> Path:
    import sys

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "desktop"
    raise RuntimeError("界面资源不在启动器里。请使用发布的启动器，或在源码目录运行 scripts/launch.py。")


def safe_static(root: Path, url_path: str) -> Path | None:
    base = root.resolve()
    relative = unquote(url_path).split("?", 1)[0]
    if "\x00" in relative:
        return None
    if relative in {"", "/"}:
        relative = "index.html"
    else:
        relative = relative.lstrip("/")
    candidate = (base / relative).resolve()
    if not candidate.is_relative_to(base) or not candidate.is_file():
        return None
    return candidate


def content_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(path.name)
    kind = guessed or "application/octet-stream"
    if kind.startswith("text/") or kind in {"application/javascript", "image/svg+xml"}:
        return f"{kind}; charset=utf-8"
    return kind


def backend_origin() -> str:
    session = read_runtime(load_settings())
    if not session:
        return "http://127.0.0.1:8765"
    host = str(session.get("host") or "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        host = "127.0.0.1"
    return f"http://{host}:{int(session['port'])}"


def read_local_token() -> str:
    path = load_settings().token_path
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class InterfaceServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_handler(root: Path):
    desktop = root.resolve()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_HEAD(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def do_PUT(self) -> None:  # noqa: N802
            self._dispatch()

        def do_PATCH(self) -> None:  # noqa: N802
            self._dispatch()

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch()

        def _dispatch(self) -> None:
            self.close_connection = True
            path = urlsplit(self.path).path
            if path.startswith("/api"):
                self._proxy()
                return
            self._static()

        def _static(self) -> None:
            target = safe_static(desktop, urlsplit(self.path).path)
            if target is None:
                self.send_error(404)
                return
            payload = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type(target))
            self.send_header("Content-Length", str(len(payload)))
            cache = "no-store" if target.name == "index.html" else "public, max-age=3600"
            self.send_header("Cache-Control", cache)
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def _proxy(self) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            if length > DEFAULT_MAX_UPLOAD:
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else None
            headers = {key: value for key, value in self.headers.items() if key.lower() not in HOP_HEADERS}
            if "authorization" not in {key.lower() for key in headers}:
                token = read_local_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
            request = Request(backend_origin() + self.path, data=body, headers=headers, method=self.command)
            try:
                with urlopen(request, timeout=120) as response:
                    payload = response.read()
                    status = response.status
                    forwarded = response.headers
            except HTTPError as exc:
                payload = exc.read()
                status = exc.code
                forwarded = exc.headers
            except URLError:
                message = "本地服务不可用".encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(message)))
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(message)
                return
            self.send_response(status)
            for key, value in forwarded.items():
                if key.lower() in HOP_HEADERS:
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def log_message(self, fmt: str, *args) -> None:
            logging.getLogger("agentshelf.ui").info("%s - %s", self.address_string(), fmt % args)

    return Handler


def serve_ui(port: int, root: Path | None = None) -> None:
    desktop = root or bundled_desktop()
    if not (desktop / "index.html").is_file():
        raise SystemExit(f"启动器里没有界面文件：{desktop}")
    server = InterfaceServer((UI_HOST, port), make_handler(desktop))
    print(f"桌面界面监听 http://{UI_HOST}:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
