export function SnippetText({ value }: { value: string }) {
  const plain = value
    .replace(/[#*`>|]+/g, " ")
    .replace(/(^|\s)[-+]\s/g, "$1")
    .replace(/\s+/g, " ")
    .trim()
  const parts = plain.split(/(【|】)/)
  let marked = false
  const nodes = parts.map((part, index) => {
    if (part === "【") {
      marked = true
      return null
    }
    if (part === "】") {
      marked = false
      return null
    }
    return marked ? <mark key={index}>{part}</mark> : <span key={index}>{part}</span>
  })
  return <p className="snippet">{nodes}</p>
}
