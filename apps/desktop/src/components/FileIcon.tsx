const looks: Record<string, { color: string; glyph: string }> = {
  markdown: { color: "#17b3a3", glyph: "M" },
  html: { color: "#7b5cf0", glyph: "</>" },
  text: { color: "#7d8796", glyph: "T" },
  csv: { color: "#28b463", glyph: "▦" },
  json: { color: "#4c7cf3", glyph: "{ }" },
  image: { color: "#e4638f", glyph: "▲" },
  video: { color: "#9a5cf0", glyph: "▶" },
  pdf: { color: "#e5533d", glyph: "P" },
  unsupported: { color: "#a3a8b1", glyph: "·" },
}

export function FileIcon({ kind, size = 18 }: { kind: string; size?: number }) {
  const look = looks[kind] || looks.unsupported
  return (
    <span className="file-icon" style={{ width: size, height: size, background: look.color, fontSize: look.glyph.length > 1 ? size * 0.4 : size * 0.56 }} aria-hidden="true">
      {look.glyph}
    </span>
  )
}

export function BundleIcon({ size = 18 }: { size?: number }) {
  return (
    <span className="bundle-icon" style={{ width: size, height: size }} aria-hidden="true">
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M7 4h10M5 8h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Zm4 6h6" />
      </svg>
    </span>
  )
}
