export function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0 B"
  const units = ["B", "KB", "MB", "GB"]
  let size = value
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`
}

export function formatTime(value?: string): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date)
}

const LIBRARY_KEY = "agentshelf.library.search"

export function rememberLibrary(search: string) {
  try {
    window.sessionStorage.setItem(LIBRARY_KEY, search)
  } catch {
    return
  }
}

export function libraryPath(): string {
  try {
    return `/${window.sessionStorage.getItem(LIBRARY_KEY) || ""}`
  } catch {
    return "/"
  }
}

export function fileSummary(count: number, filename: string): string {
  return count > 1 ? `${count} 个文件` : filename
}

const VIDEO_EXT = ["mp4", "webm", "mov", "m4v", "ogv"]

export function fileExtension(filename: string): string {
  const base = filename.split(/[/\\]/).pop() || filename
  const dot = base.lastIndexOf(".")
  return dot >= 0 ? base.slice(dot + 1).toLowerCase() : ""
}

export function displayKind(file: { filename: string; preview_kind?: string }): string {
  const kind = file.preview_kind || ""
  if (kind && kind !== "unsupported") return kind
  if (VIDEO_EXT.includes(fileExtension(file.filename))) return "video"
  return kind || "unsupported"
}

export function sameFile(left: { id?: string; filename: string; sha256: string }, right: { id?: string; filename: string; sha256: string }) {
  if (left.id && right.id) return left.id === right.id
  return left.filename === right.filename && left.sha256 === right.sha256
}

export const kindLabel: Record<string, string> = {
  markdown: "Markdown",
  text: "文本",
  csv: "CSV",
  json: "JSON",
  image: "图片",
  video: "视频",
  pdf: "PDF",
  unsupported: "其他",
}
