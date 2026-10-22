import { useEffect, useState } from "react"
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
    <section>
      <div className="page-head">
        <div>
          <h1>整理</h1>
          <p>项目、标签和来源只用于归档和筛选。删除项目或来源不会删除产物。</p>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {loading ? (
        <div className="empty">正在读取项目、标签和来源…</div>
      ) : (
      <div className="columns">
        <Manager
          title="项目"
          rows={projects.map((item) => ({ id: item.id, name: item.name, extra: item.description, count: item.artifact_count }))}
          extraLabel="描述"
          onCreate={(name, extra) => createProject(name, extra).then(reload)}
          onUpdate={(id, name, extra) => updateProject(id, name, extra).then(reload)}
          onDelete={(id) => deleteProject(id).then(reload)}
        />
        <Manager
          title="标签"
          rows={tags.map((item) => ({ id: item.id, name: item.name, extra: "", count: item.artifact_count }))}
          onCreate={(name) => createTag(name).then(reload)}
          onUpdate={(id, name) => updateTag(id, name).then(reload)}
          onDelete={(id) => deleteTag(id).then(reload)}
        />
        <Manager
          title="来源 Agent"
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
  rows,
  extraLabel,
  onCreate,
  onUpdate,
  onDelete,
}: {
  title: string
  rows: Array<{ id: string; name: string; extra: string; count: number }>
  extraLabel?: string
  onCreate: (name: string, extra: string) => Promise<unknown>
  onUpdate: (id: string, name: string, extra: string) => Promise<unknown>
  onDelete: (id: string) => Promise<unknown>
}) {
  const [name, setName] = useState("")
  const [extra, setExtra] = useState("")
  const [editing, setEditing] = useState("")
  const [draft, setDraft] = useState("")
  const [draftExtra, setDraftExtra] = useState("")
  const [error, setError] = useState("")

  async function create() {
    try {
      await onCreate(name.trim(), extra.trim())
      setName("")
      setExtra("")
      setError("")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败")
    }
  }

  return (
    <div className="panel">
      <h2>{title}</h2>
      <div className="stack">
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder={`新${title}`} />
        {extraLabel ? <input value={extra} onChange={(event) => setExtra(event.target.value)} placeholder={extraLabel} /> : null}
        <button className="btn-primary" onClick={create} disabled={!name.trim()}>
          添加
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {rows.length === 0 ? <p className="muted">还没有{title}</p> : null}
      {rows.map((row) => (
        <div className="manage-row" key={row.id}>
          {editing === row.id ? (
            <>
              <input value={draft} onChange={(event) => setDraft(event.target.value)} />
              {extraLabel ? <input value={draftExtra} onChange={(event) => setDraftExtra(event.target.value)} /> : <span />}
              <button
                className="btn-ghost"
                onClick={() =>
                  onUpdate(row.id, draft, draftExtra)
                    .then(() => setEditing(""))
                    .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "保存失败"))
                }
              >
                保存
              </button>
            </>
          ) : (
            <>
              <div>
                <strong>{row.name}</strong>
                <div className="muted">
                  {row.count} 个产物{row.extra ? ` · ${row.extra}` : ""}
                </div>
              </div>
              <span />
              <div className="actions">
                <button
                  className="btn-ghost"
                  onClick={() => {
                    setEditing(row.id)
                    setDraft(row.name)
                    setDraftExtra(row.extra)
                  }}
                >
                  重命名
                </button>
                <button
                  className="btn-danger"
                  onClick={() => {
                    if (window.confirm(`删除${title}「${row.name}」？`)) onDelete(row.id).catch(() => setError("删除失败"))
                  }}
                >
                  删除
                </button>
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  )
}
