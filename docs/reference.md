# 数据与接口

界面、命令行和 Skill 共用本地 FastAPI。除健康检查外，请求都要带本机令牌：`Authorization: Bearer <token>`。

## 数据目录

默认位置由操作系统决定：

| 系统 | 路径 |
|---|---|
| macOS | `~/Library/Application Support/AgentShelf` |
| Windows | `%LOCALAPPDATA%\AgentShelf` |
| Linux | `~/.local/share/AgentShelf` |

设置环境变量 `AGENTSHELF_DATA_DIR` 可以改到其他目录。改之前先停掉正在运行的服务，避免两处数据各写一半。

目录里的主要内容：

| 路径 | 内容 |
|---|---|
| `library.db` | 产物、版本、项目、标签、来源、全文索引和任务队列 |
| `objects/` | 按 SHA-256 存放的文件内容 |
| `staging/` | 等待确认的临时文件 |
| `backups/` | 本机生成的 zip 备份 |
| `models/` | 登记过的本地模型信息 |
| `logs/agentshelf.log` | 本地日志 |
| `token` | 本机访问令牌，权限为仅当前用户可读 |
| `runtime.json` | 当前服务的端口等运行信息 |

`~/.agentshelf/app`（Windows 为 `%USERPROFILE%\.agentshelf\app`）是 Skill 使用的程序副本，不是产物数据目录。

## 服务怎么监听

服务只绑定回环地址。`AGENTSHELF_HOST` 设成 `127.0.0.1`、`localhost` 和 `::1` 以外的值时，服务会拒绝启动。

默认从 8765 开始找空闲端口，范围到 8865。实际端口写在 `runtime.json`。开发界面地址是 <http://127.0.0.1:1420>，它再去连接本地 API。

单个文件默认上限 200MB。可以用 `AGENTSHELF_MAX_UPLOAD` 调整，单位是字节。`AGENTSHELF_PORT` 用来指定首选端口。

## 备份

在设置页点击「创建备份」，或执行 `agentshelf backup`。备份是一个 zip，里面有：

- `manifest.json`：备份格式版本、应用版本和创建时间
- `library.db`：数据库快照
- `objects/`：对象文件

恢复前会检查路径和完整性。开始前先把现有数据库和文件移开；恢复失败时再移回去。恢复会替换当前产物库，设置页和命令行都会先要求确认。

设置页可以下载已有备份，或从一份 zip 文件恢复。

## 语义检索

语义检索是可选项。启用前安装可选依赖：

```bash
source .venv/bin/activate
pip install -e ".[semantic]"
```

然后在设置页填写本地模型目录，执行「校验并导入」。目录里需要有 `config.json`，以及 `.safetensors`、`.bin`、`.onnx` 或 `.ot` 权重文件。校验通过后，再点击「启用」。

启用后可以重建索引，或删除语义索引。删除语义索引不会删除产物文件。关闭语义检索后，全文检索和预览保持可用。应用不会替你下载模型。

产物库里的「语义」和「混合」要在模型已启用时才有语义结果。

## 本地接口

基础地址形如 `http://127.0.0.1:8765`。端口以 `runtime.json` 为准。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 服务是否就绪。这个接口不需要令牌 |
| GET | `/api/status` | 数据库、存储、任务、语义检索状态 |
| GET | `/api/jobs` | 索引任务 |
| POST | `/api/ingest` | 上传并归档。表单字段含文件、名称、描述、项目、标签、来源、处理方式和产物编号 |
| POST | `/api/ingest/confirm` | 确认重复内容是新产物还是新版本 |
| GET | `/api/artifacts` | 列表或检索 |
| GET | `/api/search` | 与产物列表相同的检索 |
| GET | `/api/artifacts/{id}` | 详情 |
| PATCH | `/api/artifacts/{id}` | 修改名称、描述、项目、标签、来源 |
| DELETE | `/api/artifacts/{id}` | 删除产物 |
| GET | `/api/artifacts/{id}/preview` | 预览数据 |
| GET | `/api/artifacts/{id}/download` | 下载原始文件，响应头带 SHA-256 |
| GET | `/api/artifacts/{id}/verify` | 重新计算哈希并比对 |
| POST | `/api/artifacts/{id}/versions/{version}/restore` | 把历史版本恢复为新的当前版本 |
| GET、POST、PATCH、DELETE | `/api/projects`、`/api/tags`、`/api/agents` | 项目、标签、来源 |
| GET、POST | `/api/backups` | 列出或创建备份 |
| GET | `/api/backups/{name}/download` | 下载一份备份 |
| POST | `/api/backups/{name}/restore` | 从已有备份恢复 |
| POST | `/api/backups/upload-restore` | 上传一份 zip 并恢复 |
| POST | `/api/semantic/import` | 校验并登记本地模型目录 |
| POST | `/api/semantic/enable` | 开启或关闭语义检索 |
| POST | `/api/semantic/rebuild` | 重建语义索引 |
| DELETE | `/api/semantic` | 删除语义索引 |

检索参数包括 `q`、`project`、`tag`、`source`、`kind`、`mode`、`limit` 和 `offset`。`mode` 为 `keyword`、`semantic` 或 `hybrid`。

直接调用这些接口时，自己附上令牌。日常归档优先用界面或 `agentshelf` 命令，这样重复内容的确认流程和退出码都已经接好。
