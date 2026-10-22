import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { listArtifacts } from "../api"
import { bodyFile, displayKind, libraryPath } from "../format"
import type { LibraryItem } from "../types"
import { BundleIcon, FileIcon } from "./FileIcon"
import { Icon } from "./Icon"

const UNGROUPED = "未分组"
const RECENT = 5

interface Props {
  activeId: string
  activeFileId?: string
  refreshKey?: string
}

export function KnowledgeTree({ activeId, activeFileId, refreshKey }: Props) {
  const navigate = useNavigate()
  const [items, setItems] = useState<LibraryItem[]>([])
  const [folded, setFolded] = useState<Set<string>>(new Set())
  const [opened, setOpened] = useState<Set<string>>(new Set())

  useEffect(() => {
    listArtifacts({ limit: "200" })
      .then((body) => setItems(body.items))
      .catch(() => setItems([]))
  }, [refreshKey])

  useEffect(() => {
    setOpened((current) => (current.has(activeId) ? current : new Set(current).add(activeId)))
  }, [activeId])

  const sections = useMemo(() => {
    const map = new Map<string, LibraryItem[]>()
    for (const item of items) {
      const name = item.project || UNGROUPED
      map.set(name, [...(map.get(name) || []), item])
    }
    return [...map.entries()].sort(([left], [right]) => {
      if (left === UNGROUPED) return 1
      if (right === UNGROUPED) return -1
      return left.localeCompare(right, "zh-CN")
    })
  }, [items])

  function flip(setter: typeof setFolded, key: string) {
    setter((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function renderItem(item: LibraryItem, scope: string) {
    const bundle = item.file_count > 1
    const isActive = item.artifact_id === activeId
    const expanded = bundle && opened.has(item.artifact_id)
    const body = bodyFile(item.files)
    return (
      <div key={`${scope}:${item.artifact_id}`}>
        <div className={isActive && !expanded ? "tree-row active" : "tree-row"} style={{ paddingLeft: 8 }}>
          {bundle ? (
            <button className={expanded ? "caret" : "caret folded"} onClick={() => flip(setOpened, item.artifact_id)} aria-label={expanded ? "收起文件" : "展开文件"}>
              <Icon name="chevron-down" size={12} />
            </button>
          ) : (
            <span className="caret-space" />
          )}
          <Link to={`/artifacts/${item.artifact_id}`} className="tree-link" title={item.title}>
            {bundle ? <BundleIcon size={16} /> : <FileIcon kind={displayKind(item)} size={16} />}
            <span className="tree-name">{item.title}</span>
          </Link>
        </div>
        {expanded
          ? item.files.map((file) => {
              const isBody = body?.id === file.id
              const active = isActive && (activeFileId ? activeFileId === file.id : isBody)
              return (
                <div key={file.id} className={active ? "tree-row active" : "tree-row"} style={{ paddingLeft: 30 }}>
                  <Link to={isBody ? `/artifacts/${item.artifact_id}` : `/artifacts/${item.artifact_id}?file=${file.id}`} className="tree-link" title={file.filename}>
                    <FileIcon kind={displayKind(file)} size={16} />
                    <span className="tree-name">{file.filename}</span>
                  </Link>
                </div>
              )
            })
          : null}
      </div>
    )
  }

  const recent = [...items].sort((left, right) => right.updated_at.localeCompare(left.updated_at)).slice(0, RECENT)

  return (
    <aside className="tree-panel">
      <div className="tree-head">
        <strong>知识库</strong>
        <Link className="tool-btn" to="/upload" title="上传" aria-label="上传">
          <Icon name="plus" />
        </Link>
      </div>
      <nav className="tree-quick">
        <button onClick={() => navigate(libraryPath(), { state: { focusSearch: true } })}>
          <Icon name="search" />
          搜索
        </button>
        <button onClick={() => navigate("/")}>
          <Icon name="stack" />
          全部知识
        </button>
      </nav>
      <div className="tree-scroll">
        {recent.length ? (
          <div className="tree-section">
            <button className="tree-label" onClick={() => flip(setFolded, "__recent")}>
              <Icon name="clock" size={13} />
              最近更新
              <span className={folded.has("__recent") ? "caret folded" : "caret"}>
                <Icon name="chevron-down" size={12} />
              </span>
            </button>
            {folded.has("__recent") ? null : recent.map((item) => renderItem(item, "recent"))}
          </div>
        ) : null}
        {sections.map(([name, rows]) => (
          <div className="tree-section" key={name}>
            <button className="tree-label" onClick={() => flip(setFolded, name)}>
              <Icon name="library" size={13} />
              <span className="tree-name">{name}</span>
              <span className="tree-count">{rows.length}</span>
              <span className={folded.has(name) ? "caret folded" : "caret"}>
                <Icon name="chevron-down" size={12} />
              </span>
            </button>
            {folded.has(name) ? null : rows.map((item) => renderItem(item, name))}
          </div>
        ))}
      </div>
    </aside>
  )
}
