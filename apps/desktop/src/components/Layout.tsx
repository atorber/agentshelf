import { useEffect, useState } from "react"
import { Link, NavLink, Outlet, useLocation, useSearchParams } from "react-router-dom"
import { listProjects, status } from "../api"
import { libraryPath } from "../format"
import type { Project, Status } from "../types"
import { Icon } from "./Icon"

const links = [
  ["/", "知识库", "book"],
  ["/upload", "上传", "upload"],
  ["/organize", "整理", "organize"],
  ["/settings", "设置", "settings"],
]

export function Layout() {
  const [info, setInfo] = useState<Status | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [offline, setOffline] = useState(false)
  const location = useLocation()
  const [params] = useSearchParams()
  const inLibrary = location.pathname === "/" || location.pathname.startsWith("/artifacts/")
  const inDetail = location.pathname.startsWith("/artifacts/")
  const activeProject = location.pathname === "/" ? params.get("project") || "" : ""

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
      listProjects()
        .then((body) => {
          if (!stop) setProjects(body.items)
        })
        .catch(() => undefined)
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
            <svg width="16" height="16" viewBox="0 0 32 32">
              <rect x="6" y="18" width="20" height="3" rx="1" fill="#f6f1e8" />
              <rect x="8" y="9" width="5" height="9" rx="1" fill="#f3de9a" />
              <rect x="14" y="11" width="5" height="7" rx="1" fill="#f6f1e8" />
              <rect x="20" y="8" width="4" height="10" rx="1" fill="#e7c3b4" />
            </svg>
          </div>
          <div className="brand-text">
            <strong>AgentShelf</strong>
            <span>{info ? `v${info.version}` : "本地知识库"}</span>
          </div>
        </div>
        <nav className="nav">
          {links.map(([to, label, icon]) => (
            <NavLink key={to} to={to === "/" ? libraryPath() : to} end={to === "/"} className={({ isActive }) => ((to === "/" ? inLibrary : isActive) ? "active" : "")}>
              <Icon name={icon} />
              {label}
            </NavLink>
          ))}
        </nav>
        {projects.length ? (
          <div className="side-section">
            <div className="side-label">项目 ({projects.length})</div>
            {projects.map((project) => (
              <Link
                key={project.id}
                to={`/?project=${encodeURIComponent(project.name)}`}
                className={activeProject === project.name ? "side-row active" : "side-row"}
                aria-current={activeProject === project.name ? "page" : undefined}
                title={project.name}
              >
                <span className="side-row-name">{project.name}</span>
                <span className="side-row-meta">{project.artifact_count}</span>
              </Link>
            ))}
          </div>
        ) : null}
        <div className="side-status">
          <span className={offline || info?.db_ok === false ? "dot warn" : "dot"} />
          <span className="grow">{offline ? "服务未响应" : info?.db_ok === false ? "数据库异常" : info ? "服务运行中" : "正在连接"}</span>
          {info ? <span className="faint">{info.storage.artifact_count} 条知识</span> : null}
        </div>
      </aside>
      <main className={inDetail ? "main flush" : "main"}>
        <Outlet />
      </main>
    </div>
  )
}
