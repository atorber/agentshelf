import { useEffect, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { deleteArtifact, downloadArtifact, getArtifact, restoreVersion, updateArtifact, verify } from "../api"
import { PreviewPane } from "../components/PreviewPane"
import { formatBytes, formatTime, kindLabel } from "../format"
import type { Artifact, ArtifactFile, Version } from "../types"

function listedFiles(version: Version): ArtifactFile[] {
  if (version.files?.length) return version.files
  return [
    {
      id: "",
      filename: version.filename,
      mime_type: version.mime_type,
      size_bytes: version.size_bytes,
      sha256: version.sha256,
      preview_kind: version.preview_kind,
      extract_status: version.extract_status,
      extract_error: version.extract_error,
    },
  ]
}

function fileSignature(version: Version) {
  return listedFiles(version)
    .map((file) => file.sha256)
    .sort()
    .join("\n")
}

export function DetailPage() {
  const { id = "" } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [artifact, setArtifact] = useState<Artifact | null>(null)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [project, setProject] = useState("")
  const [tags, setTags] = useState("")
  const [source, setSource] = useState("")

  const versionId = params.get("version") || undefined
  const fileId = params.get("file") || undefined

  function load(nextId = id) {
    return getArtifact(nextId)
      .then((body) => {
        setArtifact(body)
        setTitle(body.title)
        setDescription(body.description)
        setProject(body.project?.name || "")
        setTags(body.tags.join(", "))
        setSource(body.source_agent?.name || "")
        setError("")
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "读取失败"))
  }

  useEffect(() => {
    setArtifact(null)
    setError("")
    setNotice("")
    load()
  }, [id])

  const selected = artifact?.versions.find((item) => item.id === versionId) || artifact?.current_version
  const files = selected ? listedFiles(selected) : []
  const opened = files.find((file) => file.id && file.id === fileId)
  const showList = files.length > 1 && !opened
  const shown = opened || (files.length === 1 ? files[0] : undefined)

  async function save() {
    try {
      const body = await updateArtifact(id, { title, description, project, tags, source_agent: source })
      setArtifact(body)
      setNotice("已保存")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败")
    }
  }

  async function restore(target: string) {
    setNotice("")
    try {
      const body = await restoreVersion(id, target)
      setArtifact(body)
      setParams({})
      setNotice(body.message || "已恢复为新版本")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "恢复失败")
    }
  }

  function openFile(file: ArtifactFile) {
    const next = new URLSearchParams()
    if (versionId) next.set("version", versionId)
    if (file.id) next.set("file", file.id)
    setParams(next)
  }

  function backToFiles() {
    const next = new URLSearchParams()
    if (versionId) next.set("version", versionId)
    setParams(next)
  }

  async function download() {
    if (!selected || !shown) return
    try {
      await downloadArtifact(id, selected.id, shown.filename, shown.id || undefined)
      setNotice("已下载，并通过哈希校验")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "下载失败")
    }
  }

  async function check() {
    try {
      const result = await verify(id, selected?.id, shown?.id || undefined)
      setNotice(result.ok ? "文件与记录的 SHA-256 一致" : "文件内容与记录不一致")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "校验失败")
    }
  }

  async function remove() {
    if (!window.confirm("删除后无法从产物库恢复，确定删除？")) return
    await deleteArtifact(id)
    navigate("/")
  }

  if (error && !artifact) return <p className="error">{error}</p>
  if (!artifact || !selected) return <p className="muted">正在读取产物…</p>

  return (
    <section>
      <div className="page-head">
        <div>
          <Link to="/">返回产物库</Link>
          <h1>{artifact.title}</h1>
          <p>
            {showList || !shown
              ? `${files.length} 个文件`
              : `${kindLabel[shown.preview_kind] || shown.preview_kind} · ${shown.filename} · ${formatBytes(shown.size_bytes)}`}
          </p>
        </div>
        <div className="actions">
          {shown ? (
            <>
              <button className="btn-ghost" onClick={download}>
                下载
              </button>
              <button className="btn-ghost" onClick={check}>
                校验
              </button>
            </>
          ) : null}
          <button className="btn-danger" onClick={remove}>
            删除
          </button>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {notice ? <p className="notice">{notice}</p> : null}
      <div className="detail">
        {showList ? (
          <div className="panel">
            <strong>文件</strong>
            {files.map((file) => (
              <div className="version" key={file.id || file.sha256}>
                <div>
                  <button className="btn-ghost" onClick={() => openFile(file)}>
                    {file.filename}
                  </button>
                  <div className="muted">
                    {kindLabel[file.preview_kind] || file.preview_kind} · {formatBytes(file.size_bytes)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="stack">
            {files.length > 1 ? (
              <button className="btn-ghost" onClick={backToFiles}>
                返回文件列表
              </button>
            ) : null}
            <PreviewPane artifactId={id} versionId={selected.id} fileId={shown?.id || undefined} />
          </div>
        )}
        <div className="stack">
          <div className="panel stack">
            <label className="field">
              <span>名称</span>
              <input value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label className="field">
              <span>描述</span>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <label className="field">
              <span>项目</span>
              <input value={project} onChange={(event) => setProject(event.target.value)} />
            </label>
            <label className="field">
              <span>标签</span>
              <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="用逗号分隔" />
            </label>
            <label className="field">
              <span>来源 Agent</span>
              <input value={source} onChange={(event) => setSource(event.target.value)} />
            </label>
            <button className="btn-primary" onClick={save}>
              保存信息
            </button>
            {shown ? <div className="hash">SHA-256 {shown.sha256}</div> : <div className="muted">打开文件后可以下载和校验。</div>}
            {(shown || selected).extract_status === "pending" ? <div className="muted">正在建立索引…</div> : null}
            {(shown || selected).extract_error ? <div className="error">{(shown || selected).extract_error}</div> : null}
          </div>
          <div className="panel">
            <strong>版本</strong>
            {artifact.versions.map((version) => (
              <div className="version" key={version.id}>
                <div>
                  <button className="btn-ghost" onClick={() => setParams(version.is_current ? {} : { version: version.id })}>
                    v{version.version_number} {version.is_current ? "当前" : ""}
                  </button>
                  <div className="muted">
                    {formatTime(version.created_at)} · {(version.file_count || version.files?.length || 1) > 1 ? `${version.file_count || version.files.length} 个文件` : version.filename}
                    {version.note ? ` · ${version.note}` : ""}
                  </div>
                </div>
                {artifact.current_version && fileSignature(version) !== fileSignature(artifact.current_version) ? (
                  <button className="btn-ghost" onClick={() => restore(version.id)}>
                    恢复
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
