import { displayKind } from "./format"
import type { ArtifactFile } from "./types"

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function stemOf(filename: string) {
  return filename.replace(/\.[^.]+$/, "")
}

function alreadyPlaced(markdown: string, filename: string) {
  return new RegExp(`\\]\\([^)\\n]*${escapeRegExp(filename)}\\)`, "i").test(markdown)
}

function tokensOf(filename: string) {
  const parts = stemOf(filename).match(/[0-9A-Za-z]{4,}|[\u4e00-\u9fff]{2,}/g) || []
  return [...new Set(parts.map((part) => part.toLowerCase()))]
}

function blockEnd(lines: string[], index: number) {
  const trimmed = lines[index].trim()
  let end = index
  if (trimmed.startsWith("|")) {
    while (end + 1 < lines.length && lines[end + 1].trim().startsWith("|")) end += 1
    return end
  }
  if (trimmed.startsWith(">")) {
    while (end + 1 < lines.length && lines[end + 1].trim().startsWith(">")) end += 1
    return end
  }
  while (end + 1 < lines.length) {
    const next = lines[end + 1].trim()
    if (!next || next.startsWith("#") || next.startsWith("|") || next.startsWith("```") || next.startsWith(">")) break
    end += 1
  }
  return end
}

function mentionEnd(lines: string[], filename: string) {
  const needles = [filename.toLowerCase()]
  const stem = stemOf(filename).toLowerCase()
  if (stem.length >= 4 && stem !== filename.toLowerCase()) needles.push(stem)
  let inCode = false
  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = lines[index].trim()
    if (trimmed.startsWith("```")) {
      inCode = !inCode
      continue
    }
    if (inCode) continue
    const lower = lines[index].toLowerCase()
    if (needles.some((needle) => lower.includes(needle))) return blockEnd(lines, index)
  }
  return -1
}

function sectionInsertAt(lines: string[], filename: string) {
  const tokens = tokensOf(filename)
  if (!tokens.length) return -1
  const headings: Array<{ index: number; level: number }> = []
  for (let index = 0; index < lines.length; index += 1) {
    const matched = /^(#{1,6})\s+/.exec(lines[index])
    if (matched) headings.push({ index, level: matched[1].length })
  }
  let bestIndex = -1
  let bestScore = 0
  headings.forEach((heading, order) => {
    let end = lines.length
    for (let next = order + 1; next < headings.length; next += 1) {
      if (headings[next].level <= heading.level) {
        end = headings[next].index
        break
      }
    }
    const headingText = lines[heading.index].toLowerCase()
    const section = lines.slice(heading.index, end).join("\n").toLowerCase()
    let score = 0
    tokens.forEach((token) => {
      if (headingText.includes(token)) score += token.length * 3
      else if (section.includes(token)) score += token.length
    })
    if (score > bestScore) {
      bestScore = score
      bestIndex = heading.index
    }
  })
  return bestScore >= 4 ? bestIndex : -1
}

function snippet(file: ArtifactFile) {
  const kind = displayKind(file)
  if (kind === "image" || kind === "video") return `![${stemOf(file.filename) || file.filename}](${file.filename})`
  return `[${stemOf(file.filename) || file.filename}](${file.filename})`
}

export function placeAttachments(markdown: string, files: ArtifactFile[], currentFilename: string) {
  const lines = markdown.split("\n")
  const insertions: Array<{ index: number; order: number; text: string }> = []
  files.forEach((file, order) => {
    if (!file.filename || file.filename === currentFilename || alreadyPlaced(markdown, file.filename)) return
    const mentioned = mentionEnd(lines, file.filename)
    const index = mentioned >= 0 ? mentioned : sectionInsertAt(lines, file.filename)
    insertions.push({ index: index >= 0 ? index + 1 : lines.length, order, text: snippet(file) })
  })
  insertions.sort((left, right) => right.index - left.index || right.order - left.order)
  insertions.forEach((item) => {
    lines.splice(item.index, 0, "", item.text)
  })
  return lines.join("\n")
}
