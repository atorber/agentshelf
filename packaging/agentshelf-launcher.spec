# -*- mode: python ; coding: utf-8 -*-
"""把启动器打成单个可执行文件，并带上已构建的桌面界面。"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).resolve().parent
desktop = root / "apps" / "desktop" / "dist"
if not (desktop / "index.html").is_file():
    raise SystemExit(f"缺少前端构建：{desktop}")

name = os.environ.get("AGENTSHELF_LAUNCHER_NAME", "").strip()
if not name:
    raise SystemExit("缺少环境变量 AGENTSHELF_LAUNCHER_NAME")

hidden = collect_submodules("uvicorn")
hidden += [
    "agentshelf.cli",
    "agentshelf.launcher_bin",
    "agentshelf.ui_server",
    "agentshelf.server",
    "agentshelf.app",
    "agentshelf.library",
    "agentshelf.extract",
    "pypdf",
    "multipart",
]

analysis = Analysis(
    [str(root / "src" / "agentshelf" / "standalone.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(desktop), "desktop")],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["sentence_transformers", "torch", "transformers", "numpy"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
