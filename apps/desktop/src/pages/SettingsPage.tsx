import { useEffect, useState } from "react"
import { clearSemantic, createBackup, dataDir, downloadBackup, enableSemantic, importModel, listBackups, openDataDir, rebuildSemantic, restoreBackup, restoreUploadedBackup, status } from "../api"
import { formatBytes, formatTime } from "../format"
import type { BackupItem, Status } from "../types"

export function SettingsPage() {
  const [info, setInfo] = useState<Status | null>(null)
  const [backups, setBackups] = useState<BackupItem[]>([])
  const [modelPath, setModelPath] = useState("")
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)

  async function reload() {
    const [body, backupBody] = await Promise.all([status(), listBackups()])
    setInfo(body)
    setBackups(backupBody.items)
    setModelPath(body.semantic.model_path || "")
  }

  useEffect(() => {
    reload()
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "读取失败"))
      .finally(() => setLoading(false))
  }, [])

  async function run(action: () => Promise<unknown>, success: string) {
    setError("")
    try {
      await action()
      await reload()
      setMessage(success)
    } catch (reason) {
      setMessage("")
      setError(reason instanceof Error ? reason.message : "操作失败")
    }
  }

  const storage = info?.storage
  const total = storage?.total_bytes || 1

  return (
    <section className="stack">
      <div className="page-head">
        <div>
          <h1>设置</h1>
          <p>数据、索引和备份都留在本机。应用不会自动下载模型，也不会发送遥测。</p>
        </div>
      </div>
      {message ? <div className="notice">{message}</div> : null}
      {error ? <p className="error">{error}</p> : null}
      {loading && !info ? (
        <div className="empty">正在读取设置…</div>
      ) : (
        <>
      <div className="panel stack">
        <h2>服务</h2>
        <div>版本 {info?.version || "—"} · 监听 {info?.host || "127.0.0.1"} · 索引 {info?.fts_tokenizer || "—"}</div>
        <div>{info?.db_ok ? "数据库完整性检查通过" : "数据库完整性检查未通过，请先从备份恢复"}</div>
        <div className="muted">
          待处理任务 {info?.jobs.pending || 0} · 失败任务 {info?.jobs.failed || 0}
        </div>
        {(info?.jobs.recent || [])
          .filter((job) => job.status === "failed")
          .map((job) => (
            <div key={job.id} className="error">
              任务 {job.id}：{job.error || job.status}
            </div>
          ))}
      </div>

      <div className="panel stack">
        <h2>存储</h2>
        <div className="hash">{storage?.data_dir || dataDir() || "启动后可在此查看数据目录"}</div>
        <div className="actions">
          <button
            className="btn-ghost"
            onClick={() => navigator.clipboard.writeText(storage?.data_dir || "")}
            disabled={!storage?.data_dir}
          >
            复制路径
          </button>
          <button className="btn-ghost" onClick={() => openDataDir().catch(() => setError("请在桌面应用中打开目录"))}>
            打开目录
          </button>
        </div>
        <div>产物 {storage?.artifact_count || 0} · 版本 {storage?.version_count || 0} · 物理文件 {storage?.blob_count || 0}</div>
        <div className="muted">合计 {formatBytes(storage?.total_bytes || 0)}</div>
        <div className="meter" title="对象文件占比">
          <span style={{ width: `${Math.min(100, ((storage?.objects_bytes || 0) / total) * 100)}%` }} />
        </div>
        <div className="muted">
          文件 {formatBytes(storage?.objects_bytes || 0)} · 数据库 {formatBytes(storage?.db_bytes || 0)} · 备份 {formatBytes(storage?.backup_bytes || 0)}
        </div>
      </div>

      <div className="panel stack">
        <h2>备份与恢复</h2>
        <p className="muted">恢复会替换当前产物库。开始前会先把现有数据移开，失败时再移回。</p>
        <div className="actions">
          <button className="btn-primary" onClick={() => run(createBackup, "已创建备份")}>
            创建备份
          </button>
          <label className="btn-ghost">
            从文件恢复
            <input
              hidden
              type="file"
              accept=".zip,application/zip"
              onChange={(event) => {
                const file = event.target.files?.[0]
                event.target.value = ""
                if (!file) return
                if (!window.confirm("用这个备份替换当前产物库？")) return
                run(() => restoreUploadedBackup(file), "已从文件恢复")
              }}
            />
          </label>
        </div>
        {backups.length === 0 ? <div className="muted">还没有备份</div> : null}
        {backups.map((item) => (
          <div className="version" key={item.name}>
            <div>
              <strong>{item.name}</strong>
              <div className="muted">
                {formatBytes(item.size_bytes)} · {formatTime(item.created_at)}
              </div>
            </div>
            <div className="actions">
              <button className="btn-ghost" onClick={() => downloadBackup(item.name).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "下载失败"))}>
                下载
              </button>
              <button
                className="btn-danger"
                onClick={() => {
                  if (window.confirm("用该备份替换当前产物库？")) run(() => restoreBackup(item.name), "已恢复")
                }}
              >
                恢复
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="panel stack">
        <h2>语义检索</h2>
        <p>当前状态：{info?.semantic.reason || "读取中"}</p>
        <p className="muted">模型目录需要包含 config.json 和权重文件。未启用时，全文检索和预览保持可用。</p>
        <label className="field">
          <span>本地模型目录</span>
          <input value={modelPath} onChange={(event) => setModelPath(event.target.value)} placeholder="/path/to/model" />
        </label>
        <div className="actions">
          <button className="btn-ghost" onClick={() => run(() => importModel(modelPath), "模型已导入，尚未启用")} disabled={!modelPath.trim()}>
            校验并导入
          </button>
          <button className="btn-primary" onClick={() => run(() => enableSemantic(true), "已启用语义检索")} disabled={!info?.semantic.model_path && !info?.semantic.package_ready}>
            启用
          </button>
          <button className="btn-ghost" onClick={() => run(() => enableSemantic(false), "已关闭语义检索")}>
            关闭
          </button>
          <button className="btn-ghost" onClick={() => run(rebuildSemantic, "已开始重建语义索引")} disabled={!info?.semantic.enabled}>
            重建索引
          </button>
          <button className="btn-danger" onClick={() => run(clearSemantic, "已删除语义索引")}>
            删除语义索引
          </button>
        </div>
        <div className="muted">已索引版本 {info?.semantic.indexed_versions || 0}</div>
      </div>

      <div className="panel stack">
        <h2>Skill 安装</h2>
        <p>安装 Skill 后，让 Agent 归档时会先运行仓库里的 scripts/launch.py，把后端和桌面界面准备好，再登记产物。</p>
        <pre className="mono">{`agentshelf archive ./最终稿.md --title "周报" --project "工作" --tags "报告" --source "cursor"`}</pre>
        <p className="muted">如果命令退出码是 2，表示相同内容已存在。需要明确选择 --new-artifact，或用 --artifact-id 追加版本。不要按文件名覆盖。</p>
      </div>

      <div className="panel stack">
        <h2>遇到问题时</h2>
        <ul>
          <li>页面一直停在启动：先运行 agentshelf status，确认服务是否已监听 127.0.0.1。</li>
          <li>端口被占用时，服务会自动改用 8765 到 8865 之间的空闲端口。</li>
          <li>关闭桌面窗口会停止由它启动的后端。命令行单独启动的服务会继续运行，可用 agentshelf stop 结束。</li>
          <li>预览失败时，产物记录和下载仍然保留。损坏文件不会拖垮整个应用。</li>
          <li>日志写在数据目录的 logs，不会发往外部服务器。</li>
        </ul>
      </div>
        </>
      )}
    </section>
  )
}
