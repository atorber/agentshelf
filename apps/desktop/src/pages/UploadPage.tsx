import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { confirmIngest, uploadFile } from "../api"
import type { IngestResult } from "../types"

interface QueuedFile {
  key: string
  file: File
  title: string
  progress: number
  result?: IngestResult
  error?: string
}

export function UploadPage() {
  const [items, setItems] = useState<QueuedFile[]>([])
  const [over, setOver] = useState(false)
  const [description, setDescription] = useState("")
  const [project, setProject] = useState("")
  const [tags, setTags] = useState("")
  const [source, setSource] = useState("")
  const [running, setRunning] = useState(false)

  function addFiles(files: FileList | File[]) {
    const next = Array.from(files).map((file) => ({
      key: `${file.name}-${file.size}-${file.lastModified}-${Math.random()}`,
      file,
      title: file.name.replace(/\.[^.]+$/, "") || file.name,
      progress: 0,
    }))
    setItems((current) => [...current, ...next])
  }

  const pending = useMemo(() => items.filter((item) => !item.result && !item.error), [items])

  async function start() {
    setRunning(true)
    for (const item of items) {
      if (item.result || item.error) continue
      try {
        const result = await uploadFile(
          item.file,
          {
            title: item.title,
            description,
            project,
            tags,
            source_agent: source,
          },
          (ratio) => {
            setItems((current) => current.map((entry) => (entry.key === item.key ? { ...entry, progress: ratio } : entry)))
          },
        )
        setItems((current) => current.map((entry) => (entry.key === item.key ? { ...entry, progress: 1, result } : entry)))
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : "上传失败"
        setItems((current) => current.map((entry) => (entry.key === item.key ? { ...entry, error: message } : entry)))
      }
    }
    setRunning(false)
  }

  async function choose(item: QueuedFile, decision: "new_artifact" | "new_version", artifactId?: string) {
    if (!item.result?.staging_id) return
    try {
      const result = await confirmIngest({
        staging_id: item.result.staging_id,
        decision,
        artifact_id: artifactId,
        title: item.title,
        description,
        project,
        tags,
        source_agent: source,
        filename: item.file.name,
      })
      setItems((current) => current.map((entry) => (entry.key === item.key ? { ...entry, result, error: undefined } : entry)))
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "确认失败"
      setItems((current) => current.map((entry) => (entry.key === item.key ? { ...entry, error: message } : entry)))
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>上传</h1>
          <p>可以一次放入多个文件。某个文件失败时，已经成功的文件会保留。</p>
        </div>
      </div>
      <div
        className={over ? "drop over" : "drop"}
        onDragOver={(event) => {
          event.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault()
          setOver(false)
          addFiles(event.dataTransfer.files)
        }}
      >
        <strong>拖拽文件到这里</strong>
        <p className="muted">或选择本机文件。上传前可以改名称、描述、项目和标签。</p>
        <label className="btn-primary">
          选择文件
          <input
            type="file"
            multiple
            hidden
            onChange={(event) => {
              if (event.target.files) addFiles(event.target.files)
              event.target.value = ""
            }}
          />
        </label>
      </div>
      <div className="panel stack" style={{ marginTop: 16 }}>
        <div className="filters">
          <label className="field grow">
            <span>描述</span>
            <input value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
          <label className="field">
            <span>项目</span>
            <input value={project} onChange={(event) => setProject(event.target.value)} />
          </label>
          <label className="field">
            <span>标签</span>
            <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="逗号分隔" />
          </label>
          <label className="field">
            <span>来源 Agent</span>
            <input value={source} onChange={(event) => setSource(event.target.value)} placeholder="例如 cursor" />
          </label>
        </div>
        {items.map((item) => (
          <div className="file-row" key={item.key}>
            <label className="field">
              <span>{item.file.name}</span>
              <input
                value={item.title}
                onChange={(event) =>
                  setItems((current) => current.map((entry) => (entry.key === item.key ? { ...entry, title: event.target.value } : entry)))
                }
              />
            </label>
            <div>
              <div className="progress">
                <span style={{ width: `${Math.round(item.progress * 100)}%` }} />
              </div>
              <FileState item={item} onChoose={choose} />
            </div>
            <button className="btn-ghost" onClick={() => setItems((current) => current.filter((entry) => entry.key !== item.key))} disabled={running}>
              移除
            </button>
          </div>
        ))}
        <div className="actions">
          <button className="btn-primary" disabled={running || pending.length === 0} onClick={start}>
            {running ? "正在上传…" : `开始上传 ${pending.length} 个文件`}
          </button>
        </div>
      </div>
    </section>
  )
}

function FileState({
  item,
  onChoose,
}: {
  item: QueuedFile
  onChoose: (item: QueuedFile, decision: "new_artifact" | "new_version", artifactId?: string) => void
}) {
  if (item.error) return <div className="error">{item.error}</div>
  if (!item.result) return <div className="muted">等待上传</div>
  if (item.result.status === "needs_decision") {
    return (
      <div className="notice">
        <div>{item.result.message}</div>
        <div className="choice">
          <button className="btn-ghost" onClick={() => onChoose(item, "new_artifact")}>
            创建新产物
          </button>
        </div>
        {(item.result.candidates || []).map((candidate) => (
          <div className="choice" key={candidate.artifact_id}>
            <span>
              {candidate.title}（v{candidate.versions.join(", ")}）
            </span>
            <button className="btn-ghost" onClick={() => onChoose(item, "new_version", candidate.artifact_id)}>
              追加为新版本
            </button>
          </div>
        ))}
      </div>
    )
  }
  if (item.result.id) {
    return (
      <div>
        {item.result.message || "已归档"}{" "}
        <Link to={`/artifacts/${item.result.id}`}>查看产物</Link>
        {item.result.stored_new_blob === false ? <span className="muted"> · 已复用相同内容</span> : null}
      </div>
    )
  }
  return <div>{item.result.message || item.result.status}</div>
}
