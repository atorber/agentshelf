import { useEffect, useState } from "react"
import { HashRouter, Route, Routes } from "react-router-dom"
import { health, initApi } from "./api"
import { Layout } from "./components/Layout"
import { DetailPage } from "./pages/DetailPage"
import { LibraryPage } from "./pages/LibraryPage"
import { LearnPage } from "./pages/LearnPage"
import { OrganizePage } from "./pages/OrganizePage"
import { SettingsPage } from "./pages/SettingsPage"
import { UploadPage } from "./pages/UploadPage"

export function App() {
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading")
  const [detail, setDetail] = useState("")

  useEffect(() => {
    let stop = false
    ;(async () => {
      for (let attempt = 0; attempt < 40; attempt += 1) {
        try {
          await initApi()
          await health()
          if (!stop) setPhase("ready")
          return
        } catch (reason) {
          if (!stop) setDetail(reason instanceof Error ? reason.message : "正在连接本地服务…")
          await new Promise((resolve) => window.setTimeout(resolve, 300))
        }
      }
      if (!stop) setPhase("error")
    })()
    return () => {
      stop = true
    }
  }, [])

  if (phase !== "ready") {
    return (
      <div className={phase === "error" ? "boot-error" : "boot"}>
        <div className="boot-card">
          <h1>AgentShelf</h1>
          <p>{phase === "error" ? "本地服务没有在预期时间内就绪。" : "正在连接本地服务…"}</p>
          {phase === "loading" ? <p className="muted">服务就绪后会自动进入知识库。</p> : null}
          {phase === "error" && detail ? <p className="error">{detail}</p> : null}
          {phase === "error" ? (
            <p className="muted">可以在项目目录运行 ./scripts/dev.sh，或先执行 agentshelf serve，再刷新这个页面。</p>
          ) : null}
        </div>
      </div>
    )
  }

  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<LibraryPage />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="organize" element={<OrganizePage />} />
          <Route path="learn" element={<LearnPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="artifacts/:id" element={<DetailPage />} />
        </Route>
      </Routes>
    </HashRouter>
  )
}
