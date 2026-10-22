import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { confirmIngest, uploadFiles } from "../api"
import { formatBytes } from "../format"
import type { IngestResult } from "../types"

export function UploadPage() {
  const [files, setFiles] = useState<File[]>([])
  const [over, setOver] = useState(false)
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [project, setProject] = useState("")
  const [tags, setTags] = useState("")
  const [source, setSource] = useState("")
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<IngestResult | null>(null)
  const [error, setError] = useState("")

  function addFiles(incoming: FileList | File[]) {
    const next = Array.from(incoming)
    if (next.length === 0) return
    setFiles((current) => [...current, ...next])
    setResult(null)
    setError("")
    setProgress(0)
    setTitle((current) => current || (next.length === 1 ? next[0].name.replace(/\.[^.]+$/, "") || next[0].name : ""))
  }

  const pending = useMemo(() => files.length > 0 && !result, [files.length, result])

  async function start() {
    setRunning(true)
    setError("")
    try {
      const body = await uploadFiles(
        files,
        {
          title: title || (files.length === 1 ? files[0].name.replace(/\.[^.]+$/, "") || files[0].name : ""),
          description,
          project,
          tags,
          source_agent: source,
        },
        setProgress,
      )
      setResult(body)
      setProgress(1)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "上传失败")
    }
    setRunning(false)
  }

  async function choose(decision: "new_artifact" | "new_version", artifactId?: string) {
    if (!result?.staging_id) return
    try {
      const body = await confirmIngest({
        staging_id: result.staging_id,
        decision,
        artifact_id: artifactId,
        title,
        description,
        project,
        tags,
        source_agent: source,
        filename: files[0]?.name,
      })
      setResult(body)
      setError("")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "确认失败")
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>上传</h1>
          <p>一次放入的文件会归档为同一份产物。只有一个文件时，打开详情会直接预览。</p>
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
        <p className="muted">或选择本机文件。多个文件属于同一份最终成果时，一起放进来。</p>
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
            <span>名称</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={files.length > 1 ? "这一组文件的名称" : "默认使用文件名"} />
          </label>
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
        {files.map((file, index) => (
          <div className="file-row" key={`${file.name}-${file.size}-${file.lastModified}-${index}`}>
            <div>
              <strong>{file.name}</strong>
              <div className="muted">{formatBytes(file.size)}</div>
            </div>
            <button
              className="btn-ghost"
              disabled={running}
              onClick={() => {
                setFiles((current) => current.filter((_, item) => item !== index))
                setResult(null)
                setError("")
              }}
            >
              移除
            </button>
          </div>
        ))}
        {files.length > 0 ? (
          <div className="progress">
            <span style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
        ) : null}
        {error ? <div className="error">{error}</div> : null}
        <BundleState result={result} onChoose={choose} />
        <div className="actions">
          <button className="btn-primary" disabled={running || !pending} onClick={start}>
            {running ? "正在上传…" : files.length > 1 ? `归档为同一份产物（${files.length} 个文件）` : "开始上传"}
          </button>
        </div>
      </div>
    </section>
  )
}

function BundleState({
  result,
  onChoose,
}: {
  result: IngestResult | null
  onChoose: (decision: "new_artifact" | "new_version", artifactId?: string) => void
}) {
  if (!result) return null
  if (result.status === "needs_decision") {
    return (
      <div className="notice">
        <div>{result.message}</div>
        <div className="choice">
          <button className="btn-ghost" onClick={() => onChoose("new_artifact")}>
            创建新产物
          </button>
        </div>
        {(result.candidates || []).map((candidate) => (
          <div className="choice" key={candidate.artifact_id}>
            <span>
              {candidate.title}（v{candidate.versions.join(", ")}）
            </span>
            <button className="btn-ghost" onClick={() => onChoose("new_version", candidate.artifact_id)}>
              追加为新版本
            </button>
          </div>
        ))}
      </div>
    )
  }
  if (result.id) {
    const count = result.current_version?.file_count || 0
    return (
      <div>
        {result.message || "已归档"}{" "}
        <Link to={`/artifacts/${result.id}`}>查看产物</Link>
        {count > 1 ? <span className="muted"> · {count} 个文件</span> : null}
        {result.stored_new_blob === false ? <span className="muted"> · 已复用相同内容</span> : null}
      </div>
    )
  }
  return <div>{result.message || result.status}</div>
}
