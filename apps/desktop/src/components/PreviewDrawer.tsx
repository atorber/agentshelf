import { useEffect, useState } from "react"
import { downloadArtifact, verify } from "../api"
import { bodyFile, displayKind, formatBytes, kindLabel } from "../format"
import type { ArtifactFile, LibraryFile, LibraryItem } from "../types"
import { FileIcon } from "./FileIcon"
import { Icon } from "./Icon"
import { PreviewPane } from "./PreviewPane"

export function asArtifactFiles(files: LibraryFile[]): ArtifactFile[] {
  return files.map((file) => ({ ...file, extract_status: "", extract_error: "" }))
}

interface Props {
  item: LibraryItem
  fileId?: string
  onClose: () => void
  onSelectFile: (fileId: string | undefined) => void
  onExpand: () => void
}

export function PreviewDrawer({ item, fileId, onClose, onSelectFile, onExpand }: Props) {
  const files = asArtifactFiles(item.files)
  const body = bodyFile(files)
  const shown = files.find((file) => file.id === fileId) || body
  const inSidecar = Boolean(shown && body && shown.id !== body.id)
  const [notice, setNotice] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    setNotice("")
    setError("")
  }, [item.version_id, fileId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  async function check() {
    try {
      const result = await verify(item.artifact_id, item.version_id, shown?.id || undefined)
      setNotice(result.ok ? "文件与记录的 SHA-256 一致" : "文件内容与记录不一致")
      setError("")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "校验失败")
    }
  }

  async function download() {
    if (!shown) return
    try {
      await downloadArtifact(item.artifact_id, item.version_id, shown.filename, shown.id || undefined)
      setNotice("已下载，并通过哈希校验")
      setError("")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "下载失败")
    }
  }

  function openAsset(file: ArtifactFile) {
    onSelectFile(body && file.id === body.id ? undefined : file.id)
  }

  const kind = shown ? displayKind(shown) : item.preview_kind

  return (
    <div className="drawer-layer">
      <div className="drawer-mask" onClick={onClose} />
      <section className="drawer" role="dialog" aria-label={shown?.filename || item.title}>
        <header className="drawer-head">
          {inSidecar ? (
            <button className="tool-btn" onClick={() => onSelectFile(undefined)} title="返回正文" aria-label="返回正文">
              <Icon name="back" />
            </button>
          ) : null}
          <FileIcon kind={kind} />
          <div className="drawer-title">
            <strong>{shown?.filename || item.title}</strong>
            {item.file_count > 1 || shown?.filename !== item.title ? <span>{item.title}</span> : null}
          </div>
          <div className="drawer-tools">
            <button className="tool-btn" onClick={check} title="校验" aria-label="校验">
              <Icon name="check" />
            </button>
            <button className="tool-btn" onClick={download} title="下载" aria-label="下载">
              <Icon name="download" />
            </button>
            <button className="tool-btn" onClick={onExpand} title="打开详情" aria-label="打开详情">
              <Icon name="expand" />
            </button>
            <button className="tool-btn" onClick={onClose} title="关闭" aria-label="关闭">
              <Icon name="close" />
            </button>
          </div>
        </header>
        {notice ? <p className="drawer-note">{notice}</p> : null}
        {error ? <p className="drawer-note error">{error}</p> : null}
        <div className="drawer-body">
          <PreviewPane artifactId={item.artifact_id} versionId={item.version_id} fileId={shown?.id || undefined} assets={files} embedAssets={!inSidecar} onOpenAsset={openAsset} />
        </div>
        {shown ? (
          <footer className="drawer-foot">
            <span>
              {kindLabel[kind] || kind} · {formatBytes(shown.size_bytes)}
            </span>
            <span className="hash" title="SHA-256">
              {shown.sha256.slice(0, 16)}…
            </span>
          </footer>
        ) : null}
      </section>
    </div>
  )
}
