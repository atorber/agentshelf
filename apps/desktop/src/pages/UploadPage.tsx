import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { confirmIngest, uploadFiles } from "../api"
import { Icon } from "../components/Icon"
import { formatBytes } from "../format"
import type { IngestResult } from "../types"

function stem(name: string) {
  return name.replace(/\.[^.]+$/, "") || name
}

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
    if (result?.id) reset()
    setFiles((current) => [...(result?.id ? [] : current), ...next])
    setResult(null)
    setError("")
    setProgress(0)
    setTitle((current) => current || (next.length === 1 ? stem(next[0].name) : ""))
  }

  function reset() {
    setFiles([])
    setTitle("")
    setDescription("")
    setProject("")
    setTags("")
    setSource("")
    setProgress(0)
  }

  const pending = useMemo(() => files.length > 0 && !result, [files.length, result])
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0)

  async function start() {
    setRunning(true)
    setError("")
    try {
      const body = await uploadFiles(
        files,
        {
          title: title || (files.length === 1 ? stem(files[0].name) : ""),
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
    <section className="page narrow">
      <div className="page-head">
        <div>
          <h1>上传</h1>
          <p>一次放入的文件归档为同一份产物。</p>
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
        <span className="muted">
          <Icon name="upload" size={22} />
        </span>
        <strong>拖拽文件到这里</strong>
        <p className="muted small">同一份成果的多个文件请一起放入</p>
        <label className="btn">
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

      {files.length > 0 ? (
        <>
          <div className="panel">
            <div className="panel-head">
              <h2>文件</h2>
              <span className="muted small">
                {files.length} 个 · {formatBytes(totalBytes)}
              </span>
            </div>
            <div>
              {files.map((file, index) => (
                <div className="file-row" key={`${file.name}-${file.size}-${file.lastModified}-${index}`}>
                  <span className="item-title">
                    <span>{file.name}</span>
                  </span>
                  <span className="muted small" style={{ textAlign: "right" }}>
                    {formatBytes(file.size)}
                  </span>
                  <button
                    className="btn-text danger"
                    disabled={running || Boolean(result?.id)}
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
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>信息</h2>
              <span className="muted small">都可以留空，稍后在详情页修改</span>
            </div>
            <div className="panel-body">
              <div className="form-grid">
                <label className="field span">
                  <span>名称</span>
                  <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={files.length > 1 ? "这一组文件的名称" : "默认使用文件名"} />
                </label>
                <label className="field span">
                  <span>描述</span>
                  <input value={description} onChange={(event) => setDescription(event.target.value)} />
                </label>
                <label className="field">
                  <span>项目</span>
                  <input value={project} onChange={(event) => setProject(event.target.value)} />
                </label>
                <label className="field">
                  <span>来源 Agent</span>
                  <input value={source} onChange={(event) => setSource(event.target.value)} placeholder="例如 cursor" />
                </label>
                <label className="field span">
                  <span>标签</span>
                  <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="用逗号分隔" />
                </label>
              </div>
            </div>
          </div>

          {error ? <p className="error">{error}</p> : null}
          <BundleState result={result} onChoose={choose} />
          <div className="row" style={{ justifyContent: "flex-end" }}>
            {running || progress > 0 ? (
              <div className="progress grow" style={{ maxWidth: 240 }}>
                <span style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
            ) : null}
            {result?.id ? (
              <button className="btn" onClick={reset}>
                继续上传
              </button>
            ) : null}
            <button className="btn-primary" disabled={running || !pending} onClick={start}>
              {running ? "正在上传…" : files.length > 1 ? `归档 ${files.length} 个文件` : "归档"}
            </button>
          </div>
        </>
      ) : null}
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
      <div className="notice warn">
        <div>{result.message}</div>
        <div className="choice">
          <span>作为一份独立的新产物保存</span>
          <button className="btn" onClick={() => onChoose("new_artifact")}>
            创建新产物
          </button>
        </div>
        {(result.candidates || []).map((candidate) => (
          <div className="choice" key={candidate.artifact_id}>
            <span>
              {candidate.title}（v{candidate.versions.join(", ")}）
            </span>
            <button className="btn" onClick={() => onChoose("new_version", candidate.artifact_id)}>
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
      <div className="notice">
        {result.message || "已归档"}
        {count > 1 ? ` · ${count} 个文件` : ""}
        {result.stored_new_blob === false ? " · 已复用相同内容" : ""} · <Link to={`/artifacts/${result.id}`}>查看产物</Link>
      </div>
    )
  }
  return <div className="notice">{result.message || result.status}</div>
}
