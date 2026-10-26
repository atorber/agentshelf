import { useEffect, useState } from "react"
import { analyzeInspectorSkill, askInspector, getInspectorFile, getInspectorReport, listInspectorSkills } from "../api"
import type { InspectorAnswer, InspectorNode, InspectorReport, InspectorSkill } from "../types"

const TABS = [
  ["overview", "概览"],
  ["flow", "流程图"],
  ["tools", "工具"],
  ["files", "文件"],
  ["report", "学习报告"],
  ["ask", "问答"],
] as const

const STATUS_LABEL: Record<InspectorSkill["status"], string> = {
  discovered: "未分析",
  analyzed: "已分析",
  changed: "文件已变化",
  missing: "无法读取",
}

export function LearnPage() {
  const [skills, setSkills] = useState<InspectorSkill[]>([])
  const [path, setPath] = useState("")
  const [report, setReport] = useState<InspectorReport | null>(null)
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("overview")
  const [nodeId, setNodeId] = useState("")
  const [snippet, setSnippet] = useState("")
  const [question, setQuestion] = useState("")
  const [answer, setAnswer] = useState<InspectorAnswer | null>(null)
  const [confirmedOnly, setConfirmedOnly] = useState(false)
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  async function reload() {
    setSkills((await listInspectorSkills()).items)
  }

  useEffect(() => {
    reload().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "读取失败"))
  }, [])

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError("")
    setMessage("")
    try {
      await action()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败")
    }
    setBusy(false)
  }

  async function openReport(id: string) {
    const body = await getInspectorReport(id)
    setReport(body)
    setNodeId(body.nodes[0]?.id || "")
    setSnippet("")
    setAnswer(null)
    setTab("overview")
  }

  async function analyze(target: string, mode: "quick" | "deep") {
    const body = await analyzeInspectorSkill(target, mode, false)
    setReport(body)
    setNodeId(body.nodes[0]?.id || "")
    setSnippet("")
    setAnswer(null)
    setTab("flow")
    setMessage(body.reused ? "文件没有变化，打开了已有报告。" : "分析完成。流程来自静态推断。")
    await reload()
  }

  async function showFile(fileId: string) {
    if (!report) return
    const file = await getInspectorFile(report.id, fileId)
    setSnippet(`${file.path}\n\n${file.text || "这个文件没有可显示的文本。"}`)
    setTab("files")
  }

  const node = report?.nodes.find((item) => item.id === nodeId) || null
  const nodes = (report?.nodes || []).filter((item) => !confirmedOnly || item.evidenceType === "static")

  return (
    <section className="page">
      <div className="page-head">
        <div>
          <h1>Skill 学习</h1>
          <p>静态阅读 Skill 的结构、流程和工具。不执行 Skill，也不修改原始文件。</p>
        </div>
      </div>
      {message ? <p className="notice">{message}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <div className="inspector-layout">
        <div className="panel">
          <div className="panel-head">
            <h2>可分析的 Skill</h2>
          </div>
          <div className="panel-body">
            <label className="field">
              <span>导入路径</span>
              <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="SKILL.md 或它所在的目录" aria-label="导入路径" />
            </label>
            <div className="row">
              <button className="btn" disabled={busy || !path.trim()} onClick={() => run(() => analyze(path.trim(), "quick"))}>
                快速分析
              </button>
              <button className="btn" disabled={busy || !path.trim()} onClick={() => run(() => analyze(path.trim(), "deep"))}>
                深度分析
              </button>
            </div>
            {skills.length === 0 ? <p className="muted small">还没有从 Cursor、Claude、Agents 或 Codex 的 Skill 目录发现 SKILL.md。可以在上面填入路径。</p> : null}
            {skills.map((skill) => (
              <div className="inspector-skill" key={skill.path}>
                <div className="item-title">
                  <span>{skill.name}</span>
                  <span className={skill.status === "analyzed" ? "badge current" : "badge"}>{STATUS_LABEL[skill.status]}</span>
                </div>
                <p className="item-sub">{skill.source_label} · {skill.readable ? "可读取" : "不可读取"}</p>
                <p className="muted small">{skill.description || skill.path}</p>
                <div className="row">
                  <button className="btn" disabled={busy || !skill.readable} onClick={() => run(() => analyze(skill.path, "quick"))}>
                    快速分析
                  </button>
                  <button className="btn" disabled={busy || !skill.readable} onClick={() => run(() => analyze(skill.path, "deep"))}>
                    深度分析
                  </button>
                  {skill.report_id ? (
                    <button className="btn-text" disabled={busy} onClick={() => run(() => openReport(skill.report_id || ""))}>
                      打开报告
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head">
            <h2>{report?.overview.name || "学习工作台"}</h2>
            {report ? <span className="badge current">{report.overview.mode === "deep" ? "深度分析" : "快速分析"} · 静态推断</span> : null}
          </div>
          {report ? (
            <div className="panel-body">
              <div className="inspector-tabs">
                {TABS.map(([id, label]) => (
                  <button key={id} className={tab === id ? "btn-primary" : "btn"} onClick={() => setTab(id)}>
                    {label}
                  </button>
                ))}
              </div>
              {tab === "overview" ? <Overview report={report} /> : null}
              {tab === "flow" ? (
                <div className="inspector-split">
                  <div>
                    <label className="row">
                      <input type="checkbox" checked={confirmedOnly} onChange={(event) => setConfirmedOnly(event.target.checked)} />
                      <span>只看已确认内容</span>
                    </label>
                    <div className="inspector-flow">
                      {nodes.map((item) => (
                        <button key={item.id} className={item.id === nodeId ? "inspector-node active" : "inspector-node"} onClick={() => setNodeId(item.id)}>
                          <strong>{item.title}</strong>
                          <span>{evidenceLabel(item.evidenceType)}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                  <NodeDetail node={node} onOpen={showFile} />
                </div>
              ) : null}
              {tab === "tools" ? (
                <div>
                  {report.tools.length === 0 ? <p className="muted">没有识别到明确的工具声明或调用。</p> : null}
                  {report.tools.map((tool) => (
                    <div className="inspector-skill" key={tool.id}>
                      <div className="item-title">
                        <span>{tool.name}</span>
                        <span className="badge">{tool.kind} · {evidenceLabel(tool.evidenceType)}</span>
                      </div>
                      <p>{tool.purpose}</p>
                      <p className="muted small">{tool.sourceRefs.map(refText).join("；") || "没有精确位置"}</p>
                    </div>
                  ))}
                </div>
              ) : null}
              {tab === "files" ? (
                <div className="inspector-split">
                  <div>
                    {report.files.map((file) => (
                      <button key={file.id} className="inspector-node" onClick={() => run(() => showFile(file.id))}>
                        <strong>{file.path}</strong>
                        <span>{file.sizeBytes} 字节</span>
                      </button>
                    ))}
                  </div>
                  <pre className="inspector-code">{snippet || "选择一个文件查看已纳入分析的文本。"}</pre>
                </div>
              ) : null}
              {tab === "report" ? (
                <div>
                  {report.sections.map((section) => (
                    <section key={section.id} className="inspector-skill">
                      <h3>{section.title}</h3>
                      {section.paragraphs.map((paragraph) => (
                        <p key={paragraph}>{paragraph}</p>
                      ))}
                    </section>
                  ))}
                </div>
              ) : null}
              {tab === "ask" ? (
                <div>
                  <p className="muted small">回答只使用当前报告里的文件证据，并区分事实和推断。</p>
                  <div className="row">
                    <input className="grow" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：这个 Skill 的核心步骤是什么？" aria-label="学习问题" />
                    <button
                      className="btn-primary"
                      disabled={busy || !question.trim()}
                      onClick={() =>
                        run(async () => {
                          setAnswer(await askInspector(report.id, question.trim()))
                        })
                      }
                    >
                      提问
                    </button>
                  </div>
                  {answer ? (
                    <div className="inspector-skill">
                      <p>{answer.answer}</p>
                      {answer.claims.map((claim) => (
                        <p key={claim.text} className="muted small">
                          {evidenceLabel(claim.evidenceType)}：{claim.text}
                        </p>
                      ))}
                      {answer.unknowns.map((item) => (
                        <p key={item} className="muted small">
                          未知：{item}
                        </p>
                      ))}
                      {answer.evidence.length ? <p className="muted small">{answer.evidence.map(refText).join("；")}</p> : null}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="panel-body">
              <p className="muted">选择一个 Skill 并开始分析。快速分析只读 SKILL.md；深度分析读取该目录里的文本文件。</p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function Overview({ report }: { report: InspectorReport }) {
  return (
    <div>
      <p>{report.overview.purpose}</p>
      {report.overview.limitations.map((item) => (
        <p key={item} className="muted small">
          {item}
        </p>
      ))}
      {report.findings.map((item) => (
        <p key={item.message} className="muted small">
          {item.message}
        </p>
      ))}
      <p className="muted small">纳入 {report.overview.fileCount} 个文件。报告不会覆盖更早的快照。</p>
    </div>
  )
}

function NodeDetail({ node, onOpen }: { node: InspectorNode | null; onOpen: (fileId: string) => Promise<void> }) {
  if (!node) return <p className="muted">选择一个节点。</p>
  return (
    <div className="inspector-detail">
      <h3>{node.title}</h3>
      <p>{node.description}</p>
      <p className="muted small">{evidenceLabel(node.evidenceType)} · {node.nodeType}</p>
      {node.sourceRefs.map((ref) => (
        <p key={`${ref.path}-${ref.start_line}`}>
          <span className="muted small">{refText(ref)}</span>
          {ref.fileId ? (
            <button className="btn-text" onClick={() => onOpen(ref.fileId || "")}>
              查看原文
            </button>
          ) : null}
        </p>
      ))}
    </div>
  )
}

function evidenceLabel(value: string) {
  if (value === "static") return "原文"
  if (value === "declared") return "已声明"
  if (value === "referenced") return "文本引用"
  if (value === "inferred") return "推断"
  return value
}

function refText(ref: { path: string; start_line: number | null; end_line: number | null; precision: string }) {
  if (ref.precision === "line" && ref.start_line) return `${ref.path}:${ref.start_line}`
  if (ref.precision === "file_missing") return `${ref.path}（文件不在分析范围内）`
  return `${ref.path}（文件级引用）`
}
