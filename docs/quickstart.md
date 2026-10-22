# 快速开始

准备 Python 3.11 或更高版本。要打开界面，还需要 Node.js。要编译桌面安装包，需要本机已安装 Rust。

下面的步骤在仓库根目录执行。

## 打开界面

```bash
chmod +x scripts/dev.sh
./scripts/dev.sh
```

脚本会创建虚拟环境、安装依赖、启动本地服务，并打开界面：<http://127.0.0.1:1420>。

关闭这个终端时，由它启动的服务会一起停止。页面如果停在「正在启动」，先看 [排查](troubleshooting.md)。

## 归档第一份文件

1. 打开「上传」。
2. 点击选择文件，或把文件拖进页面。可以一次放入多个文件。
3. 按需要填写名称、描述、项目、标签和来源。名称默认取文件名去掉扩展名。
4. 开始上传。每个文件单独显示结果，一个文件失败不会撤销其他已经成功的文件。
5. 上传完成后，从结果进入产物详情，确认预览和版本。

相同内容已经存在时，页面会列出候选产物。选择「创建新产物」，或追加为某个已有产物的新版本。应用不会按文件名自动覆盖。

## 用命令行归档

先保证本地服务已经在运行，再执行：

```bash
source .venv/bin/activate
agentshelf archive ./最终稿.md --title "周报" --project "工作" --tags "报告" --source "cursor"
agentshelf search "周报"
```

`archive` 在内容已存在时以退出码 2 结束，并打印候选产物。之后在同一条命令上追加 `--new-artifact`，或使用 `--artifact-id <编号>` 追加版本。

只想启动服务、不打开界面时：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
agentshelf serve
```

另开一个终端使用 `agentshelf archive`、`search`、`status`。这个服务由你自己启动，关闭桌面窗口不会把它停掉。结束时执行 `agentshelf stop`。

## 打开桌面窗口

桌面壳会自行拉起后端。关闭窗口时，由它启动的服务会停止。

```bash
cd apps/desktop
npm install
npm run tauri dev
```

这需要本机已安装 Rust。在 macOS 上生成 dmg，在 Windows 上生成 nsis：

```bash
npm run tauri build
```

## 让 Agent 归档

把下面这段话发给当前使用的 Agent：

```text
请从 https://github.com/atorber/agentshelf 安装 Skill agentshelf-archive（目录 skill/agentshelf-archive）。安装到我当前使用的 Agent 的用户级 skills 目录，使所有项目可用。安装完成后告诉我安装位置。
```

安装之后，在任务结束并确认最终稿时，让 Agent 把文件归档到 AgentShelf。Skill 会先启动本机服务和界面，再调用本地命令。细节见 [命令行与 Skill](cli-and-skill.md)。
