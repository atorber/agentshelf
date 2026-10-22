# 快速开始

在正在使用的 Agent 里发一段提示词即可。Agent 会安装归档能力，并在本机打开 AgentShelf。不需要自己执行安装命令。

支持 Claude Code、Cursor、Codex，以及其他能安装 Skill 的 Agent。

## 安装

把下面这段话发给 Agent：

```text
请从 https://github.com/atorber/agentshelf 安装 Skill agentshelf-archive（目录 skill/agentshelf-archive）。安装到我当前使用的 Agent 的用户级 skills 目录，使所有项目可用。安装完成后告诉我安装位置，并打开 AgentShelf。
```

安装完成后，Agent 会告诉你 Skill 放在哪里，并打开本机窗口。窗口打不开或停在「正在启动」时，看 [排查](troubleshooting.md)。

## 归档第一份文件

任务结束、你确认某一份文件是最终稿之后，对 Agent 说：

```text
把 ./最终稿.md 归档到 AgentShelf。名称是「周报」，项目是「工作」，标签是「报告」。只归档这一份最终稿。
```

Agent 会回报产物名称、编号和版本。然后在窗口的产物库里打开它，确认预览是否正确。

一次可以说明多个文件。某一份失败时，其余文件仍会分别告诉你结果。

## 内容已经存在时

Agent 会列出已经保存过的相同内容，并请你选择：

- 新建一份产物。内容相同，但是另一份独立记录。
- 追加到已有产物。成为那一份的新版本。

把选择告诉 Agent 即可。它不会按文件名自行覆盖。

## 自己放入文件

打开窗口里的「上传」，点击选择或拖入文件，填写名称、项目和标签后开始上传。规则与让 Agent 归档相同。
