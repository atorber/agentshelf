import { useEffect, useState } from "react"
import { NavLink, Outlet } from "react-router-dom"
import { status } from "../api"
import type { Status } from "../types"

const links = [
  ["/", "产物库"],
  ["/upload", "上传"],
  ["/organize", "整理"],
  ["/settings", "设置"],
]

export function Layout() {
  const [info, setInfo] = useState<Status | null>(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let stop = false
    const load = () => {
      status()
        .then((body) => {
          if (!stop) {
            setInfo(body)
            setOffline(false)
          }
        })
        .catch(() => {
          if (!stop) setOffline(true)
        })
    }
    load()
    const timer = window.setInterval(load, 15000)
    return () => {
      stop = true
      window.clearInterval(timer)
    }
  }, [])

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 32 32">
              <rect x="6" y="18" width="20" height="3" rx="1" fill="#f6f1e8" />
              <rect x="8" y="9" width="5" height="9" rx="1" fill="#f3de9a" />
              <rect x="14" y="11" width="5" height="7" rx="1" fill="#f6f1e8" />
              <rect x="20" y="8" width="4" height="10" rx="1" fill="#e7c3b4" />
            </svg>
          </div>
          <div>
            <strong>AgentShelf</strong>
            <span>本地产物库</span>
          </div>
        </div>
        <nav className="nav">
          {links.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="side-status">
          <div>
            <span className={offline || info?.db_ok === false ? "dot warn" : "dot"} />
            {offline ? "服务未响应" : info?.db_ok === false ? "数据库异常" : "服务运行中"}
          </div>
          <div>{info ? `${info.storage.artifact_count} 个产物` : "正在读取状态"}</div>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
