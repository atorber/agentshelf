import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { listAgents, listArtifacts, listProjects, listTags } from "../api"
import { SnippetText } from "../components/SnippetText"
import { formatTime, kindLabel } from "../format"
import type { Agent, LibraryItem, Project, Tag } from "../types"

export function LibraryPage() {
  const [query, setQuery] = useState("")
  const [project, setProject] = useState("")
  const [tag, setTag] = useState("")
  const [source, setSource] = useState("")
  const [kind, setKind] = useState("")
  const [mode, setMode] = useState("keyword")
  const [items, setItems] = useState<LibraryItem[]>([])
  const [total, setTotal] = useState(0)
  const [projects, setProjects] = useState<Project[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [error, setError] = useState("")

  useEffect(() => {
    Promise.all([listProjects(), listTags(), listAgents()])
      .then(([projectBody, tagBody, agentBody]) => {
        setProjects(projectBody.items)
        setTags(tagBody.items)
        setAgents(agentBody.items)
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      listArtifacts({ q: query, project, tag, source, kind, mode: query ? mode : "keyword" })
        .then((body) => {
          setItems(body.items)
          setTotal(body.total)
          setError("")
        })
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "检索失败"))
    }, 180)
    return () => window.clearTimeout(timer)
  }, [kind, mode, project, query, source, tag])

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>产物库</h1>
          <p>全文检索会包含历史版本。语义检索只在你启用本地模型后可用。</p>
        </div>
        <Link className="btn-primary" to="/upload">
          上传产物
        </Link>
      </div>
      <div className="filters">
        <label className="field grow">
          <span>搜索</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="标题、正文、文件名" />
        </label>
        <label className="field">
          <span>方式</span>
          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="keyword">全文</option>
            <option value="semantic">语义</option>
            <option value="hybrid">混合</option>
          </select>
        </label>
        <label className="field">
          <span>项目</span>
          <select value={project} onChange={(event) => setProject(event.target.value)}>
            <option value="">全部</option>
            {projects.map((item) => (
              <option key={item.id}>{item.name}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>标签</span>
          <select value={tag} onChange={(event) => setTag(event.target.value)}>
            <option value="">全部</option>
            {tags.map((item) => (
              <option key={item.id}>{item.name}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>来源</span>
          <select value={source} onChange={(event) => setSource(event.target.value)}>
            <option value="">全部</option>
            {agents.map((item) => (
              <option key={item.id}>{item.name}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>格式</span>
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="">全部</option>
            {Object.entries(kindLabel).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <p className="muted">{total} 条结果</p>
      {items.length === 0 ? <div className="empty">还没有匹配的产物。上传文件，或让 Agent 通过 CLI 归档最终稿。</div> : null}
      {query ? (
        <div className="list">
          {items.map((item) => (
            <Link className="result" key={item.version_id} to={`/artifacts/${item.artifact_id}?version=${item.version_id}`}>
              <div className="row">
                <h2>{item.title}</h2>
                <span className="kind">{kindLabel[item.preview_kind] || item.preview_kind}</span>
                {!item.is_current ? <span className="tag">v{item.version_number}</span> : null}
              </div>
              <div className="muted">
                {item.project || "未分组"} · {item.file_count > 1 ? `${item.file_count} 个文件` : item.filename} · {formatTime(item.updated_at)}
              </div>
              {item.snippet ? <SnippetText value={item.snippet} /> : null}
            </Link>
          ))}
        </div>
      ) : (
        <div className="grid">
          {items.map((item) => (
            <Link className="card" key={item.artifact_id} to={`/artifacts/${item.artifact_id}`}>
              <div className="row">
                <span className="kind">{kindLabel[item.preview_kind] || item.preview_kind}</span>
                <span className="muted">v{item.version_number}</span>
              </div>
              <h2>{item.title}</h2>
              <div className="muted">{item.description || (item.file_count > 1 ? `${item.file_count} 个文件` : item.filename)}</div>
              <div className="tags">
                {item.project ? <span className="tag">{item.project}</span> : null}
                {item.tags.map((name) => (
                  <span className="tag" key={name}>
                    {name}
                  </span>
                ))}
              </div>
              <div className="muted">{formatTime(item.updated_at)}</div>
            </Link>
          ))}
        </div>
      )}
    </section>
  )
}
