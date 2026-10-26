# AgentShelf

AgentShelf 是面向多个 AI Agent 的本地知识库。Claude Code、Cursor、Codex 以及其他支持 Skill 的 Agent，通过同一个归档 Skill 把最终成果交到本机，在这里检索、预览、保留版本和备份。正常使用不需要互联网，也不会把文件、检索词或使用记录发到外部服务。思考过程、执行日志和中间文件不进入知识库。

产品介绍、快速开始和使用说明：<https://atorber.github.io/agentshelf/>（源文件在 [website](website/docs/index.mdx)）。

## 技术方案

桌面窗口使用 Tauri 2 承载 React 界面，并由它启动、监督和关闭本地 Python 服务。业务只走这一套 FastAPI：手动上传、CLI 和 Skill 共用归档、哈希、去重、版本和索引规则，不直接写数据库。

```text
上传 / CLI / Skill
        |
        v
FastAPI（只监听 127.0.0.1，请求带本机令牌）
        |
   +----+----+
   |         |
SQLite    内容寻址文件
FTS5      objects/<sha256>
```

- 每条知识有独立编号。文件名不会用来覆盖已有知识。
- 文件按 SHA-256 保存。相同内容只保留一份物理文件。
- 相同内容再次归档时，必须明确选择“新建一条知识”或“追加到指定的那一条”。
- 全文检索使用 SQLite FTS5。语义检索是可选项，模型由用户自行导入，未启用时其余功能完整可用。
- 索引任务放在 SQLite 队列里。异常退出后，未完成任务会在下次启动时继续。
- 数据目录使用操作系统标准位置。macOS 为 `~/Library/Application Support/AgentShelf`。

## 运行

在仓库根目录：

```bash
chmod +x scripts/dev.sh
./scripts/dev.sh
```

脚本会准备虚拟环境、启动本地服务，并打开界面：<http://127.0.0.1:1420>。关闭这个终端时，由它启动的服务会一起停止。

Skill 归档前比较本 Skill 版本和 `/api/health` 的 `version`。版本一致且服务已启动时直接使用，不再下载或重新启动。本 Skill 版本更高时，从标签 `v<版本>` 的 Release 下载启动器，停掉旧服务后再启动。版本一致但服务没在运行时，才检查本机二进制；没有就下载该版本。下载失败时再用 `~/.agentshelf/app` 里的 `scripts/launch.py`，最后才用当前仓库的 `scripts/launch.py`。启动器拉起后端和桌面界面后退出，服务继续在后台运行。

```bash
python3 scripts/launch.py
```

成功时输出以 `AGENTSHELF_LAUNCHED` 开头，并带上本机 `agentshelf` 命令的路径。需要桌面窗口而不是浏览器界面时，执行 `python3 scripts/launch.py --desktop tauri`。这需要本机已安装 Rust。

发布 GitHub Release 时，工作流会把启动器编译成各系统的单个可执行文件，连同 SHA-256 校验文件上传到该 Release。标签形如 `v0.3.2`。本机没有对应版本的 `~/.agentshelf/bin/agentshelf-launcher`（Windows 为 `%USERPROFILE%\.agentshelf\bin\agentshelf-launcher.exe`），或正在运行的服务比 Skill 旧时，Skill 从该标签下载对应系统的文件，并在升级时重启服务。这个文件包含后端和本机界面，运行时不需要另外安装 Python 或 Node。下载失败时，再用 `~/.agentshelf/app` 里的 `scripts/launch.py`，最后才用当前仓库。版本升级的下载失败则停住，不改用旧二进制。

只启动服务：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
agentshelf serve
```

桌面壳（会自行拉起后端，关闭窗口时停止由它启动的服务）：

```bash
cd apps/desktop
npm install
npm run tauri dev
```

安装包配置了 macOS dmg 和 Windows nsis。请在对应系统上执行 `npm run tauri build`。当前仓库不附带已经编好的安装包。

## 归档

界面支持点击选择、拖拽和多文件上传。一次放入的多个文件归为同一条知识。上传前可以填写名称、描述、项目和标签。

命令行：

```bash
agentshelf archive ./最终稿.md --title "周报" --project "工作" --tags "报告" --source "cursor"
agentshelf archive ./设计.md ./附图.png --title "方案" --project "工作"
agentshelf search "周报"
agentshelf status
agentshelf backup
agentshelf restore ./备份.zip --yes
agentshelf stop
```

内容已存在时，`archive` 以退出码 2 返回已有的候选知识，不会自动覆盖。之后使用 `--new-artifact`，或 `--artifact-id <编号>` 追加版本。

## 安装 Skill

把下面这段话发给 Agent，由它从本仓库安装归档 Skill：

```text
请从 https://github.com/atorber/agentshelf 安装 Skill agentshelf-archive（目录 skill/agentshelf-archive）。安装到我当前使用的 Agent 的用户级 skills 目录，使所有项目可用。安装完成后告诉我安装位置。
```

归档时对 Agent 说：「把这份最终稿归档到 AgentShelf。」名称、项目、标签和来源由 Skill 根据当前任务填写。安装 Skill 时先比较版本。服务已启动且版本不低于 Skill 就直接使用；Skill 更新时下载对应版本的启动器并重启服务。

## 主要接口

除 `GET /api/health` 外，请求都需要本机令牌：`Authorization: Bearer <token>`。令牌写在数据目录的 `token` 文件中，权限为仅当前用户可读。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 服务是否就绪 |
| GET | `/api/status` | 数据库、存储、任务、语义检索状态 |
| POST | `/api/ingest` | 上传并归档 |
| POST | `/api/ingest/confirm` | 确认重复内容的处理方式 |
| GET | `/api/artifacts` | 列表或检索 |
| GET | `/api/artifacts/{id}` | 详情 |
| PATCH | `/api/artifacts/{id}` | 修改名称、描述、项目、标签、来源 |
| DELETE | `/api/artifacts/{id}` | 删除这条知识 |
| GET | `/api/artifacts/{id}/preview` | 预览数据 |
| GET | `/api/artifacts/{id}/download` | 下载原始文件，响应头带 SHA-256 |
| GET | `/api/artifacts/{id}/verify` | 重新计算哈希并比对 |
| POST | `/api/artifacts/{id}/versions/{version}/restore` | 把历史版本恢复为新的当前版本 |
| GET/POST/PATCH/DELETE | `/api/projects` `/api/tags` `/api/agents` | 项目、标签、来源 |
| POST | `/api/backups` | 创建备份 |
| POST | `/api/backups/{name}/restore` | 从已有备份恢复 |
| GET/PUT | `/api/cloud` | 读取或保存 S3 配置，响应不含 Secret Key |
| POST | `/api/cloud/backup` | 创建备份并上传到配置的目录 |
| PUT | `/api/cloud/sync` | 保存云同步的 Bucket 和根目录 |
| POST | `/api/cloud/sync` | 按本地目录结构同步到云端，包含数据库 |
| POST | `/api/cloud/sync/pull` | 用云端目录替换本地存储，令牌和密钥留在本机 |
| POST | `/api/semantic/import` | 校验并登记本地模型目录 |
| POST | `/api/semantic/enable` | 开启或关闭语义检索 |
| POST | `/api/semantic/rebuild` | 重建语义索引 |
| DELETE | `/api/semantic` | 删除语义索引 |
| GET | `/api/inspector/skills` | 发现本机 Skill 目录并显示已有报告 |
| POST | `/api/inspector/analyses` | 静态分析 `SKILL.md` 或整个 Skill 目录 |
| GET | `/api/inspector/reports/{id}` | 读取学习报告、流程和工具证据 |
| GET | `/api/inspector/reports/{id}/files/{fileId}` | 读取报告快照中的文件文本 |
| POST | `/api/inspector/reports/{id}/questions` | 基于当前报告提问 |
| GET | `/api/inspector/reports/{id}/export` | 导出 Markdown 报告 |
| DELETE | `/api/inspector/skills/{id}` | 删除导入记录和报告，不删除原始 Skill |

语义检索需要自行安装可选依赖 `pip install -e ".[semantic]"`，并导入含 `config.json` 与权重文件的本地模型目录。应用不会下载模型。

预览支持 Markdown、HTML、文本、CSV、JSON、PNG/JPEG/GIF/WebP 和 PDF。HTML 在隔离页面里显示样式和页面内交互。其他格式提供下载。SVG 不作为图片内嵌预览。

## 备份

备份是一个 zip，内含 `manifest.json`、数据库快照和对象文件。恢复前会做路径检查和完整性检查。恢复失败时会把原来的数据库和文件移回。

设置页可以填写标准 S3，把 zip 备份上传到指定目录。密钥写在数据目录的 `cloud.json`，权限仅当前用户可读，接口不会回传 Secret Key。`agentshelf backup --cloud` 使用已保存的配置上传。

云同步使用同一套访问地址和密钥，另设 Bucket 和根目录，按本机数据目录逐文件镜像，包括 `library.db`。令牌、`cloud.json`、运行状态、日志和暂存不会上传。同步和拉取都是手动操作。

## 学习 Skill

学习页用静态分析阅读本机 Skill，帮助理解它的结构、步骤和工具。分析只读取文件，不执行脚本，也不修改原始 Skill。

会查找这些目录中的 `SKILL.md`：`~/.cursor/skills`、`~/.claude/skills`、`~/.agents/skills`、`~/.codex/skills`。其他位置可以在页面里填入 `SKILL.md` 或它所在的目录。快速分析只读 `SKILL.md`。深度分析读取该目录内的文本文件，不跟随指向目录外的符号链接。单次最多纳入 80 个文件，单个文本超过 512KB 时不读取正文。

流程图、工具清单和学习报告来自同一次分析。结论会标成原文、已声明、文本引用或推断。能定位时给出文件和行号，定位不到时只保留文件级引用。静态分析不知道 Agent 运行时实际选择了哪条分支。疑似密钥在报告正文里脱敏。要求忽略既有规则的文本只当作不可信内容。

问答只使用当前报告。文件没有变化时再次分析会打开已有报告；内容变化后生成新快照，旧报告仍可打开。

## 测试

```bash
source .venv/bin/activate
pytest
```

覆盖归档去重、版本恢复、全文检索、预览、损坏文件、备份恢复、云端备份与云同步、Skill 静态分析、令牌、断网条件下不依赖外部地址，以及 CLI 通过本地 API 归档。

## 已知限制与排查

- 首版是单人本地库，没有账号、远程访问和团队权限。云端备份上传 zip；云同步按目录镜像存储。两者都要手动执行，不会在后台自动进行。
- Skill 学习是静态分析，不会执行 Skill，也不能还原 Agent 运行时实际走过的分支。
- 安装包需要在 macOS 和 Windows 上分别构建。仓库里提供了 Tauri 的 dmg / nsis 配置。
- 桌面壳优先使用仓库里的 `.venv`。换机器后先执行 `./scripts/dev.sh` 或 `pip install -e .`。
- 语义检索在没有本地模型和可选依赖时不可用，全文检索不受影响。
- 少于 3 个字符的检索会退回普通匹配。SQLite 的 trigram 索引对中文更合适。
- 单个文件默认上限 200MB，可用环境变量 `AGENTSHELF_MAX_UPLOAD` 调整。
- 服务只绑定 `127.0.0.1`。把 `AGENTSHELF_HOST` 设成其他地址会直接拒绝启动。
- 页面停在“正在启动”时，看数据目录里的 `logs/agentshelf.log`，或运行 `agentshelf status`。
- 端口 8765 被占用时，会在 8765–8865 之间选择空闲端口，并写到数据目录的 `runtime.json`。
- 预览失败只影响该文件。可以继续下载，并用校验按钮核对 SHA-256。
- 关闭桌面窗口只会停止由它启动的后端。终端里单独运行的 `agentshelf serve` 用 `agentshelf stop` 结束。
