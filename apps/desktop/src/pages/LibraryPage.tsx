import { useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { listAgents, listArtifacts, listProjects, listTags } from "../api"
import { Icon } from "../components/Icon"
import { SnippetText } from "../components/SnippetText"
import { formatTime, kindLabel, rememberLibrary } from "../format"
import type { Agent, LibraryItem, Project, Tag } from "../types"

const FILTER_KEYS = ["q", "mode", "project", "tag", "source", "kind"] as const

export function LibraryPage() {
  const [params, setParams] = useSearchParams()
  const query = params.get("q") || ""
  const mode = params.get("mode") || "keyword"
  const project = params.get("project") || ""
  const tag = params.get("tag") || ""
  const source = params.get("source") || ""
  const kind = params.get("kind") || ""
  const [items, setItems] = useState<LibraryItem[]>([])
  const [total, setTotal] = useState(0)
  const [projects, setProjects] = useState<Project[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)
  const [ready, setReady] = useState(false)

  const search = params.toString()
  useEffect(() => {
    rememberLibrary(search ? `?${search}` : "")
  }, [search])

  function setFilter(key: (typeof FILTER_KEYS)[number], value: string) {
    const next = new URLSearchParams(params)
    if (value && !(key === "mode" && value === "keyword")) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const filtered = FILTER_KEYS.some((key) => key !== "mode" && params.get(key))

  useEffect(() => {
    Promise.all([listProjects(), listTags(), listAgents()])
      .then(([projectBody, tagBody, agentBody]) => {
        setProjects(projectBody.items)
        setTags(tagBody.items)
        setAgents(agentBody.items)
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "筛选项读取失败"))
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoading(true)
      listArtifacts({ q: query, project, tag, source, kind, mode: query ? mode : "keyword" })
        .then((body) => {
          setItems(body.items)
          setTotal(body.total)
          setError("")
          setReady(true)
        })
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "检索失败"))
        .finally(() => setLoading(false))
    }, 180)
    return () => window.clearTimeout(timer)
  }, [kind, mode, project, query, source, tag])

  return (
    <section className="page">
      <div className="page-head">
        <h1>产物库</h1>
        <Link className="btn-primary" to="/upload">
          <Icon name="upload" />
          上传
        </Link>
      </div>
      <div className="filters">
        <div className="search">
          <Icon name="search" />
          <input value={query} onChange={(event) => setFilter("q", event.target.value)} placeholder="搜索标题、正文、文件名" aria-label="搜索" />
          {query ? (
            <select value={mode} onChange={(event) => setFilter("mode", event.target.value)} aria-label="检索方式">
              <option value="keyword">全文</option>
              <option value="semantic">语义</option>
              <option value="hybrid">混合</option>
            </select>
          ) : null}
        </div>
        <select value={project} onChange={(event) => setFilter("project", event.target.value)} aria-label="项目">
          <option value="">全部项目</option>
          {projects.map((item) => (
            <option key={item.id}>{item.name}</option>
          ))}
        </select>
        <select value={tag} onChange={(event) => setFilter("tag", event.target.value)} aria-label="标签">
          <option value="">全部标签</option>
          {tags.map((item) => (
            <option key={item.id}>{item.name}</option>
          ))}
        </select>
        <select value={source} onChange={(event) => setFilter("source", event.target.value)} aria-label="来源">
          <option value="">全部来源</option>
          {agents.map((item) => (
            <option key={item.id}>{item.name}</option>
          ))}
        </select>
        <select value={kind} onChange={(event) => setFilter("kind", event.target.value)} aria-label="格式">
          <option value="">全部格式</option>
          {Object.entries(kindLabel).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <div className="result-bar">
        <span>{!ready ? (loading ? "正在读取…" : "") : loading ? "正在更新…" : query ? `${total} 条结果，包含历史版本` : `${total} 个产物`}</span>
        {filtered ? (
          <button className="btn-text" onClick={() => setParams({}, { replace: true })}>
            清除筛选
          </button>
        ) : null}
      </div>
      {!ready && loading ? <SkeletonList /> : null}
      {ready && !loading && items.length === 0 ? (
        <div className="items empty">
          {filtered ? (
            <>
              <strong>没有匹配的产物</strong>换个关键词，或清除筛选。
            </>
          ) : (
            <>
              <strong>还没有产物</strong>在 Agent 里说「把这份最终稿归档到 AgentShelf。」，或者直接上传文件。
            </>
          )}
        </div>
      ) : null}
      {ready && items.length > 0 ? (
        <div className="items">
          {items.map((item) => (
            <Link
              className="item"
              key={query ? item.version_id : item.artifact_id}
              to={query && !item.is_current ? `/artifacts/${item.artifact_id}?version=${item.version_id}` : `/artifacts/${item.artifact_id}`}
            >
              {item.file_count > 1 ? (
                <span className="kind kind-bundle">{item.file_count} 个文件</span>
              ) : (
                <span className={`kind kind-${item.preview_kind}`}>{kindLabel[item.preview_kind] || item.preview_kind}</span>
              )}
              <div className="grow">
                <div className="item-title">
                  <span>{item.title}</span>
                  {!item.is_current ? <span className="badge">v{item.version_number}</span> : null}
                </div>
                <div className="item-sub">
                  {[item.file_count > 1 ? "" : item.filename, item.project, item.description].filter(Boolean).join(" · ")}
                </div>
                {query && item.snippet ? <SnippetText value={item.snippet} /> : null}
              </div>
              <div className="tags">
                {item.tags.map((name) => (
                  <span className="tag" key={name}>
                    {name}
                  </span>
                ))}
              </div>
              <div className="item-meta">
                <div>{formatTime(item.updated_at)}</div>
                <div className="faint">{item.source_agent || "—"}</div>
              </div>
            </Link>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function SkeletonList() {
  return (
    <div className="items">
      {[0, 1, 2, 3].map((index) => (
        <div className="item" key={index}>
          <div className="skeleton" />
          <div className="stack" style={{ gap: 6 }}>
            <div className="skeleton" style={{ width: "40%" }} />
            <div className="skeleton" style={{ width: "65%", height: 10 }} />
          </div>
          <span />
          <div className="skeleton" style={{ height: 10 }} />
        </div>
      ))}
    </div>
  )
}
