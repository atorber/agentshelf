"""发布二进制的入口。无参数时启动本机服务和界面，其余参数交给命令行。"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] == "launch":
        from agentshelf.launcher_bin import parse_ui_port, run_launch

        run_launch(parse_ui_port(args[1:] if args[:1] == ["launch"] else []))
        return
    if args[0] == "ui":
        from agentshelf.launcher_bin import parse_ui_port
        from agentshelf.ui_server import serve_ui

        serve_ui(parse_ui_port(args[1:]))
        return
    sys.argv = [sys.argv[0], *args]
    from agentshelf.cli import app

    app()


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
