const paths: Record<string, string> = {
  library: "M4 5.5A1.5 1.5 0 0 1 5.5 4H10l2 2h6.5A1.5 1.5 0 0 1 20 7.5v11a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5Z",
  book: "M4 5.5C4 4.7 4.7 4 5.5 4H10a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4Zm16 0c0-.8-.7-1.5-1.5-1.5H14a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6Z",
  upload: "M12 16V4m0 0-5 5m5-5 5 5M4 20h16",
  organize: "M4 7h10M4 12h16M4 17h7M17 4v6m0 0 3-3m-3 3-3-3",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7.6 7.6 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7.6 7.6 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z",
  search: "m20 20-4.5-4.5M17 10.5a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0Z",
  back: "M15 18l-6-6 6-6",
  download: "M12 4v11m0 0-4-4m4 4 4-4M5 20h14",
  check: "M5 12.5 10 17l9-10",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Zm0 0v5h5",
  filter: "M4 5h16l-6 7.5V19l-4 1.5v-8Z",
  "chevron-down": "m6 9 6 6 6-6",
  "chevron-right": "m9 6 6 6-6 6",
  close: "M6 6l12 12M18 6 6 18",
  expand: "M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  panel: "M4 5h16v14H4ZM9.5 5v14",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13v4.5l3 2",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-10v5m0-8h.01",
  trash: "M5 7h14M10 11v6m4-6v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3",
  sort: "M8 9l4-4 4 4M8 15l4 4 4-4",
  "sort-down": "M8 15l4 4 4-4",
  "sort-up": "M8 9l4-4 4 4",
  plus: "M12 5v14M5 12h14",
  stack: "M12 4 3 8.5l9 4.5 9-4.5Zm-9 8 9 4.5 9-4.5m-18 4 9 4.5 9-4.5",
}

export function Icon({ name, size = 16 }: { name: keyof typeof paths | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  )
}
