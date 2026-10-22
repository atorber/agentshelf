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

export const kindLabel: Record<string, string> = {
  markdown: "Markdown",
  text: "文本",
  csv: "CSV",
  json: "JSON",
  image: "图片",
  pdf: "PDF",
  unsupported: "其他",
}
