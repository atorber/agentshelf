# 命令行与 Skill

命令行和 Skill 是各 Agent 接入本机产物库的方式。它们访问已经启动的本地服务，不自己保存版本，也不直接改数据库。服务没启动时，先按 [快速开始](quickstart.md) 打开界面，或执行 `agentshelf serve`。

只归档最终成果。过程稿、执行日志、思考记录和中间文件不提交。拿不准时先问你。Claude Code、Cursor、Codex 以及其他支持 Skill 的 Agent 使用同一份 `agentshelf-archive`。

命令通过本机令牌访问 `127.0.0.1`。令牌写在数据目录的 `token` 文件里，只有当前用户可以读。不要把令牌抄到仓库或发给别人。

## 常用命令

查看服务、存储和语义检索状态：

```bash
agentshelf status
```

归档一个文件：

```bash
agentshelf archive ./最终稿.md \
  --title "周报" \
  --description "本周进展" \
  --project "工作" \
  --tags "报告,周报" \
  --source "cursor"
```

| 参数 | 作用 |
|---|---|
| `--title` | 产物名称。留空时使用去掉扩展名的文件名 |
| `--description` | 描述 |
| `--project` | 项目名称。还没有这个项目时会建立 |
| `--tags` | 标签，逗号分隔 |
| `--source` | 来源 Agent 的名称 |
| `--new-artifact` | 内容已存在时，仍创建新产物 |
| `--artifact-id` | 把这次内容追加为该产物的新版本 |
| `--json` | 以 JSON 输出结果 |

`--new-artifact` 和 `--artifact-id` 不能同时使用。

检索：

```bash
agentshelf search "周报"
agentshelf search "周报" --project "工作" --tag "报告" --source "cursor" --kind markdown --mode keyword
```

`--mode` 可以是 `keyword`、`semantic` 或 `hybrid`。`--kind` 可以是 `markdown`、`text`、`csv`、`json`、`image`、`pdf` 或 `unsupported`。

备份与恢复：

```bash
agentshelf backup
agentshelf restore ./备份.zip --yes
```

没有 `--yes` 时，`restore` 不会改动当前产物库。恢复会替换当前数据库和对象文件。

停止由命令行或启动器拉起、并且仍在运行的本地服务：

```bash
agentshelf stop
```

## 内容重复时怎么处理

`archive` 发现相同内容已经归档时，退出码是 2，并打印候选产物和暂存编号。此时文件还没有登记成新版本。

创建另一份产物：

```bash
agentshelf archive ./最终稿.md --title "周报" --new-artifact
```

追加到已有产物：

```bash
agentshelf archive ./最终稿.md --title "周报" --artifact-id "<产物编号>"
```

也可以用暂存编号确认，避免再次上传文件：

```bash
agentshelf confirm "<暂存编号>" --decision new_artifact --title "周报"
agentshelf confirm "<暂存编号>" --decision new_version --artifact-id "<产物编号>"
```

`--decision` 只能是 `new_artifact` 或 `new_version`。选择 `new_version` 时要带上产物编号。

其他失败的退出码是 1。看命令打印的错误，不要把失败当成已经归档。

## 安装并使用 Skill

Skill 位于仓库的 `skill/agentshelf-archive`。安装到当前 Agent 的用户级 skills 目录后，所有项目都可以用。

可以让 Agent 自己安装：

```text
请从 https://github.com/atorber/agentshelf 安装 Skill agentshelf-archive（目录 skill/agentshelf-archive）。安装到我当前使用的 Agent 的用户级 skills 目录，使所有项目可用。安装完成后告诉我安装位置。
```

使用范围：你明确要求归档、保存最终稿或收入产物库时。Skill 会先部署并启动本机后端和桌面界面，再归档。

部署目录按这个顺序只选一处：

1. 当前工作区已经是 AgentShelf 仓库时，用当前工作区。
2. 否则使用已有目录：macOS 和 Linux 为 `~/.agentshelf/app`，Windows 为 `%USERPROFILE%\.agentshelf\app`。
3. 两处都没有时，再克隆仓库到上述目录。

启动命令：

```bash
python3 scripts/launch.py
```

Windows 上没有 `python3` 时使用 `py -3 scripts/launch.py`。需要桌面窗口而不是浏览器界面时，加上 `--desktop tauri`，这要求本机已安装 Rust。

成功时，最后一行以 `AGENTSHELF_LAUNCHED` 开头，并带上本机地址、数据目录和 `agentshelf` 命令路径。之后的归档使用这条输出里的命令路径。没有这行成功输出时，不要继续归档。

对每个最终文件执行：

```bash
"<bin>" archive "<文件路径>" --title "<名称>" --project "<项目>" --tags "<标签1,标签2>" --source "<agent 名称>"
```

多个文件逐个归档。一个文件失败时，继续处理其余文件，并分别报告结果。同一次任务只部署一次。

敏感文件要先得到你的明确确认。过程稿、执行日志、思考记录和中间文件不归档。
