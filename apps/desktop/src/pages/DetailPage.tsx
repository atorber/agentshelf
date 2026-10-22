import { useEffect, useState } from "react"
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { deleteArtifact, downloadArtifact, getArtifact, restoreVersion, updateArtifact, verify } from "../api"
import { Icon } from "../components/Icon"
import { PreviewPane } from "../components/PreviewPane"
import { displayKind, fileSummary, formatBytes, formatTime, kindLabel, libraryPath, sameFile } from "../format"
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
  const location = useLocation()
  const [artifact, setArtifact] = useState<Artifact | null>(null)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [project, setProject] = useState("")
  const [tags, setTags] = useState("")
  const [source, setSource] = useState("")

  const versionId = params.get("version") || undefined
  const fileId = params.get("file") || undefined

  function fillForm(body: Artifact) {
    setTitle(body.title)
    setDescription(body.description)
    setProject(body.project?.name || "")
    setTags(body.tags.join(", "))
    setSource(body.source_agent?.name || "")
  }

  function load(nextId = id) {
    return getArtifact(nextId)
      .then((body) => {
        setArtifact(body)
        fillForm(body)
        setError("")
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "读取失败"))
  }

  useEffect(() => {
    setArtifact(null)
    setError("")
    setNotice("")
    setEditing(false)
    load()
  }, [id])

  const selected = artifact?.versions.find((item) => item.id === versionId) || artifact?.current_version
  const files = selected ? listedFiles(selected) : []
  const body = files.find((file) => displayKind(file) === "markdown") || files[0]
  const sidecars = body ? files.filter((file) => !sameFile(file, body)) : []
  const opened = files.find((file) => file.id && file.id === fileId)
  const shown = opened || body
  const inSidecar = Boolean(shown && body && !sameFile(shown, body))

  function versionParams() {
    const next = new URLSearchParams()
    if (versionId) next.set("version", versionId)
    return next
  }

  function openSidecar(file: ArtifactFile) {
    if (body && sameFile(file, body)) {
      backToDocument()
      return
    }
    const next = versionParams()
    if (file.id) next.set("file", file.id)
    if (inSidecar) setParams(next, { replace: true, state: location.state })
    else setParams(next, { state: { fromDocument: true } })
  }

  function backToDocument() {
    if ((location.state as { fromDocument?: boolean } | null)?.fromDocument) navigate(-1)
    else setParams(versionParams(), { replace: true })
  }

  function goUp() {
    if (inSidecar) backToDocument()
    else navigate(libraryPath())
  }

  async function save() {
    try {
      const body = await updateArtifact(id, { title, description, project, tags, source_agent: source })
      setArtifact(body)
      fillForm(body)
      setEditing(false)
      setNotice("已保存")
      setError("")
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
    try {
      await deleteArtifact(id)
      navigate(libraryPath())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除失败")
    }
  }

  if (error && !artifact) {
    return (
      <section className="page">
        <div className="crumbs">
          <Link to={libraryPath()}>产物库</Link>
        </div>
        <p className="error">{error}</p>
      </section>
    )
  }
  if (!artifact || !selected) {
    return (
      <section className="page">
        <div className="crumbs">
          <Link to={libraryPath()}>产物库</Link>
        </div>
        <div className="panel empty">正在读取产物…</div>
      </section>
    )
  }

  const isOld = !selected.is_current
  const extractTarget = shown || selected

  return (
    <section className="page">
      <div className="stack" style={{ gap: 6 }}>
        <nav className="crumbs" aria-label="位置">
          <Link to={libraryPath()}>产物库</Link>
          <span className="sep">/</span>
          {inSidecar ? (
            <button onClick={backToDocument}>{artifact.title}</button>
          ) : (
            <span className={isOld ? "" : "here"}>{artifact.title}</span>
          )}
          {isOld ? (
            <>
              <span className="sep">/</span>
              <span className={inSidecar ? "" : "here"}>v{selected.version_number}</span>
            </>
          ) : null}
          {inSidecar && shown ? (
            <>
              <span className="sep">/</span>
              <span className="here">{shown.filename}</span>
            </>
          ) : null}
        </nav>
        <div className="page-head">
          <div className="title-row">
            <button className="btn-ghost icon-btn" onClick={goUp} title={inSidecar ? "返回正文" : "返回产物库"} aria-label={inSidecar ? "返回正文" : "返回产物库"}>
              <Icon name="back" />
            </button>
            <h1>{artifact.title}</h1>
            {isOld ? <span className="badge">历史版本 v{selected.version_number}</span> : null}
          </div>
          <div className="actions">
            {shown ? (
              <>
                <button className="btn" onClick={check}>
                  <Icon name="check" />
                  校验
                </button>
                <button className="btn" onClick={download}>
                  <Icon name="download" />
                  下载
                </button>
              </>
            ) : null}
          </div>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {notice ? <p className="notice">{notice}</p> : null}
      <div className="detail">
        <div className="panel viewer">
          {inSidecar ? (
            <div className="panel-head">
              <button className="btn-text" onClick={backToDocument}>
                返回正文
              </button>
              <span className="muted small">{shown?.filename}</span>
            </div>
          ) : null}
          <PreviewPane artifactId={id} versionId={selected.id} fileId={shown?.id || undefined} assets={files} embedAssets={!inSidecar} onOpenAsset={openSidecar} />
          {shown ? (
            <div className="viewer-foot">
              <span className="muted small">
                {kindLabel[displayKind(shown)] || displayKind(shown)} · {shown.filename} · {formatBytes(shown.size_bytes)}
              </span>
              <span className="hash" title="SHA-256">
                {shown.sha256.slice(0, 16)}…
              </span>
            </div>
          ) : null}
          {extractTarget.extract_status === "pending" ? <div className="viewer-foot muted small">正在建立索引…</div> : null}
          {extractTarget.extract_error ? <div className="viewer-foot error small">{extractTarget.extract_error}</div> : null}
        </div>
        <aside>
          {sidecars.length ? (
            <div className="panel">
              <div className="panel-head">
                <h2>附件</h2>
                <span className="muted small">{sidecars.length}</span>
              </div>
              <div className="files attach">
                {sidecars.map((file) => {
                  const kind = displayKind(file)
                  const active = shown ? sameFile(file, shown) : false
                  return (
                    <button className={active ? "item active" : "item"} key={file.id || file.sha256} onClick={() => openSidecar(file)}>
                      <span className={`kind kind-${kind}`}>{kindLabel[kind] || kind}</span>
                      <span className="item-title">
                        <span>{file.filename}</span>
                        <span className="item-sub">{formatBytes(file.size_bytes)}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          ) : null}
          <div className="panel">
            <div className="panel-head">
              <h2>信息</h2>
              {editing ? null : (
                <button className="btn-text" onClick={() => setEditing(true)}>
                  编辑
                </button>
              )}
            </div>
            <div className="panel-body">
              {editing ? (
                <>
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
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <button
                      className="btn-ghost"
                      onClick={() => {
                        fillForm(artifact)
                        setEditing(false)
                      }}
                    >
                      取消
                    </button>
                    <button className="btn-primary" onClick={save} disabled={!title.trim()}>
                      保存
                    </button>
                  </div>
                </>
              ) : (
                <dl className="props">
                  <dt>项目</dt>
                  <dd>{artifact.project?.name || <span className="faint">未分组</span>}</dd>
                  <dt>标签</dt>
                  <dd>
                    {artifact.tags.length ? (
                      <span className="tags">
                        {artifact.tags.map((name) => (
                          <span className="tag" key={name}>
                            {name}
                          </span>
                        ))}
                      </span>
                    ) : (
                      <span className="faint">无</span>
                    )}
                  </dd>
                  <dt>来源</dt>
                  <dd>{artifact.source_agent?.name || <span className="faint">未知</span>}</dd>
                  <dt>文件</dt>
                  <dd>{fileSummary(files.length, files[0]?.filename || "")}</dd>
                  <dt>更新</dt>
                  <dd>{formatTime(artifact.updated_at)}</dd>
                  {artifact.description ? (
                    <>
                      <dt>描述</dt>
                      <dd>{artifact.description}</dd>
                    </>
                  ) : null}
                </dl>
              )}
            </div>
          </div>
          <div className="panel">
            <div className="panel-head">
              <h2>版本</h2>
              <span className="muted small">{artifact.versions.length}</span>
            </div>
            <div className="versions">
              {artifact.versions.map((version) => (
                <div
                  className={version.id === selected.id ? "version active" : "version"}
                  key={version.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setParams(version.is_current ? {} : { version: version.id })}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") setParams(version.is_current ? {} : { version: version.id })
                  }}
                >
                  <div className="grow">
                    <div className="version-title">
                      v{version.version_number}
                      {version.is_current ? <span className="badge current">当前</span> : null}
                    </div>
                    <div className="muted small item-sub">
                      {formatTime(version.created_at)} · {fileSummary(version.file_count || version.files?.length || 1, version.filename)}
                      {version.note ? ` · ${version.note}` : ""}
                    </div>
                  </div>
                  {artifact.current_version && fileSignature(version) !== fileSignature(artifact.current_version) ? (
                    <button
                      className="btn-text"
                      onClick={(event) => {
                        event.stopPropagation()
                        restore(version.id)
                      }}
                    >
                      恢复
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
          <button className="btn-text danger" onClick={remove} style={{ alignSelf: "flex-start" }}>
            删除产物
          </button>
        </aside>
      </div>
    </section>
  )
}
