import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { createAgent, createProject, createTag, deleteAgent, deleteProject, deleteTag, listAgents, listProjects, listTags, updateAgent, updateProject, updateTag } from "../api"
import type { Agent, Project, Tag } from "../types"

export function OrganizePage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)

  async function reload() {
    const [projectBody, tagBody, agentBody] = await Promise.all([listProjects(), listTags(), listAgents()])
    setProjects(projectBody.items)
    setTags(tagBody.items)
    setAgents(agentBody.items)
  }

  useEffect(() => {
    reload()
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "读取失败"))
      .finally(() => setLoading(false))
  }, [])

  return (
    <section className="page">
      <div className="page-head">
        <div>
          <h1>整理</h1>
          <p>项目、标签和来源只用于归类和筛选。删除它们不会删除已收入的知识。</p>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {loading ? (
        <div className="panel empty">正在读取项目、标签和来源…</div>
      ) : (
        <div className="columns">
          <Manager
            title="项目"
            filterKey="project"
            rows={projects.map((item) => ({ id: item.id, name: item.name, extra: item.description, count: item.artifact_count }))}
            extraLabel="描述"
            onCreate={(name, extra) => createProject(name, extra).then(reload)}
            onUpdate={(id, name, extra) => updateProject(id, name, extra).then(reload)}
            onDelete={(id) => deleteProject(id).then(reload)}
          />
          <Manager
            title="标签"
            filterKey="tag"
            rows={tags.map((item) => ({ id: item.id, name: item.name, extra: "", count: item.artifact_count }))}
            onCreate={(name) => createTag(name).then(reload)}
            onUpdate={(id, name) => updateTag(id, name).then(reload)}
            onDelete={(id) => deleteTag(id).then(reload)}
          />
          <Manager
            title="来源 Agent"
            filterKey="source"
            rows={agents.map((item) => ({ id: item.id, name: item.name, extra: item.note, count: item.artifact_count }))}
            extraLabel="备注"
            onCreate={(name, extra) => createAgent(name, extra).then(reload)}
            onUpdate={(id, name, extra) => updateAgent(id, name, extra).then(reload)}
            onDelete={(id) => deleteAgent(id).then(reload)}
          />
        </div>
      )}
    </section>
  )
}

function Manager({
  title,
  filterKey,
  rows,
  extraLabel,
  onCreate,
  onUpdate,
  onDelete,
}: {
  title: string
  filterKey: string
  rows: Array<{ id: string; name: string; extra: string; count: number }>
  extraLabel?: string
  onCreate: (name: string, extra: string) => Promise<unknown>
  onUpdate: (id: string, name: string, extra: string) => Promise<unknown>
  onDelete: (id: string) => Promise<unknown>
}) {
  const [name, setName] = useState("")
  const [editing, setEditing] = useState("")
  const [draft, setDraft] = useState("")
  const [draftExtra, setDraftExtra] = useState("")
  const [error, setError] = useState("")

  async function create() {
    if (!name.trim()) return
    try {
      await onCreate(name.trim(), "")
      setName("")
      setError("")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败")
    }
  }

  async function save(id: string) {
    try {
      await onUpdate(id, draft.trim(), draftExtra.trim())
      setEditing("")
      setError("")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败")
    }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        <span className="muted small">{rows.length}</span>
      </div>
      <form
        className="add-row"
        onSubmit={(event) => {
          event.preventDefault()
          create()
        }}
      >
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder={`新建${title}`} />
        <button className="btn" type="submit" disabled={!name.trim()}>
          添加
        </button>
      </form>
      {error ? <p className="error small" style={{ padding: "8px 14px 0" }}>{error}</p> : null}
      {rows.length === 0 ? <div className="empty small">还没有{title}</div> : null}
      <div>
        {rows.map((row) =>
          editing === row.id ? (
            <form
              className="manage-row"
              key={row.id}
              style={{ flexWrap: "wrap" }}
              onSubmit={(event) => {
                event.preventDefault()
                save(row.id)
              }}
            >
              <input value={draft} onChange={(event) => setDraft(event.target.value)} autoFocus aria-label="名称" />
              {extraLabel ? <input value={draftExtra} onChange={(event) => setDraftExtra(event.target.value)} placeholder={extraLabel} aria-label={extraLabel} /> : null}
              <div className="row">
                <button className="btn-text" type="button" onClick={() => setEditing("")}>
                  取消
                </button>
                <button className="btn-primary" type="submit" disabled={!draft.trim()}>
                  保存
                </button>
              </div>
            </form>
          ) : (
            <div className="manage-row" key={row.id}>
              <div className="grow">
                <div className="item-title">
                  <span>{row.name}</span>
                </div>
                <div className="item-sub">
                  <Link to={`/?${filterKey}=${encodeURIComponent(row.name)}`}>{row.count} 条知识</Link>
                  {row.extra ? ` · ${row.extra}` : ""}
                </div>
              </div>
              <div className="row hover-actions">
                <button
                  className="btn-text"
                  onClick={() => {
                    setEditing(row.id)
                    setDraft(row.name)
                    setDraftExtra(row.extra)
                  }}
                >
                  编辑
                </button>
                <button
                  className="btn-text danger"
                  onClick={() => {
                    if (window.confirm(`删除${title}「${row.name}」？已收入的知识不会被删除。`)) onDelete(row.id).catch(() => setError("删除失败"))
                  }}
                >
                  删除
                </button>
              </div>
            </div>
          ),
        )}
      </div>
    </div>
  )
}
