---
name: agentshelf-archive
description: 把当前任务的最终产物归档到本地 AgentShelf。用户说「把这份最终稿归档到 AgentShelf」或要求保存最终稿、收入产物库时使用。自行确定文件，并填写名称、项目、标签、来源和描述，不要向用户索要这些字段。调用前先准备启动器：本机没有时从 GitHub Release 下载对应系统的二进制，不要克隆仓库。不要归档思考过程、日志或中间文件。
---

# AgentShelf 归档

用户要求归档时，只归档当前任务的最终成果。先完成下面的部署，再使用启动器输出的 `bin` 调用本地服务。不要直接修改数据库或存储目录，也不要按文件名猜测并覆盖已有产物。

## 部署

安装本 Skill 时，以及每次归档之前，都要先部署。没有看到以 `AGENTSHELF_LAUNCHED` 开头的成功输出时，不要执行归档，也不要声称已经打开。

按这个顺序选择唯一的启动器，不要同时部署多份：

1. 当前工作区包含 `scripts/launch.py`，且 `pyproject.toml` 里的项目名是 `agentshelf` 时，使用这份源码里的启动器。
2. 否则，如果已有源码目录里存在 `scripts/launch.py`，使用该目录。macOS 和 Linux 为 `~/.agentshelf/app`，Windows 为 `%USERPROFILE%\.agentshelf\app`。
3. 否则，如果已经下载过发布的启动器，直接运行它。macOS 和 Linux 为 `~/.agentshelf/bin/agentshelf-launcher`，Windows 为 `%USERPROFILE%\.agentshelf\bin\agentshelf-launcher.exe`。
4. 以上都没有时，从最新的 GitHub Release 下载与本机系统对应的二进制，保存为第 3 步的路径后再运行。不要克隆仓库来代替下载。

已有二进制无法执行时，删掉该文件后重新下载一次。下载失败时报告地址和错误，不要改用克隆，也不要声称已经打开。

### 源码启动器

在对应目录执行：

```bash
python3 scripts/launch.py
```

Windows 上没有 `python3` 时改用 `py -3 scripts/launch.py`。

### 下载发布的启动器

只在本机没有启动器时下载。用 `uname -sm` 判断 macOS 和 Linux 的架构。Windows 看 `PROCESSOR_ARCHITECTURE`：`AMD64` 用下表的 Windows 文件；`ARM64` 没有对应文件，说明不支持并停止。

| 系统 | 架构 | Release 中的文件名 |
|---|---|---|
| macOS | arm64 | `agentshelf-launcher-darwin-arm64` |
| macOS | x86_64 | `agentshelf-launcher-darwin-x64` |
| Linux | x86_64 | `agentshelf-launcher-linux-x64` |
| Linux | aarch64 | `agentshelf-launcher-linux-arm64` |
| Windows | x64 | `agentshelf-launcher-windows-x64.exe` |

文件地址是 `https://github.com/atorber/agentshelf/releases/latest/download/<文件名>`。校验文件是同一地址加上 `.sha256`，内容是一行 SHA-256 十六进制摘要。

macOS 和 Linux：

1. 创建 `~/.agentshelf/bin`。
2. 把二进制和对应的 `.sha256` 下载到临时文件。
3. 计算二进制的 SHA-256，与校验文件中的摘要比较。不一致就删除临时文件并停止。macOS 用 `shasum -a 256`，Linux 用 `sha256sum`。
4. 把二进制移动到 `~/.agentshelf/bin/agentshelf-launcher`，并执行 `chmod 755`。
5. 在 macOS 上再执行 `xattr -d com.apple.quarantine ~/.agentshelf/bin/agentshelf-launcher`。属性不存在时忽略这个命令的失败。
6. 运行 `~/.agentshelf/bin/agentshelf-launcher`。不要加参数，也不要用 Python 启动它。

Windows：

1. 创建 `%USERPROFILE%\.agentshelf\bin`。
2. 用 `curl.exe -fL` 下载 exe 和对应的 `.sha256`。
3. 用 `Get-FileHash -Algorithm SHA256` 比对摘要。不一致就删除并停止。
4. 保存为 `%USERPROFILE%\.agentshelf\bin\agentshelf-launcher.exe`。
5. 运行这个 exe。不要加参数。

发布的启动器是单个可执行文件，包含后端和本机界面。运行它不需要安装 Python 或 Node。

### 成功输出

启动器会在后台启动后端和本机界面，然后退出；已经在运行时直接复用，并尝试打开界面。成功时最后一行类似：

```text
AGENTSHELF_LAUNCHED {"backend":"http://127.0.0.1:8765","desktop":"http://127.0.0.1:1420","data_dir":"...","bin":"..."}
```

界面没有自动打开时，打开输出里的 `desktop` 地址。记下其中的 `bin`。随后的归档命令都使用这个路径，不要改用系统里同名的其他命令。启动器退出码不为 0，或输出里没有 `AGENTSHELF_LAUNCHED` 时，向用户报告错误并停止，不要声称已经归档。

## 归档

用户说「把这份最终稿归档到 AgentShelf。」或同等意思时，直接归档。不要向用户索要路径、名称、项目、标签、来源或描述。用户已经说过的字段以用户的为准，其余自行填写。

### 选定文件

- 「这份最终稿」是当前任务里准备留下的那一份成果。任务里只有一份最终文件时，直接用它。
- 用户点了路径或文件名时，用用户点名的文件。
- 最终稿还只在对话里、没有文件时，先按推断出的名称写成当前项目中的一个文件，再归档，并在结果里说明写到了哪里。
- 有多份都像最终稿、无法判断是哪一份时，只列出候选并询问归档哪几份。过程稿、执行日志、思考记录和中间文件不列入候选。
- 同一份最终成果包含多个文件时，放进同一份产物，用一条归档命令一次传入这些路径。不要拆成多份产物。
- 用户明确要留下多份彼此独立的成果时，才分别归档。

### 自动填写

归档前填好，不要先征求确认。判断不了的项目、标签或描述直接省略，不要编造，也不要为此提问。

| 字段 | 怎么得到 |
|---|---|
| 名称 | 文档标题，例如 Markdown 一级标题。没有标题时用去掉扩展名的文件名。不要把「最终稿」当作名称 |
| 项目 | 当前工作区或仓库的项目名 |
| 标签 | 根据内容取 1 到 3 个短标签，逗号分隔 |
| 来源 | 当前 Agent 的名称，例如 Cursor、Claude Code、Codex |
| 描述 | 一句话说明这份成果是什么 |

追加为已有产物的新版本时，沿用该产物已有的名称、项目、标签和描述，除非用户明确要求修改。来源仍填写当前 Agent。

敏感文件（密钥、令牌、私钥等）必须得到用户明确同意后才能归档。

### 执行

把 `<bin>` 换成启动器输出的路径。同一份成果的文件放在同一条命令里。只附上有值的选项：

```bash
"<bin>" archive "<文件路径>" --title "<名称>" --project "<项目>" --tags "<标签1,标签2>" --source "<当前 Agent>" --description "<一句话说明>"
"<bin>" archive "<文件1>" "<文件2>" --title "<名称>" --project "<项目>" --tags "<标签1,标签2>" --source "<当前 Agent>"
```

1. 退出码为 0：报告产物名称、编号和版本，以及实际写入的项目、标签和来源。
2. 退出码为 2：相同内容已经存在。把候选产物原样告诉用户，请用户选择：
   - 创建新产物：同一条命令加上 `--new-artifact`
   - 追加到已有产物：加上 `--artifact-id "<产物编号>"`，并沿用该产物已有的名称、项目、标签和描述
3. 退出码为其他值：报告命令输出的错误，不要声称已经归档。

同一份成果的多个文件用一条命令归档。命令失败时不要改成逐个文件各建一份产物。彼此独立的成果才分开归档，并分别报告结果。同一次任务只部署一次。

## 禁止

- 不在部署成功前登记产物。
- 不根据文件名覆盖已有产物。
- 不为了补齐名称、项目、标签或来源打断用户。
- 不把 CLI 或 API 绕开，直接写入数据目录。
- 不采集 Agent 的思考过程、执行日志和中间产物。
