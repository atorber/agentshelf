from __future__ import annotations

import json
import logging
import os
import socket
import urllib.request
from pathlib import Path

import uvicorn

from agentshelf.app import create_app
from agentshelf.config import PORT_SCAN_END, Settings, load_settings
from agentshelf.library import now_iso


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        access = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(access, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def health_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.8) as response:
            return response.status == 200
    except Exception:
        return False


def read_runtime(settings: Settings) -> dict | None:
    if not settings.runtime_path.exists():
        return None
    try:
        data = json.loads(settings.runtime_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "port" not in data:
        return None
    return data


def running_session(settings: Settings) -> dict | None:
    data = read_runtime(settings)
    if not data:
        return None
    pid = int(data.get("pid") or 0)
    port = int(data.get("port") or 0)
    if not pid_alive(pid) or not health_ok(port):
        return None
    return data


def publish_runtime(settings: Settings, port: int) -> None:
    payload = {
        "port": port,
        "pid": os.getpid(),
        "host": "127.0.0.1",
        "started_at": now_iso(),
        "data_dir": str(settings.data_dir),
    }
    temporary = settings.runtime_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, settings.runtime_path)


def ready_line(payload: dict) -> str:
    return "AGENTSHELF_READY " + json.dumps(payload, ensure_ascii=False)


def pick_port(host: str, preferred: int) -> int:
    candidates = [preferred]
    candidates.extend(port for port in range(8765, PORT_SCAN_END + 1) if port != preferred)
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError("没有可用的本地端口")


def configure_logging(settings: Settings) -> None:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(settings.logs_dir / "agentshelf.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(item, logging.FileHandler) and getattr(item, "baseFilename", "") == handler.baseFilename for item in root.handlers):
        root.addHandler(handler)


def serve(port: int | None = None) -> None:
    settings = load_settings()
    settings.ensure_dirs()
    configure_logging(settings)
    existing = running_session(settings)
    if existing:
        print(
            ready_line(
                {
                    "port": int(existing["port"]),
                    "pid": int(existing["pid"]),
                    "data_dir": str(settings.data_dir),
                    "adopted": True,
                }
            ),
            flush=True,
        )
        return
    chosen = pick_port(settings.host, port or settings.port)
    app = create_app(settings)
    app.state.advertise_port = chosen

    class ReadyServer(uvicorn.Server):
        async def startup(self, sockets=None):  # type: ignore[override]
            await super().startup(sockets=sockets)
            publish_runtime(settings, chosen)
            print(
                ready_line(
                    {
                        "port": chosen,
                        "pid": os.getpid(),
                        "data_dir": str(settings.data_dir),
                        "adopted": False,
                    }
                ),
                flush=True,
            )

    config = uvicorn.Config(app, host=settings.host, port=chosen, log_level="info")
    server = ReadyServer(config)
    app.state.uvicorn_server = server
    server.run()


def stop_running(settings: Settings | None = None) -> bool:
    resolved = settings or load_settings()
    session = read_runtime(resolved)
    if not session:
        return False
    port = int(session.get("port") or 0)
    token_path = resolved.token_path
    token = token_path.read_text(encoding="utf-8").strip() if token_path.exists() else ""
    if port and token:
        _post_shutdown(port, token)
    pid = int(session.get("pid") or 0)
    if pid == os.getpid() or not pid_alive(pid):
        return True
    try:
        os.kill(pid, 15)
    except OSError:
        return False
    return True


def _post_shutdown(port: int, token: str) -> None:
    body = b"{}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/admin/shutdown",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=2).read()
    except Exception:
        return


def session_endpoint(settings: Settings | None = None) -> tuple[int, str, Path]:
    resolved = settings or load_settings()
    session = running_session(resolved)
    if not session:
        raise RuntimeError("本地服务未启动。请先打开 AgentShelf，或运行 agentshelf serve。")
    token = resolved.token_path.read_text(encoding="utf-8").strip() if resolved.token_path.exists() else ""
    if not token:
        raise RuntimeError("找不到本地访问令牌。")
    return int(session["port"]), token, resolved.data_dir
