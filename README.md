# AgentShelf

AgentShelf 是一个本地个人产物库，用来保存 AI 最终产出的文件，并在本机完成检索、预览、版本和备份。正常使用不需要互联网，也不会把文件、检索词或使用记录发到外部服务。

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

- 产物身份是独立编号。文件名不会用来覆盖已有产物。
- 文件按 SHA-256 保存。相同内容只保留一份物理文件。
- 相同内容再次归档时，必须明确选择“新产物”或“追加到指定产物”。
- 全文检索使用 SQLite FTS5。语义检索是可选项，模型由用户自行导入，未启用时其余功能完整可用。
- 索引任务放在 SQLite 队列里。异常退出后，未完成任务会在下次启动时继续。
- 数据目录使用操作系统标准位置。macOS 为 `~/Library/Application Support/AgentShelf`。

## 运行

在仓库根目录：

```bash
chmod +x scripts/dev.sh
./scripts/dev.sh
```

脚本会准备虚拟环境、启动本地服务，并打开界面：<http://127.0.0.1:1420>。

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

界面支持点击选择、拖拽和多文件上传。上传前可以填写名称、描述、项目和标签。每个文件单独记录结果，一个失败不会回滚其他文件。

命令行：

```bash
agentshelf archive ./最终稿.md --title "周报" --project "工作" --tags "报告" --source "cursor"
agentshelf search "周报"
agentshelf status
agentshelf backup
agentshelf restore ./备份.zip --yes
agentshelf stop
```

内容已存在时，`archive` 以退出码 2 返回候选产物，不会自动覆盖。之后使用 `--new-artifact`，或 `--artifact-id <编号>` 追加版本。

## 安装 Skill

`skill/agentshelf-archive` 让 Agent 在你明确要求归档时调用本机 `agentshelf`。它和界面上传走同一套规则，只保存确认过的最终成果，不收集思考过程、日志和中间文件。

先让命令行可用，并保证本地服务已经在跑：

```bash
source .venv/bin/activate
pip install -e .
agentshelf status
```

`agentshelf status` 能连上本机服务后，再安装 Skill。

还没有这份仓库时，从 GitHub 安装。仓库地址是 <https://github.com/atorber/agentshelf>，Skill 在 `main` 分支的 `skill/agentshelf-archive`。

只下载 Skill 文件，安装到当前用户的所有 Cursor 项目：

```bash
mkdir -p ~/.cursor/skills/agentshelf-archive
curl -fsSL \
  -o ~/.cursor/skills/agentshelf-archive/SKILL.md \
  https://raw.githubusercontent.com/atorber/agentshelf/main/skill/agentshelf-archive/SKILL.md
```

克隆仓库后再复制。以后 Skill 目录里如果增加了脚本或说明，用这种方式可以一次拿全：

```bash
git clone --depth 1 https://github.com/atorber/agentshelf.git
mkdir -p ~/.cursor/skills
cp -R agentshelf/skill/agentshelf-archive ~/.cursor/skills/
```

已经在仓库目录里时，给当前用户的所有项目使用（Cursor）：

```bash
mkdir -p ~/.cursor/skills
cp -R skill/agentshelf-archive ~/.cursor/skills/
```

只在本仓库使用（Cursor）：

```bash
mkdir -p .cursor/skills
cp -R skill/agentshelf-archive .cursor/skills/
```

Claude Code 的个人技能目录是 `~/.claude/skills`，项目技能目录是 `.claude/skills`，复制方式相同。其他会读取 `SKILL.md` 的 Agent，把该目录放到它自己的 skills 目录，文件夹名保持 `agentshelf-archive`。

不要复制到 `~/.cursor/skills-cursor`。那个目录由 Cursor 自己管理。

装好后新开一轮对话，直接说“把这个最终稿归档到 AgentShelf”。Agent 会执行 `agentshelf archive`。内容已存在时退出码为 2，它会把候选产物列出来，等你选择新建还是追加版本。

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
| DELETE | `/api/artifacts/{id}` | 删除产物 |
| GET | `/api/artifacts/{id}/preview` | 预览数据 |
| GET | `/api/artifacts/{id}/download` | 下载原始文件，响应头带 SHA-256 |
| GET | `/api/artifacts/{id}/verify` | 重新计算哈希并比对 |
| POST | `/api/artifacts/{id}/versions/{version}/restore` | 把历史版本恢复为新的当前版本 |
| GET/POST/PATCH/DELETE | `/api/projects` `/api/tags` `/api/agents` | 项目、标签、来源 |
| POST | `/api/backups` | 创建备份 |
| POST | `/api/backups/{name}/restore` | 从已有备份恢复 |
| POST | `/api/semantic/import` | 校验并登记本地模型目录 |
| POST | `/api/semantic/enable` | 开启或关闭语义检索 |
| POST | `/api/semantic/rebuild` | 重建语义索引 |
| DELETE | `/api/semantic` | 删除语义索引 |

语义检索需要自行安装可选依赖 `pip install -e ".[semantic]"`，并导入含 `config.json` 与权重文件的本地模型目录。应用不会下载模型。

预览支持 Markdown、文本、CSV、JSON、PNG/JPEG/GIF/WebP 和 PDF。其他格式提供下载。SVG 不作为图片内嵌预览。

## 备份

备份是一个 zip，内含 `manifest.json`、数据库快照和对象文件。恢复前会做路径检查和完整性检查。恢复失败时会把原来的数据库和文件移回。

## 测试

```bash
source .venv/bin/activate
pytest
```

覆盖归档去重、版本恢复、全文检索、预览、损坏文件、备份恢复、令牌、断网条件下不依赖外部地址，以及 CLI 通过本地 API 归档。

## 已知限制与排查

- 首版是单人本地库，没有账号、云同步、远程访问和团队权限。
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
