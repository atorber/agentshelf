import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { deleteArtifact, downloadArtifact, listAgents, listArtifacts, listProjects, listTags } from "../api"
import { BundleIcon, FileIcon } from "../components/FileIcon"
import { Icon } from "../components/Icon"
import { PreviewDrawer } from "../components/PreviewDrawer"
import { SnippetText } from "../components/SnippetText"
import { bodyFile, displayKind, formatBytes, formatRelative, formatTime, kindLabel, rememberLibrary, typeLabel } from "../format"
import type { Agent, LibraryItem, Project, Tag } from "../types"

const FILTER_KEYS = ["q", "mode", "project", "tag", "source", "kind"] as const
const PAGE = 200
const UNGROUPED = "未分组"

type SortKey = "title" | "updated" | "size"

interface Opened {
  key: string
  fileId?: string
}

function itemKey(item: LibraryItem, query: string) {
  return query ? item.version_id : item.artifact_id
}

export function LibraryPage() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()
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
  const [notice, setNotice] = useState("")
  const [loading, setLoading] = useState(true)
  const [ready, setReady] = useState(false)
  const [reload, setReload] = useState(0)
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "updated", desc: true })
  const [foldedGroups, setFoldedGroups] = useState<Set<string>>(new Set())
  const [foldedItems, setFoldedItems] = useState<Set<string>>(new Set())
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [opened, setOpened] = useState<Opened | null>(null)
  const searchBox = useRef<HTMLInputElement>(null)

  const search = params.toString()
  useEffect(() => {
    rememberLibrary(search ? `?${search}` : "")
  }, [search])

  useEffect(() => {
    if ((location.state as { focusSearch?: boolean } | null)?.focusSearch) searchBox.current?.focus()
  }, [location.state])

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
      listArtifacts({ q: query, project, tag, source, kind, mode: query ? mode : "keyword", limit: String(PAGE) })
        .then((body) => {
          setItems(body.items)
          setTotal(body.total)
          setError("")
          setReady(true)
          setChecked(new Set())
        })
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "检索失败"))
        .finally(() => setLoading(false))
    }, 180)
    return () => window.clearTimeout(timer)
  }, [kind, mode, project, query, source, tag, reload])

  async function loadMore() {
    try {
      const body = await listArtifacts({ q: query, project, tag, source, kind, mode: query ? mode : "keyword", limit: String(PAGE), offset: String(items.length) })
      setItems((current) => [...current, ...body.items])
      setTotal(body.total)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取失败")
    }
  }

  const groups = useMemo(() => {
    const sorted = [...items].sort((left, right) => {
      const order =
        sort.key === "title"
          ? left.title.localeCompare(right.title, "zh-CN")
          : sort.key === "size"
            ? (left.size_bytes || 0) - (right.size_bytes || 0)
            : left.updated_at.localeCompare(right.updated_at)
      return sort.desc ? -order : order
    })
    const map = new Map<string, LibraryItem[]>()
    for (const item of sorted) {
      const name = item.project || UNGROUPED
      map.set(name, [...(map.get(name) || []), item])
    }
    return [...map.entries()].sort(([left], [right]) => {
      if (left === UNGROUPED) return 1
      if (right === UNGROUPED) return -1
      return left.localeCompare(right, "zh-CN")
    })
  }, [items, sort])

  function toggle(setter: typeof setFoldedGroups, key: string) {
    setter((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function sortBy(key: SortKey) {
    setSort((current) => (current.key === key ? { key, desc: !current.desc } : { key, desc: key !== "title" }))
  }

  function detailPath(item: LibraryItem, fileId?: string) {
    const next = new URLSearchParams()
    if (query && !item.is_current) next.set("version", item.version_id)
    if (fileId) next.set("file", fileId)
    const text = next.toString()
    return `/artifacts/${item.artifact_id}${text ? `?${text}` : ""}`
  }

  async function removeChecked() {
    const ids = [...new Set(items.filter((item) => checked.has(itemKey(item, query))).map((item) => item.artifact_id))]
    if (!ids.length || !window.confirm(`删除选中的 ${ids.length} 条知识？删除后无法从知识库恢复。`)) return
    try {
      for (const id of ids) await deleteArtifact(id)
      setNotice(`已删除 ${ids.length} 条知识`)
      setOpened(null)
      setReload((value) => value + 1)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除失败")
      setReload((value) => value + 1)
    }
  }

  async function quickDownload(item: LibraryItem) {
    const file = bodyFile(item.files)
    try {
      await downloadArtifact(item.artifact_id, item.version_id, file?.filename || item.filename, file?.id)
      setNotice(`已下载 ${file?.filename || item.filename}，并通过哈希校验`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "下载失败")
    }
  }

  const openedItem = opened ? items.find((item) => itemKey(item, query) === opened.key) : undefined
  const visibleKeys = items.map((item) => itemKey(item, query))
  const allChecked = visibleKeys.length > 0 && visibleKeys.every((key) => checked.has(key))

  function sortIcon(key: SortKey) {
    if (sort.key !== key) return <Icon name="sort" size={12} />
    return <Icon name={sort.desc ? "sort-down" : "sort-up"} size={12} />
  }

  return (
    <section className="library">
      <div className="lib-head">
        <h1>知识库</h1>
        <Link className="btn-primary" to="/upload">
          <Icon name="upload" />
          上传
        </Link>
      </div>
      {checked.size ? (
        <div className="lib-tools bulk">
          <span>已选择 {checked.size} 条</span>
          <button className="btn" onClick={removeChecked}>
            <Icon name="trash" />
            删除
          </button>
          <button className="btn-text" onClick={() => setChecked(new Set())}>
            取消选择
          </button>
        </div>
      ) : (
        <div className="lib-tools">
          <label className="pill-select">
            <Icon name="filter" size={14} />
            <select value={kind} onChange={(event) => setFilter("kind", event.target.value)} aria-label="格式">
              <option value="">全部类型</option>
              {Object.entries(kindLabel).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <Icon name="chevron-down" size={12} />
          </label>
          <div className="search">
            <Icon name="search" size={14} />
            <input ref={searchBox} value={query} onChange={(event) => setFilter("q", event.target.value)} placeholder="搜索标题、正文或文件名" aria-label="搜索" />
          </div>
          {query ? (
            <label className="pill-select">
              <select value={mode} onChange={(event) => setFilter("mode", event.target.value)} aria-label="检索方式">
                <option value="keyword">全文</option>
                <option value="semantic">语义</option>
                <option value="hybrid">混合</option>
              </select>
              <Icon name="chevron-down" size={12} />
            </label>
          ) : null}
          <label className="pill-select">
            <select value={project} onChange={(event) => setFilter("project", event.target.value)} aria-label="项目">
              <option value="">全部项目</option>
              {projects.map((item) => (
                <option key={item.id}>{item.name}</option>
              ))}
            </select>
            <Icon name="chevron-down" size={12} />
          </label>
          <label className="pill-select">
            <select value={tag} onChange={(event) => setFilter("tag", event.target.value)} aria-label="标签">
              <option value="">全部标签</option>
              {tags.map((item) => (
                <option key={item.id}>{item.name}</option>
              ))}
            </select>
            <Icon name="chevron-down" size={12} />
          </label>
          <label className="pill-select">
            <select value={source} onChange={(event) => setFilter("source", event.target.value)} aria-label="来源">
              <option value="">全部来源</option>
              {agents.map((item) => (
                <option key={item.id}>{item.name}</option>
              ))}
            </select>
            <Icon name="chevron-down" size={12} />
          </label>
          <span className="lib-count">{!ready ? (loading ? "正在读取…" : "") : loading ? "正在更新…" : query ? `${total} 条结果，含历史版本` : `${total} 条知识`}</span>
          {filtered ? (
            <button className="btn-text" onClick={() => setParams({}, { replace: true })}>
              清除筛选
            </button>
          ) : null}
        </div>
      )}
      {error ? <p className="error">{error}</p> : null}
      {notice ? (
        <p className="notice" onClick={() => setNotice("")}>
          {notice}
        </p>
      ) : null}
      <div className="table" role="table" aria-label="知识列表">
        <div className="trow thead" role="row">
          <span className="cell-check">
            {items.length ? (
              <input
                type="checkbox"
                className={allChecked ? "on" : ""}
                checked={allChecked}
                onChange={() => setChecked(allChecked ? new Set() : new Set(visibleKeys))}
                aria-label="全选"
              />
            ) : null}
          </span>
          <button className={sort.key === "title" ? "th sorted" : "th"} onClick={() => sortBy("title")}>
            名称 {sortIcon("title")}
          </button>
          <span className="th">类型</span>
          <span className="th">来源</span>
          <button className={sort.key === "updated" ? "th sorted" : "th"} onClick={() => sortBy("updated")}>
            更新时间 {sortIcon("updated")}
          </button>
          <button className={sort.key === "size" ? "th sorted" : "th"} onClick={() => sortBy("size")}>
            大小 {sortIcon("size")}
          </button>
          <span />
        </div>
        {!ready && loading ? <SkeletonRows /> : null}
        {ready && !loading && items.length === 0 ? (
          <div className="empty">
            {filtered ? (
              <>
                <strong>没有匹配的知识</strong>换个关键词，或清除筛选。
              </>
            ) : (
              <>
                <strong>知识库还是空的</strong>在 Agent 里说「把这份最终稿归档到 AgentShelf。」，或者直接上传文件。
              </>
            )}
          </div>
        ) : null}
        {ready
          ? groups.map(([name, rows]) => {
              const folded = foldedGroups.has(name)
              return (
                <Fragment key={name}>
                  <div className="trow tgroup" role="row" onClick={() => toggle(setFoldedGroups, name)}>
                    <span className={folded ? "caret folded" : "caret"}>
                      <Icon name="chevron-down" size={14} />
                    </span>
                    <span className="group-name">
                      {name}
                      <span className="chip">{rows.length} 条知识</span>
                    </span>
                  </div>
                  {folded
                    ? null
                    : rows.map((item) => {
                        const key = itemKey(item, query)
                        const bundle = item.file_count > 1
                        const itemFolded = foldedItems.has(key)
                        const isOpen = opened?.key === key
                        const kindName = displayKind(item)
                        return (
                          <Fragment key={key}>
                            <div
                              className={["trow", "titem", bundle ? "bundle" : "", checked.has(key) ? "checked" : "", isOpen && !opened?.fileId ? "open" : ""].filter(Boolean).join(" ")}
                              role="row"
                              tabIndex={0}
                              onClick={() => setOpened({ key })}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") setOpened({ key })
                              }}
                            >
                              <span className="cell-check" onClick={(event) => event.stopPropagation()}>
                                <input type="checkbox" checked={checked.has(key)} onChange={() => toggle(setChecked, key)} aria-label={`选择 ${item.title}`} />
                              </span>
                              <span className="cell-name">
                                {bundle ? (
                                  <button
                                    className={itemFolded ? "caret folded" : "caret"}
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      toggle(setFoldedItems, key)
                                    }}
                                    aria-label={itemFolded ? "展开文件" : "收起文件"}
                                  >
                                    <Icon name="chevron-down" size={12} />
                                  </button>
                                ) : null}
                                {bundle ? <BundleIcon /> : <FileIcon kind={kindName} />}
                                <span className="name-text">
                                  <span className="name-line">
                                    <span className="name-title">{item.title}</span>
                                    {!item.is_current ? <span className="badge">v{item.version_number}</span> : null}
                                    {item.tags.map((name) => (
                                      <span className="tag" key={name}>
                                        {name}
                                      </span>
                                    ))}
                                  </span>
                                  {query && item.snippet ? <SnippetText value={item.snippet} /> : null}
                                </span>
                              </span>
                              <span className="cell">{bundle ? `${item.file_count} 个文件` : typeLabel[kindName] || kindLabel[kindName] || "其他"}</span>
                              <span className="cell">{item.source_agent || <span className="faint">—</span>}</span>
                              <span className="cell" title={formatTime(item.updated_at)}>
                                {formatRelative(item.updated_at)}
                              </span>
                              <span className="cell">{formatBytes(item.size_bytes || 0)}</span>
                              <span className="cell-actions" onClick={(event) => event.stopPropagation()}>
                                <button className="tool-btn" onClick={() => quickDownload(item)} title="下载正文" aria-label="下载正文">
                                  <Icon name="download" size={14} />
                                </button>
                                <button className="tool-btn" onClick={() => navigate(detailPath(item))} title="打开详情" aria-label="打开详情">
                                  <Icon name="expand" size={14} />
                                </button>
                              </span>
                            </div>
                            {bundle && !itemFolded
                              ? item.files.map((file) => {
                                  const fileKind = displayKind(file)
                                  const body = bodyFile(item.files)
                                  const isBody = body?.id === file.id
                                  const active = isOpen && (opened?.fileId ? opened.fileId === file.id : isBody)
                                  return (
                                    <div
                                      key={file.id}
                                      className={active && opened?.fileId ? "trow tfile open" : "trow tfile"}
                                      role="row"
                                      tabIndex={0}
                                      onClick={() => setOpened({ key, fileId: isBody ? undefined : file.id })}
                                      onKeyDown={(event) => {
                                        if (event.key === "Enter") setOpened({ key, fileId: isBody ? undefined : file.id })
                                      }}
                                    >
                                      <span />
                                      <span className="cell-name">
                                        <FileIcon kind={fileKind} />
                                        <span className="name-title">{file.filename}</span>
                                        {isBody ? <span className="badge">正文</span> : null}
                                      </span>
                                      <span className="cell">{typeLabel[fileKind] || "其他"}</span>
                                      <span className="cell" />
                                      <span className="cell" />
                                      <span className="cell">{formatBytes(file.size_bytes)}</span>
                                      <span />
                                    </div>
                                  )
                                })
                              : null}
                          </Fragment>
                        )
                      })}
                </Fragment>
              )
            })
          : null}
        {ready && items.length < total ? (
          <div className="table-more">
            <button className="btn" onClick={loadMore}>
              再加载 {Math.min(PAGE, total - items.length)} 条
            </button>
          </div>
        ) : null}
      </div>
      {openedItem ? (
        <PreviewDrawer
          item={openedItem}
          fileId={opened?.fileId}
          onClose={() => setOpened(null)}
          onSelectFile={(fileId) => setOpened({ key: itemKey(openedItem, query), fileId })}
          onExpand={() => navigate(detailPath(openedItem, opened?.fileId))}
        />
      ) : null}
    </section>
  )
}

function SkeletonRows() {
  return (
    <>
      {[0, 1, 2, 3, 4].map((index) => (
        <div className="trow titem" key={index}>
          <span />
          <span className="cell-name">
            <div className="skeleton" style={{ width: 18, height: 18 }} />
            <div className="skeleton" style={{ width: `${40 + index * 8}%` }} />
          </span>
          <div className="skeleton" style={{ width: 40 }} />
          <div className="skeleton" style={{ width: 60 }} />
          <div className="skeleton" style={{ width: 50 }} />
          <div className="skeleton" style={{ width: 40 }} />
          <span />
        </div>
      ))}
    </>
  )
}
