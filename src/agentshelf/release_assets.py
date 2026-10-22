"""发布到 GitHub Release 的启动器文件名。"""

from __future__ import annotations

from pathlib import Path

RELEASE_DOWNLOAD = "https://github.com/atorber/agentshelf/releases/latest/download"
INSTALL_DIR = Path(".agentshelf") / "bin"


def launcher_stem(system: str, machine: str) -> str:
    """返回不含扩展名的启动器文件名。未知系统直接失败，避免下到错误架构。"""
    normalized = system.strip().lower()
    arch = machine.strip().lower()
    if normalized == "darwin" and arch in {"arm64", "aarch64"}:
        return "agentshelf-launcher-darwin-arm64"
    if normalized == "darwin" and arch in {"x86_64", "amd64"}:
        return "agentshelf-launcher-darwin-x64"
    if normalized == "linux" and arch in {"x86_64", "amd64"}:
        return "agentshelf-launcher-linux-x64"
    if normalized == "linux" and arch in {"aarch64", "arm64"}:
        return "agentshelf-launcher-linux-arm64"
    if normalized == "windows" and arch in {"x86_64", "amd64", "x64"}:
        return "agentshelf-launcher-windows-x64"
    raise ValueError(f"没有适用于 {system} {machine} 的启动器")


def launcher_filename(system: str, machine: str) -> str:
    stem = launcher_stem(system, machine)
    if system.strip().lower() == "windows":
        return stem + ".exe"
    return stem


def checksum_filename(system: str, machine: str) -> str:
    return launcher_filename(system, machine) + ".sha256"


def release_asset_url(filename: str) -> str:
    return f"{RELEASE_DOWNLOAD}/{filename}"


def install_path(home: Path, system: str) -> Path:
    name = "agentshelf-launcher.exe" if system.strip().lower() == "windows" else "agentshelf-launcher"
    return home / INSTALL_DIR / name
