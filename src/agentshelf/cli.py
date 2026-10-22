from __future__ import annotations

import json
from pathlib import Path

import httpx
import typer

from agentshelf.config import load_settings
from agentshelf.server import running_session, serve, session_endpoint, stop_running

app = typer.Typer(help="AgentShelf 本地产物库", no_args_is_help=True)
runner_client_timeout = 120.0


def _client() -> httpx.Client:
    port, token, _data_dir = session_endpoint()
    return httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=runner_client_timeout,
    )


def _print_result(response: httpx.Response, as_json: bool) -> None:
    try:
        body = response.json()
    except json.JSONDecodeError:
        typer.echo(response.text or "服务返回了无法解析的响应")
        raise typer.Exit(1)
    if as_json:
        typer.echo(json.dumps(body, ensure_ascii=False, indent=2))
    else:
        _print_human(body, response.status_code)
    if response.status_code == 409 and body.get("status") == "needs_decision":
        raise typer.Exit(code=2)
    if response.status_code >= 400:
        raise typer.Exit(code=1)


def _print_human(body: dict, status_code: int) -> None:
    if body.get("status") == "needs_decision":
        typer.echo(body.get("message") or "需要确认如何归档")
        typer.echo(f"暂存编号: {body.get('staging_id')}")
        for item in body.get("candidates") or []:
            versions = ",".join(str(number) for number in item.get("versions") or [])
            typer.echo(f"- {item.get('title')}  产物 {item.get('artifact_id')}  版本 {versions}")
        typer.echo("请追加 --new-artifact 创建新产物，或使用 --artifact-id 追加版本。")
        return
    if status_code >= 400:
        typer.echo(body.get("detail") or body.get("message") or "请求失败")
        return
    if body.get("title") and body.get("id"):
        version = (body.get("current_version") or {}).get("version_number")
        typer.echo(body.get("message") or "完成")
        typer.echo(f"产物: {body.get('title')}")
        typer.echo(f"编号: {body.get('id')}")
        if version:
            typer.echo(f"当前版本: v{version}")
        sha = (body.get("current_version") or {}).get("sha256")
        if sha:
            typer.echo(f"SHA-256: {sha}")
        if "stored_new_blob" in body:
            typer.echo("物理文件: 新保存" if body["stored_new_blob"] else "物理文件: 复用已有内容")
        return
    typer.echo(json.dumps(body, ensure_ascii=False, indent=2))


@app.command("serve")
def serve_cmd(
    port: int = typer.Option(0, help="监听端口，0 表示从默认端口起自动选择"),
) -> None:
    """启动本地服务。桌面应用也会调用此命令。"""
    serve(None if port == 0 else port)


@app.command("stop")
def stop_cmd() -> None:
    """请求本地服务优雅退出。"""
    if stop_running():
        typer.echo("已请求停止本地服务")
        return
    typer.echo("没有正在运行的本地服务")


@app.command()
def status() -> None:
    """查看本地服务、存储和语义检索状态。"""
    settings = load_settings()
    session = running_session(settings)
    if not session:
        typer.echo("本地服务未启动")
        typer.echo(f"数据目录: {settings.data_dir}")
        raise typer.Exit(code=1)
    with _client() as client:
        response = client.get("/api/status")
    _print_result(response, as_json=True)


@app.command()
def archive(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    title: str = typer.Option("", help="产物名称"),
    description: str = typer.Option("", help="描述"),
    project: str = typer.Option("", help="项目"),
    tags: str = typer.Option("", help="标签，逗号分隔"),
    source: str = typer.Option("", help="来源 Agent"),
    artifact_id: str = typer.Option("", help="追加为该产物的新版本"),
    new_artifact: bool = typer.Option(False, "--new-artifact", help="即使内容已存在，也创建新产物"),
    as_json: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """通过本地服务归档一个最终产物。"""
    decision = ""
    if new_artifact and artifact_id:
        typer.echo("不能同时指定 --new-artifact 和 --artifact-id")
        raise typer.Exit(code=1)
    if new_artifact:
        decision = "new_artifact"
    elif artifact_id:
        decision = "new_version"
    with file.open("rb") as handle:
        with _client() as client:
            response = client.post(
                "/api/ingest",
                data={
                    "title": title,
                    "description": description,
                    "project": project,
                    "tags": tags,
                    "source_agent": source,
                    "decision": decision,
                    "artifact_id": artifact_id,
                },
                files={"file": (file.name, handle, "application/octet-stream")},
            )
    _print_result(response, as_json)


@app.command()
def confirm(
    staging_id: str = typer.Argument(...),
    decision: str = typer.Option(..., help="new_artifact 或 new_version"),
    artifact_id: str = typer.Option(""),
    title: str = typer.Option(""),
    description: str = typer.Option(""),
    project: str = typer.Option(""),
    tags: str = typer.Option(""),
    source: str = typer.Option(""),
    filename: str = typer.Option(""),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """确认暂存内容的归档方式。"""
    with _client() as client:
        response = client.post(
            "/api/ingest/confirm",
            json={
                "staging_id": staging_id,
                "decision": decision,
                "artifact_id": artifact_id or None,
                "title": title,
                "description": description,
                "project": project,
                "tags": tags,
                "source_agent": source,
                "filename": filename,
            },
        )
    _print_result(response, as_json)


@app.command()
def search(
    query: str = typer.Argument(...),
    project: str = typer.Option(""),
    tag: str = typer.Option(""),
    source: str = typer.Option(""),
    kind: str = typer.Option(""),
    mode: str = typer.Option("keyword", help="keyword、semantic 或 hybrid"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """检索已归档产物。"""
    with _client() as client:
        response = client.get(
            "/api/search",
            params={"q": query, "project": project, "tag": tag, "source": source, "kind": kind, "mode": mode},
        )
    if as_json or response.status_code >= 400:
        _print_result(response, as_json=True)
        return
    body = response.json()
    items = body.get("items") or []
    if not items:
        typer.echo("没有匹配的产物")
        return
    for item in items:
        location = "当前版本" if item.get("is_current") else f"v{item.get('version_number')}"
        typer.echo(f"{item.get('title')}  [{location}]  {item.get('artifact_id')}")
        if item.get("snippet"):
            typer.echo(f"  {item['snippet']}")


@app.command()
def backup() -> None:
    """创建一份本地备份。"""
    with _client() as client:
        response = client.post("/api/backups")
    _print_result(response, as_json=True)


@app.command()
def restore(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    yes: bool = typer.Option(False, "--yes", help="确认用备份替换当前产物库"),
) -> None:
    """从备份包恢复。会替换当前数据库和文件。"""
    if not yes:
        typer.echo("恢复会替换当前产物库。确认后请追加 --yes。")
        raise typer.Exit(code=1)
    with file.open("rb") as handle:
        with _client() as client:
            response = client.post("/api/backups/upload-restore", files={"file": (file.name, handle, "application/zip")})
    _print_result(response, as_json=True)
