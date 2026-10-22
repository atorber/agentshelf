---
name: agentshelf-archive
description: 把当前任务的最终产物归档到本地 AgentShelf。用户明确要求归档、保存最终稿、收入产物库时使用。调用前先部署并启动本机后端和桌面界面。不要归档思考过程、日志或中间文件。
---

# AgentShelf 归档

只归档用户确认过的最终成果。先用仓库里的启动器完成部署，再通过它输出的 `agentshelf` 命令调用本地服务。不要直接修改数据库或存储目录，也不要按文件名猜测并覆盖已有产物。

## 部署

归档前必须先部署。没有看到以 `AGENTSHELF_LAUNCHED` 开头的成功输出时，不要执行归档。

按这个顺序选择唯一的部署目录，不要同时部署多份：

1. 当前工作区包含 `scripts/launch.py`，且 `pyproject.toml` 里的项目名是 `agentshelf` 时，使用当前工作区。
2. 否则使用已有目录：macOS 和 Linux 为 `~/.agentshelf/app`，Windows 为 `%USERPROFILE%\.agentshelf\app`。目录里需要已有 `scripts/launch.py`。
3. 两处都没有时再克隆：

```bash
git clone --depth 1 https://github.com/atorber/agentshelf.git ~/.agentshelf/app
```

Windows 把目标路径换成 `%USERPROFILE%\.agentshelf\app`。

在部署目录执行：

```bash
python3 scripts/launch.py
```

Windows 上没有 `python3` 时改用 `py -3 scripts/launch.py`。

启动器会安装依赖，并在后台启动后端和桌面界面。已经在运行时直接复用。成功时最后一行类似：

```text
AGENTSHELF_LAUNCHED {"backend":"http://127.0.0.1:8765","desktop":"http://127.0.0.1:1420","data_dir":"...","bin":"..."}
```

记下其中的 `bin`。随后的归档命令都使用这个路径，不要改用系统里同名的其他命令。启动器退出码不为 0，或输出里没有 `AGENTSHELF_LAUNCHED` 时，向用户报告错误并停止，不要声称已经归档。

## 归档

1. 确认哪些文件是最终产物。过程稿、执行日志、思考记录和中间文件不归档。拿不准时先问用户。
2. 敏感文件必须得到用户明确确认后才能归档。
3. 对每个文件执行，把 `<bin>` 换成启动器输出的路径：

```bash
"<bin>" archive "<文件路径>" --title "<名称>" --project "<项目>" --tags "<标签1,标签2>" --source "<agent 名称>"
```

4. 退出码为 0：按命令输出报告产物名称、编号和版本。
5. 退出码为 2：相同内容已经存在。把候选产物原样告诉用户，请用户选择：
   - 创建新产物：同一条命令加上 `--new-artifact`
   - 追加到已有产物：加上 `--artifact-id "<产物编号>"`
6. 退出码为其他值：报告命令输出的错误，不要声称已经归档。

多个文件逐个归档。一个文件失败时，继续处理其余文件，并分别报告结果。同一次任务只部署一次。

## 禁止

- 不在部署成功前登记产物。
- 不根据文件名覆盖已有产物。
- 不把 CLI 或 API 绕开，直接写入数据目录。
- 不采集 Agent 的思考过程、执行日志和中间产物。
