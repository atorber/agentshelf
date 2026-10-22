#!/usr/bin/env python3
"""准备依赖，并在后台启动本地后端和桌面界面。重复执行会复用已经在跑的进程。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "apps" / "desktop"
UI_HOST = "127.0.0.1"
UI_PORT = 1420


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def venv_python() -> Path:
    folder = "Scripts" if os.name == "nt" else "bin"
    name = "python.exe" if os.name == "nt" else "python"
    return ROOT / ".venv" / folder / name


def venv_agentshelf(python: Path) -> Path:
    name = "agentshelf.exe" if os.name == "nt" else "agentshelf"
    return python.parent / name


def npm_bin() -> str:
    found = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    if not found:
        fail("未找到 npm。安装 Node.js 后重新运行启动器。")
    return found


def run(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd)
    if completed.returncode != 0:
        fail(f"命令失败（退出码 {completed.returncode}）：{' '.join(command)}")


def ensure_venv() -> Path:
    python = venv_python()
    if not python.exists():
        print("正在创建虚拟环境")
        run([sys.executable, "-m", "venv", str(ROOT / ".venv")], ROOT)
    if not python.exists():
        fail("虚拟环境已创建，但找不到 Python 解释器。")
    return python


def stamp_matches(stamp: Path, signature: str) -> bool:
    try:
        return stamp.read_text(encoding="utf-8").strip() == signature
    except OSError:
        return False


def ensure_package(python: Path) -> None:
    pyproject = ROOT / "pyproject.toml"
    signature = str(pyproject.stat().st_mtime_ns)
    stamp = ROOT / ".venv" / ".agentshelf-stamp"
    imported = subprocess.run([str(python), "-c", "import agentshelf.cli"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if imported.returncode == 0 and stamp_matches(stamp, signature):
        return
    print("正在安装后端")
    run([str(python), "-m", "pip", "install", "-e", str(ROOT)], ROOT)
    stamp.write_text(signature, encoding="utf-8")


def ensure_frontend(npm: str) -> None:
    lock = DESKTOP / "package-lock.json"
    signature = str(lock.stat().st_mtime_ns) if lock.exists() else "none"
    stamp = DESKTOP / "node_modules" / ".agentshelf-stamp"
    if (DESKTOP / "node_modules").is_dir() and stamp_matches(stamp, signature):
        return
    print("正在安装桌面依赖")
    run([npm, "install"], DESKTOP)
    signature = str(lock.stat().st_mtime_ns) if lock.exists() else "none"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(signature, encoding="utf-8")


def python_out(python: Path, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(python), "-c", code], cwd=ROOT, capture_output=True, text=True, env=os.environ.copy())


def data_dir(python: Path) -> Path:
    completed = python_out(python, "from agentshelf.config import load_settings; print(load_settings().data_dir)")
    if completed.returncode != 0 or not completed.stdout.strip():
        fail(completed.stderr.strip() or "无法确定数据目录")
    path = Path(completed.stdout.strip())
    (path / "logs").mkdir(parents=True, exist_ok=True)
    return path


def backend_session(python: Path) -> dict | None:
    code = (
        "import json\n"
        "from agentshelf.config import load_settings\n"
        "from agentshelf.server import running_session\n"
        "session = running_session(load_settings())\n"
        "print(json.dumps(session) if session else '')\n"
    )
    completed = python_out(python, code)
    if completed.returncode != 0:
        fail(completed.stderr.strip() or "无法检查后端状态")
    text = completed.stdout.strip()
    if not text:
        return None
    return json.loads(text)


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
    if os.name == "nt":
        completed = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/value"],
            capture_output=True,
            text=True,
        )
        return completed.stdout
    completed = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    return completed.stdout


def process_data_dir(pid: int) -> str:
    if os.name == "nt":
        return ""
    completed = subprocess.run(["ps", "eww", "-p", str(pid)], capture_output=True, text=True)
    for token in completed.stdout.split():
        if token.startswith("AGENTSHELF_DATA_DIR="):
            return token.split("=", 1)[1]
    return ""


def default_data_dir(python: Path) -> Path:
    env = os.environ.copy()
    env.pop("AGENTSHELF_DATA_DIR", None)
    completed = subprocess.run(
        [str(python), "-c", "from agentshelf.config import default_data_dir; print(default_data_dir())"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        fail(completed.stderr.strip() or "无法确定默认数据目录")
    return Path(completed.stdout.strip())


def desktop_belongs_here(pid: int, directory: Path, python: Path) -> bool:
    command = process_command(pid)
    normalized = command.replace("\\", "/")
    if "vite" not in normalized or "apps/desktop" not in normalized:
        return False
    recorded = process_data_dir(pid)
    expected = Path(recorded).expanduser() if recorded else default_data_dir(python)
    return expected.resolve() == directory.resolve()


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


def spawn(command: list[str], cwd: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "ab", buffering=0)
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
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


def start_backend(python: Path, logs: Path) -> dict:
    existing = backend_session(python)
    if existing:
        print(f"后端已在运行：http://{UI_HOST}:{int(existing['port'])}")
        return existing
    binary = venv_agentshelf(python)
    if not binary.exists():
        fail("后端已安装，但找不到 agentshelf 命令。")
    print("正在启动后端")
    spawn([str(binary), "serve"], ROOT, logs / "launcher-backend.log")
    found: dict | None = None

    def ready() -> bool:
        nonlocal found
        found = backend_session(python)
        return found is not None

    wait_until(ready, 40, f"后端没有在预期时间内就绪。日志：{logs / 'launcher-backend.log'}")
    assert found is not None
    print(f"后端已启动：http://{UI_HOST}:{int(found['port'])}")
    return found


def start_desktop(python: Path, npm: str, directory: Path, logs: Path, mode: str, ui_port: int) -> None:
    state = directory / "desktop.json"
    url = f"http://{UI_HOST}:{ui_port}"
    recorded = read_pid(state)
    if recorded and pid_alive(recorded) and (port_open(ui_port) or mode == "tauri"):
        print(f"桌面界面已在运行：{url}")
        return
    occupant = listening_pid(ui_port)
    if occupant and desktop_belongs_here(occupant, directory, python):
        write_pid(state, occupant)
        print(f"桌面界面已在运行：{url}")
        return
    if occupant:
        fail(f"桌面端口 {ui_port} 已被其他程序占用。")
    if mode == "tauri":
        command = [npm, "run", "tauri", "dev"]
        timeout = 180
        print("正在启动桌面窗口")
    else:
        vite = DESKTOP / "node_modules" / ".bin" / ("vite.cmd" if os.name == "nt" else "vite")
        if not vite.exists():
            fail("桌面依赖已安装，但找不到 vite。")
        command = [str(vite), "--host", UI_HOST, "--port", str(ui_port), "--strictPort"]
        timeout = 40
        print("正在启动桌面界面")
    pid = spawn(command, DESKTOP, logs / "launcher-desktop.log")
    write_pid(state, pid)
    if not port_open(ui_port):
        wait_until(lambda: port_open(ui_port), timeout, f"桌面界面没有在预期时间内就绪。日志：{logs / 'launcher-desktop.log'}")
    print(f"桌面界面已启动：{url}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(description="部署并启动 AgentShelf 后端和桌面界面")
    parser.add_argument("--desktop", choices=("vite", "tauri"), default="vite", help="vite 打开本地界面，tauri 打开桌面窗口")
    parser.add_argument("--ui-port", type=int, default=int(os.environ.get("AGENTSHELF_UI_PORT", str(UI_PORT))))
    args = parser.parse_args()
    os.chdir(ROOT)
    python = ensure_venv()
    ensure_package(python)
    npm = npm_bin()
    ensure_frontend(npm)
    directory = data_dir(python)
    session = start_backend(python, directory / "logs")
    start_desktop(python, npm, directory, directory / "logs", args.desktop, args.ui_port)
    payload = {
        "backend": f"http://{UI_HOST}:{int(session['port'])}",
        "desktop": f"http://{UI_HOST}:{args.ui_port}",
        "data_dir": str(directory),
        "bin": str(venv_agentshelf(python)),
    }
    print("AGENTSHELF_LAUNCHED " + json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
