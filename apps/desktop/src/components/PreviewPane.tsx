import { Component, useEffect, useState, type ReactNode } from "react"
import ReactMarkdown from "react-markdown"
import { artifactQuery, fetchVerifiedBlob, preview } from "../api"
import type { Preview } from "../types"

interface Props {
  artifactId: string
  versionId?: string
  fileId?: string
}

export function PreviewPane({ artifactId, versionId, fileId }: Props) {
  return (
    <PreviewBoundary key={`${artifactId}:${versionId || "current"}:${fileId || "first"}`}>
      <PreviewBody artifactId={artifactId} versionId={versionId} fileId={fileId} />
    </PreviewBoundary>
  )
}

function PreviewBody({ artifactId, versionId, fileId }: Props) {
  const [data, setData] = useState<Preview | null>(null)
  const [error, setError] = useState("")
  const [imageUrl, setImageUrl] = useState("")
  const [pdfError, setPdfError] = useState("")

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError("")
    setImageUrl("")
    setPdfError("")
    preview(artifactId, versionId, fileId)
      .then((body) => {
        if (!cancelled) setData(body)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "预览失败")
      })
    return () => {
      cancelled = true
    }
  }, [artifactId, fileId, versionId])

  useEffect(() => {
    if (!data || data.preview_kind !== "image") return
    let url = ""
    let cancelled = false
    fetchVerifiedBlob(`/api/artifacts/${artifactId}/download${artifactQuery(versionId, fileId)}`)
      .then((file) => {
        if (cancelled) return
        if (!file.verified) {
          setError("哈希校验失败，已停止预览")
          return
        }
        url = URL.createObjectURL(file.blob)
        setImageUrl(url)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "图片读取失败")
      })
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [artifactId, data, fileId, versionId])

  if (error) return <div className="preview-frame center error">{error}</div>
  if (!data) return <div className="preview-frame center">正在准备预览…</div>
  if (data.error && data.preview_kind !== "pdf" && data.preview_kind !== "json") {
    return <div className="preview-frame center">{data.error}</div>
  }
  if (data.preview_kind === "markdown") {
    return (
      <div className="preview-frame">
        <div className="markdown">
          <ReactMarkdown>{data.text || ""}</ReactMarkdown>
          {data.truncated ? <p className="muted">内容较长，这里只显示前一部分。</p> : null}
        </div>
      </div>
    )
  }
  if (data.preview_kind === "text") {
    return (
      <div className="preview-frame">
        <pre>{data.text}</pre>
      </div>
    )
  }
  if (data.preview_kind === "csv") {
    return (
      <div className="preview-frame">
        <table>
          <tbody>
            {(data.rows || []).map((row, index) => (
              <tr key={index}>
                {row.map((cell, cellIndex) => (index === 0 ? <th key={cellIndex}>{cell}</th> : <td key={cellIndex}>{cell}</td>))}
              </tr>
            ))}
          </tbody>
        </table>
        {data.truncated ? <p className="muted">只显示前 200 行。</p> : null}
      </div>
    )
  }
  if (data.preview_kind === "json") {
    const pretty = data.json === undefined || data.json === null ? data.text || "" : JSON.stringify(data.json, null, 2)
    return (
      <div className="preview-frame">
        {data.error ? <p className="error">{data.error}</p> : null}
        <pre>{pretty}</pre>
      </div>
    )
  }
  if (data.preview_kind === "image") {
    return <div className="preview-frame">{imageUrl ? <img src={imageUrl} alt={data.filename} style={{ maxWidth: "100%" }} /> : <p className="muted">正在读取图片…</p>}</div>
  }
  if (data.preview_kind === "pdf") {
    return (
      <div className="preview-frame">
        {data.error ? <p className="error">{data.error}</p> : null}
        {typeof data.page_count === "number" ? <p className="muted">共 {data.page_count} 页</p> : null}
        {pdfError ? <p className="error">{pdfError}</p> : <PdfPages artifactId={artifactId} versionId={versionId} fileId={fileId} onError={setPdfError} />}
      </div>
    )
  }
  return <div className="preview-frame center">此格式暂不支持预览，可以用右上角的「下载」取得原始文件。</div>
}

function PdfPages({ artifactId, versionId, fileId, onError }: Props & { onError: (message: string) => void }) {
  const [urls, setUrls] = useState<string[]>([])
  useEffect(() => {
    let cancelled = false
    const created: string[] = []
    ;(async () => {
      try {
        const pdfjs = await import("pdfjs-dist")
        const worker = await import("pdfjs-dist/build/pdf.worker.min.mjs?url")
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default
        const file = await fetchVerifiedBlob(`/api/artifacts/${artifactId}/download${artifactQuery(versionId, fileId)}`)
        if (!file.verified) throw new Error("哈希校验失败")
        const doc = await pdfjs.getDocument({ data: await file.blob.arrayBuffer(), isEvalSupported: false }).promise
        const total = Math.min(doc.numPages, 8)
        for (let pageNumber = 1; pageNumber <= total; pageNumber += 1) {
          const page = await doc.getPage(pageNumber)
          const viewport = page.getViewport({ scale: 1.2 })
          const canvas = document.createElement("canvas")
          canvas.width = viewport.width
          canvas.height = viewport.height
          const context = canvas.getContext("2d")
          if (!context) continue
          await page.render({ canvasContext: context, viewport }).promise
          const url = canvas.toDataURL("image/png")
          created.push(url)
        }
        if (!cancelled) setUrls(created)
      } catch (reason) {
        if (!cancelled) onError(reason instanceof Error ? reason.message : "PDF 预览失败")
      }
    })()
    return () => {
      cancelled = true
    }
  }, [artifactId, fileId, onError, versionId])
  return (
    <div className="stack">
      {urls.map((url) => (
        <img key={url.slice(-24)} src={url} alt="PDF 页面" style={{ width: "100%" }} />
      ))}
    </div>
  )
}

class PreviewBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    if (this.state.failed) return <div className="preview-frame center">预览出错了，原始文件仍可下载。</div>
    return this.props.children
  }
}
