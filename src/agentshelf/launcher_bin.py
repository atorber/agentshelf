"""发布二进制的启动过程：拉起已打包的后端和本机界面，然后退出。"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from agentshelf.config import load_settings
from agentshelf.server import running_session
from agentshelf.ui_server import UI_HOST

UI_PORT = 1420


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def binary_path() -> Path:
    return Path(sys.executable)


def port_open(port: int) -> bool:
    try:
        with socket.create_connection((UI_HOST, port), timeout=0.4):
            return True
    except OSError:
        return False


def listening_pid(port: int) -> int:
    if os.name == "nt":
        completed = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True)
        needle = f"{UI_HOST}:{port}"
        for line in completed.stdout.splitlines():
            if needle in line and "LISTEN" in line.upper():
                parts = line.split()
                if parts and parts[-1].isdigit():
                    return int(parts[-1])
        return 0
    if not shutil.which("lsof"):
        return 0
    completed = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True)
    for line in completed.stdout.split():
        if line.isdigit():
            return int(line)
    return 0


def process_command(pid: int) -> str:
    if pid <= 0:
        return ""
    if os.name == "nt":
        completed = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/value"],
            capture_output=True,
            text=True,
        )
        return completed.stdout
    completed = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    return completed.stdout


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
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


def read_pid(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return int(payload.get("pid") or 0)


def write_pid(path: Path, pid: int) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"pid": pid}), encoding="utf-8")
    os.replace(temporary, path)


def spawn(command: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "ab", buffering=0)
    env = os.environ.copy()
    # 单文件启动器退出时会删掉自己的解压目录。子进程必须单独解压，不能跟着被删掉。
    for key in ("_PYI_APPLICATION_HOME_DIR", "_PYI_PARENT_PROCESS_LEVEL", "_PYI_ARCHIVE_FILE", "_PYI_SPLASH_IPC"):
        env.pop(key, None)
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    finally:
        handle.close()
    return process.pid


def wait_until(predicate, timeout: float, message: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.3)
    fail(message)


def parse_ui_port(argv: list[str]) -> int:
    if "--port" not in argv:
        return int(os.environ.get("AGENTSHELF_UI_PORT", str(UI_PORT)))
    index = argv.index("--port")
    if index + 1 >= len(argv):
        fail("缺少 --port 的端口号")
    return int(argv[index + 1])


def start_backend(logs: Path) -> dict:
    existing = running_session(load_settings())
    if existing:
        print(f"后端已在运行：http://{UI_HOST}:{int(existing['port'])}")
        return existing
    executable = binary_path()
    print("正在启动后端")
    spawn([str(executable), "serve"], logs / "launcher-backend.log")
    found: dict | None = None

    def ready() -> bool:
        nonlocal found
        found = running_session(load_settings())
        return found is not None

    wait_until(ready, 60, f"后端没有在预期时间内就绪。日志：{logs / 'launcher-backend.log'}")
    assert found is not None
    print(f"后端已启动：http://{UI_HOST}:{int(found['port'])}")
    return found


def interface_belongs(pid: int, executable: Path) -> bool:
    command = process_command(pid).replace("\\", "/")
    return executable.name in command and " ui" in f" {command}"


def start_interface(directory: Path, logs: Path, ui_port: int) -> None:
    state = directory / "desktop.json"
    url = f"http://{UI_HOST}:{ui_port}"
    recorded = read_pid(state)
    executable = binary_path()
    if recorded and pid_alive(recorded) and port_open(ui_port) and interface_belongs(recorded, executable):
        print(f"桌面界面已在运行：{url}")
        return
    occupant = listening_pid(ui_port)
    if occupant and interface_belongs(occupant, executable):
        write_pid(state, occupant)
        print(f"桌面界面已在运行：{url}")
        return
    if occupant:
        fail(f"桌面端口 {ui_port} 已被其他程序占用。")
    print("正在启动桌面界面")
    pid = spawn([str(executable), "ui", "--port", str(ui_port)], logs / "launcher-desktop.log")
    write_pid(state, pid)
    if not port_open(ui_port):
        wait_until(lambda: port_open(ui_port), 60, f"桌面界面没有在预期时间内就绪。日志：{logs / 'launcher-desktop.log'}")
    print(f"桌面界面已启动：{url}")


def run_launch(ui_port: int | None = None) -> None:
    settings = load_settings()
    settings.ensure_dirs()
    port = UI_PORT if ui_port is None else ui_port
    if ui_port is None:
        port = int(os.environ.get("AGENTSHELF_UI_PORT", str(UI_PORT)))
    logs = settings.logs_dir
    session = start_backend(logs)
    start_interface(settings.data_dir, logs, port)
    desktop = f"http://{UI_HOST}:{port}"
    payload = {
        "backend": f"http://{UI_HOST}:{int(session['port'])}",
        "desktop": desktop,
        "data_dir": str(settings.data_dir),
        "bin": str(binary_path()),
    }
    print("AGENTSHELF_LAUNCHED " + json.dumps(payload, ensure_ascii=False), flush=True)
    if os.environ.get("AGENTSHELF_OPEN_BROWSER", "1") == "0":
        return
    try:
        webbrowser.open(desktop)
    except Exception:
        return
