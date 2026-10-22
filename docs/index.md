# AgentShelf

<p class="ash-lead">面向多个 AI Agent 的本地最终产物库。任务结束后，把值得留下的最终稿收进这台电脑，在一个窗口里检索、预览和保留版本。</p>
<p class="ash-meta">当前版本 0.2.2 · macOS 与 Windows · 文件、检索词和使用记录都留在本机</p>

<div class="ash-actions" markdown>

[安装并归档第一份](quickstart.md){ .md-button .md-button--primary }
[看产品说明](product.md){ .md-button }

</div>

## 三步用起来

<div class="grid cards" markdown>

-   :material-download:{ .lg .middle } __安装一次__

    ---

    把一段提示词发给正在使用的 Agent。它安装 Skill 并打开窗口。每个 Agent 只做一次。

    [提示词 :material-arrow-right:](quickstart.md#install)

-   :material-archive-arrow-down:{ .lg .middle } __一句话归档__

    ---

    任务完成时说「把这份最终稿归档到 AgentShelf。」名称、项目、标签和来源由 Agent 填写。

    [归档 :material-arrow-right:](agent.md#archive)

-   :material-eye-outline:{ .lg .middle } __在窗口里确认__

    ---

    一个文件直接预览。多个文件先列出，再点开查看。版本、来源和备份都在同一处。

    [窗口说明 :material-arrow-right:](usage.md)

</div>

## 留下什么

AgentShelf 保管各 Agent 值得留下的最终成果：文档、代码、图片、报告和数据文件，以及后来的修改。每份产物记下编号、来源 Agent、所属项目和归档时间。

思考过程、工具调用记录和临时中间稿留在 Agent 自己的会话里，不会进库。

<div class="grid cards" markdown>

-   :material-folder-multiple-outline:{ .lg .middle } __统一归档__

    ---

    Claude Code、Cursor、Codex，以及其他支持 Skill 的 Agent，把最终稿交到同一个本机库。你也可以自己拖进窗口。原项目里的文件仍留在原处。

-   :material-text-search:{ .lg .middle } __统一检索__

    ---

    按标题、正文和文件名查找，再用项目、标签、来源和格式筛选。筛选写在地址里，从详情返回后还在。

-   :material-source-branch:{ .lg .middle } __版本可追溯__

    ---

    每份产物有稳定编号。后续更新生成新版本，旧内容仍可预览，也可以恢复成新的当前版本。文件名不会用来覆盖已有记录。

</div>

相同内容只保存一份文件。再次遇到时，由你选择新建一份产物，或追加到已有产物。规则见 [产品说明](product.md)。

## 窗口

窗口有四个页面。左侧显示服务是否在响应，以及当前产物数量。

| 页面 | 用来 |
|---|---|
| [产物库](usage.md#library) | 浏览、搜索和筛选。一行一条，点进去看详情 |
| [上传](usage.md#upload) | 不经过 Agent，自己把文件放进库 |
| [整理](usage.md#organize) | 维护项目、标签和来源。删除它们不会删除产物 |
| [设置](usage.md#settings) | 复制提示词、查看数据目录、备份，以及按需启用语义检索 |

## 给开发者

改程序、本地构建和接口在 GitHub 项目里：[atorber/agentshelf](https://github.com/atorber/agentshelf)。
