import { useEffect, useState } from "react"
import { backupToCloud, clearSemantic, createBackup, dataDir, downloadBackup, enableSemantic, getCloud, importModel, listBackups, listCloudBackups, openDataDir, pullSync, pushSync, rebuildSemantic, restoreBackup, restoreCloudBackup, restoreUploadedBackup, saveCloud, saveSync, status, testCloud } from "../api"
import { formatBytes, formatTime } from "../format"
import type { BackupItem, CloudInput, CloudSettings, Status } from "../types"

type CloudForm = CloudSettings & { secret_access_key: string }

function cloudPayload(cloud: CloudInput): CloudInput {
  return {
    endpoint: cloud.endpoint,
    region: cloud.region,
    bucket: cloud.bucket,
    prefix: cloud.prefix,
    access_key_id: cloud.access_key_id,
    secret_access_key: cloud.secret_access_key,
    path_style: cloud.path_style,
  }
}

const EMPTY_CLOUD: CloudForm = {
  endpoint: "",
  region: "us-east-1",
  bucket: "",
  prefix: "",
  access_key_id: "",
  secret_access_key: "",
  path_style: true,
  secret_set: false,
  configured: false,
  sync_bucket: "",
  sync_prefix: "",
  sync_configured: false,
}

const INSTALL_PROMPT =
  "请从 https://github.com/atorber/agentshelf 安装 Skill agentshelf-archive（目录 skill/agentshelf-archive）。安装到我当前使用的 Agent 的用户级 skills 目录，使所有项目可用。安装完成后告诉我安装位置，并打开 AgentShelf。如果打不开，说明原因，不要声称已经打开。"
const ARCHIVE_PROMPT = "把这份最终稿归档到 AgentShelf。"

export function SettingsPage() {
  const [info, setInfo] = useState<Status | null>(null)
  const [backups, setBackups] = useState<BackupItem[]>([])
  const [cloud, setCloud] = useState(EMPTY_CLOUD)
  const [remote, setRemote] = useState<BackupItem[]>([])
  const [modelPath, setModelPath] = useState("")
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  async function reload() {
    const [body, backupBody, cloudBody] = await Promise.all([status(), listBackups(), getCloud()])
    setInfo(body)
    setBackups(backupBody.items)
    setCloud({ ...EMPTY_CLOUD, ...cloudBody, secret_access_key: "" })
    setModelPath(body.semantic.model_path || "")
    if (!cloudBody.configured) {
      setRemote([])
      return
    }
    try {
      setRemote((await listCloudBackups()).items)
    } catch (reason) {
      setRemote([])
      setError(reason instanceof Error ? reason.message : "云端目录读取失败")
    }
  }

  useEffect(() => {
    reload()
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "读取失败"))
      .finally(() => setLoading(false))
  }, [])

  async function run(action: () => Promise<unknown>, success: string) {
    setError("")
    setMessage("")
    setBusy(true)
    try {
      const result = await action()
      await reload()
      setMessage(typeof result === "string" && result ? result : success)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败")
    }
    setBusy(false)
  }

  async function checkCloud() {
    setError("")
    setMessage("")
    setBusy(true)
    try {
      const result = await testCloud(cloudPayload(cloud))
      setMessage(result.message)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接失败")
    }
    setBusy(false)
  }

  function copy(text: string) {
    navigator.clipboard
      .writeText(text)
      .then(() => setMessage("已复制"))
      .catch(() => setError("复制失败"))
  }

  const storage = info?.storage
  const total = storage?.total_bytes || 1
  const failedJobs = (info?.jobs.recent || []).filter((job) => job.status === "failed")

  return (
    <section className="page narrow">
      <div className="page-head">
        <div>
          <h1>设置</h1>
          <p>知识库留在本机。云端备份上传 zip 压缩包。云同步按目录镜像整个存储目录，需要手动执行。不会自动下载模型，也不发送遥测。</p>
        </div>
      </div>
      {message ? <p className="notice">{message}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {loading && !info ? (
        <div className="panel empty">正在读取设置…</div>
      ) : (
        <>
          <div className="panel">
            <div className="panel-head">
              <h2>Agent 接入</h2>
            </div>
            <div className="panel-body">
              <div className="stack" style={{ gap: 6 }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="muted small">安装 Skill：把这段话发给 Agent</span>
                  <button className="btn-text" onClick={() => copy(INSTALL_PROMPT)}>
                    复制
                  </button>
                </div>
                <p className="prompt">{INSTALL_PROMPT}</p>
              </div>
              <div className="stack" style={{ gap: 6 }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="muted small">归档：任务完成后对 Agent 说</span>
                  <button className="btn-text" onClick={() => copy(ARCHIVE_PROMPT)}>
                    复制
                  </button>
                </div>
                <p className="prompt">{ARCHIVE_PROMPT}</p>
              </div>
              <p className="muted small">名称、项目、标签和来源由 Agent 自动填写。内容与已有知识相同时，Agent 会先问你是新建一条还是追加版本，不会按文件名覆盖。</p>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>服务</h2>
              <span className={info?.db_ok ? "badge current" : "badge"}>{info?.db_ok ? "正常" : "数据库异常"}</span>
            </div>
            <div className="panel-body">
              <dl className="kv">
                <dt>版本</dt>
                <dd>{info?.version || "—"}</dd>
                <dt>监听</dt>
                <dd>{info?.host || "127.0.0.1"}</dd>
                <dt>全文索引</dt>
                <dd>{info?.fts_tokenizer || "—"}</dd>
                <dt>后台任务</dt>
                <dd>
                  待处理 {info?.jobs.pending || 0} · 失败 {info?.jobs.failed || 0}
                </dd>
              </dl>
              {info && !info.db_ok ? <p className="error">数据库完整性检查未通过，建议从备份恢复。</p> : null}
              {failedJobs.map((job) => (
                <p key={job.id} className="error small">
                  任务 {job.id}：{job.error || job.status}
                </p>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>存储</h2>
              <span className="muted small">{formatBytes(storage?.total_bytes || 0)}</span>
            </div>
            <div className="panel-body">
              <div className="row">
                <span className="hash grow" style={{ color: "var(--ink)" }}>
                  {storage?.data_dir || dataDir() || "—"}
                </span>
                <button className="btn-text" onClick={() => copy(storage?.data_dir || "")} disabled={!storage?.data_dir}>
                  复制
                </button>
                <button className="btn-text" onClick={() => openDataDir().catch(() => setError("请在桌面应用中打开目录"))}>
                  打开
                </button>
              </div>
              <div className="meter" title="文件占比">
                <span style={{ width: `${Math.min(100, ((storage?.objects_bytes || 0) / total) * 100)}%` }} />
              </div>
              <dl className="kv">
                <dt>内容</dt>
                <dd>
                  {storage?.artifact_count || 0} 条知识 · {storage?.version_count || 0} 个版本 · {storage?.blob_count || 0} 个文件
                </dd>
                <dt>占用</dt>
                <dd>
                  文件 {formatBytes(storage?.objects_bytes || 0)} · 数据库 {formatBytes(storage?.db_bytes || 0)} · 备份 {formatBytes(storage?.backup_bytes || 0)}
                </dd>
              </dl>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>备份与恢复</h2>
              <div className="row">
                <label className="btn-text">
                  从文件恢复
                  <input
                    hidden
                    type="file"
                    accept=".zip,application/zip"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      event.target.value = ""
                      if (!file) return
                      if (!window.confirm("用这个备份替换当前知识库？")) return
                      run(() => restoreUploadedBackup(file), "已从文件恢复")
                    }}
                  />
                </label>
                <button className="btn" disabled={busy} onClick={() => run(createBackup, "已创建备份")}>
                  创建备份
                </button>
              </div>
            </div>
            <div>
              {backups.length === 0 ? <div className="empty small">还没有备份。恢复会替换当前知识库，失败时自动回滚。</div> : null}
              {backups.map((item) => (
                <div className="list-row" key={item.name}>
                  <div className="grow">
                    <div className="item-title">
                      <span>{item.name}</span>
                    </div>
                    <div className="item-sub">
                      {formatBytes(item.size_bytes)} · {formatTime(item.created_at)}
                    </div>
                  </div>
                  <button className="btn-text" onClick={() => downloadBackup(item.name).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "下载失败"))}>
                    下载
                  </button>
                  <button
                    className="btn-text danger"
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm("用该备份替换当前知识库？")) run(() => restoreBackup(item.name), "已恢复")
                    }}
                  >
                    恢复
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>云端备份</h2>
              <span className={cloud.configured ? "badge current" : "badge"}>{cloud.configured ? "已配置" : "未配置"}</span>
            </div>
            <div className="panel-body">
              <p className="muted small">填写标准 S3。这里的目录只存放 zip 备份包，例如 backups/agentshelf。Secret Key 只写在本机数据目录，保存后不会再显示。按目录镜像存储请用下面的云同步。</p>
              <div className="form-grid">
                <label className="field span">
                  <span>访问地址</span>
                  <input value={cloud.endpoint} onChange={(event) => setCloud((current) => ({ ...current, endpoint: event.target.value }))} placeholder="留空使用 AWS，或填写 https://s3.example.com" aria-label="访问地址" />
                </label>
                <label className="field">
                  <span>区域</span>
                  <input value={cloud.region} onChange={(event) => setCloud((current) => ({ ...current, region: event.target.value }))} placeholder="us-east-1" aria-label="区域" />
                </label>
                <label className="field">
                  <span>Bucket</span>
                  <input value={cloud.bucket} onChange={(event) => setCloud((current) => ({ ...current, bucket: event.target.value }))} placeholder="my-bucket" aria-label="Bucket" />
                </label>
                <label className="field span">
                  <span>目录</span>
                  <input value={cloud.prefix} onChange={(event) => setCloud((current) => ({ ...current, prefix: event.target.value }))} placeholder="backups/agentshelf" aria-label="目录" />
                </label>
                <label className="field">
                  <span>Access Key</span>
                  <input value={cloud.access_key_id} onChange={(event) => setCloud((current) => ({ ...current, access_key_id: event.target.value }))} aria-label="Access Key" autoComplete="off" />
                </label>
                <label className="field">
                  <span>Secret Key</span>
                  <input
                    type="password"
                    value={cloud.secret_access_key}
                    onChange={(event) => setCloud((current) => ({ ...current, secret_access_key: event.target.value }))}
                    placeholder={cloud.secret_set ? "已保存，留空则不修改" : ""}
                    aria-label="Secret Key"
                    autoComplete="new-password"
                  />
                </label>
              </div>
              <label className="row" style={{ gap: 8 }}>
                <input type="checkbox" checked={cloud.path_style} onChange={(event) => setCloud((current) => ({ ...current, path_style: event.target.checked }))} />
                <span>路径风格地址（MinIO 和多数自建 S3 需要）</span>
              </label>
              <div className="row">
                <button className="btn" disabled={busy} onClick={() => run(() => saveCloud(cloudPayload(cloud)), "已保存云端配置")}>
                  保存
                </button>
                <button className="btn" disabled={busy} onClick={() => checkCloud()}>
                  测试连接
                </button>
                <button
                  className="btn-primary"
                  disabled={busy || !cloud.configured}
                  onClick={() =>
                    run(async () => {
                      const item = await backupToCloud()
                      return `已上传到 ${item.prefix}${item.name}`
                    }, "")
                  }
                >
                  备份到云端
                </button>
              </div>
              {remote.length === 0 ? <p className="muted small">云端目录里还没有备份。备份到云端时也会在本机留一份。</p> : null}
              {remote.map((item) => (
                <div className="list-row" key={item.name} style={{ paddingLeft: 0, paddingRight: 0 }}>
                  <div className="grow">
                    <div className="item-title">
                      <span>{item.name}</span>
                    </div>
                    <div className="item-sub">
                      {formatBytes(item.size_bytes)} · {formatTime(item.created_at)}
                    </div>
                  </div>
                  <button
                    className="btn-text danger"
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm("用这份云端备份替换当前知识库？")) run(() => restoreCloudBackup(item.name), "已从云端恢复")
                    }}
                  >
                    恢复
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>云同步</h2>
              <span className={cloud.sync_configured ? "badge current" : "badge"}>{cloud.sync_configured ? "已配置" : "未配置"}</span>
            </div>
            <div className="panel-body">
              <p className="muted small">指定一个 Bucket，再指定一个目录作为云同步根目录。同步会按本机数据目录的结构上传 library.db、文件、本地备份和模型。令牌、S3 密钥、运行状态、日志和暂存不会上传。访问地址、区域和密钥使用上面已保存的连接。</p>
              <div className="form-grid">
                <label className="field">
                  <span>同步 Bucket</span>
                  <input value={cloud.sync_bucket} onChange={(event) => setCloud((current) => ({ ...current, sync_bucket: event.target.value }))} placeholder="sync-bucket" aria-label="同步 Bucket" />
                </label>
                <label className="field">
                  <span>同步目录</span>
                  <input value={cloud.sync_prefix} onChange={(event) => setCloud((current) => ({ ...current, sync_prefix: event.target.value }))} placeholder="agentshelf" aria-label="同步目录" />
                </label>
              </div>
              <div className="row">
                <button className="btn" disabled={busy} onClick={() => run(() => saveSync({ bucket: cloud.sync_bucket, prefix: cloud.sync_prefix }), "已保存云同步目录")}>
                  保存同步目录
                </button>
                <button
                  className="btn-primary"
                  disabled={busy || !cloud.sync_configured}
                  onClick={() => {
                    if (!window.confirm("按本地存储目录覆盖云端目录，云端多余文件会被删除。继续？")) return
                    run(async () => {
                      const item = await pushSync()
                      return `已同步 ${item.files} 个文件，上传 ${item.uploaded}，删除云端多余 ${item.deleted}`
                    }, "")
                  }}
                >
                  同步到云端
                </button>
                <button
                  className="btn"
                  disabled={busy || !cloud.sync_configured}
                  onClick={() => {
                    if (!window.confirm("从云端拉取会用云端目录替换本地数据库、文件、备份和模型。令牌和 S3 配置留在本机。继续？")) return
                    run(() => pullSync(), "已从云端拉取")
                  }}
                >
                  从云端拉取
                </button>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>语义检索</h2>
              <span className={info?.semantic.enabled ? "badge current" : "badge"}>{info?.semantic.enabled ? "已启用" : "未启用"}</span>
            </div>
            <div className="panel-body">
              <p className="muted small">{`${info?.semantic.reason || "—"}。需要本地模型目录（含 config.json 和权重文件）。未启用时全文检索和预览不受影响。`}</p>
              <div className="row">
                <input className="grow" value={modelPath} onChange={(event) => setModelPath(event.target.value)} placeholder="本地模型目录，例如 /path/to/model" aria-label="本地模型目录" />
                <button className="btn" onClick={() => run(() => importModel(modelPath), "模型已导入，尚未启用")} disabled={busy || !modelPath.trim()}>
                  校验并导入
                </button>
              </div>
              <div className="row">
                {info?.semantic.enabled ? (
                  <button className="btn" disabled={busy} onClick={() => run(() => enableSemantic(false), "已关闭语义检索")}>
                    关闭
                  </button>
                ) : (
                  <button className="btn-primary" onClick={() => run(() => enableSemantic(true), "已启用语义检索")} disabled={busy || (!info?.semantic.model_path && !info?.semantic.package_ready)}>
                    启用
                  </button>
                )}
                <button className="btn-text" onClick={() => run(rebuildSemantic, "已开始重建语义索引")} disabled={busy || !info?.semantic.enabled}>
                  重建索引
                </button>
                <button className="btn-text danger" disabled={busy} onClick={() => run(clearSemantic, "已删除语义索引")}>
                  删除索引
                </button>
                <span className="muted small" style={{ marginLeft: "auto" }}>
                  已索引 {info?.semantic.indexed_versions || 0} 个版本
                </span>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>遇到问题时</h2>
            </div>
            <div className="panel-body">
              <ul className="tips">
                <li>页面一直停在启动：让 Agent 重新打开 AgentShelf，它会先检查服务是否已在运行。</li>
                <li>端口被占用时，服务会自动改用 8765 到 8865 之间的空闲端口。</li>
                <li>预览失败时，这条知识和下载仍然保留，损坏的文件不会影响其他知识。</li>
                <li>日志写在数据目录的 logs 里，不会发往外部服务器。</li>
              </ul>
            </div>
          </div>
        </>
      )}
    </section>
  )
}
