import type { Agent, Artifact, BackupItem, IngestResult, LibraryItem, Preview, Project, Status, Tag } from "./types"

interface Session {
  base: string
  token: string
  dataDir: string
}

const session: Session = { base: "", token: "", dataDir: "" }

export function dataDir(): string {
  return session.dataDir
}

export async function initApi(): Promise<void> {
  const tauri = (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
  if (!tauri) return
  const { invoke } = await import("@tauri-apps/api/core")
  const info = await invoke<{ port: number; token: string; dataDir: string }>("backend_session")
  session.base = `http://127.0.0.1:${info.port}`
  session.token = info.token
  session.dataDir = info.dataDir
}

export async function openDataDir(): Promise<void> {
  const tauri = (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
  if (!tauri) return
  const { invoke } = await import("@tauri-apps/api/core")
  await invoke("open_data_dir")
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (session.token) headers.set("Authorization", `Bearer ${session.token}`)
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(`${session.base}${path}`, { ...options, headers })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) {
    throw new Error(body?.detail || "请求失败")
  }
  return body as T
}

export function health() {
  return request<{ ok: boolean; version: string }>("/api/health")
}

export function status() {
  return request<Status>("/api/status")
}

export function listArtifacts(params: Record<string, string>) {
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value))
  return request<{ items: LibraryItem[]; total: number; mode: string }>(`/api/artifacts?${query.toString()}`)
}

export function getArtifact(id: string) {
  return request<Artifact>(`/api/artifacts/${id}`)
}

export function updateArtifact(id: string, payload: { title: string; description: string; project: string; tags: string; source_agent: string }) {
  return request<Artifact>(`/api/artifacts/${id}`, { method: "PATCH", body: JSON.stringify(payload) })
}

export function deleteArtifact(id: string) {
  return request<{ ok: boolean }>(`/api/artifacts/${id}`, { method: "DELETE" })
}

export function restoreVersion(artifactId: string, versionId: string) {
  return request<Artifact>(`/api/artifacts/${artifactId}/versions/${versionId}/restore`, { method: "POST" })
}

export function preview(artifactId: string, versionId?: string) {
  const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : ""
  return request<Preview>(`/api/artifacts/${artifactId}/preview${query}`)
}

export function verify(artifactId: string, versionId?: string) {
  const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : ""
  return request<{ ok: boolean; expected: string; actual: string }>(`/api/artifacts/${artifactId}/verify${query}`)
}

export function listProjects() {
  return request<{ items: Project[] }>("/api/projects")
}

export function createProject(name: string, description: string) {
  return request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name, description }) })
}

export function updateProject(id: string, name: string, description: string) {
  return request<Project>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify({ name, description }) })
}

export function deleteProject(id: string) {
  return request<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" })
}

export function listTags() {
  return request<{ items: Tag[] }>("/api/tags")
}

export function createTag(name: string) {
  return request<Tag>("/api/tags", { method: "POST", body: JSON.stringify({ name }) })
}

export function updateTag(id: string, name: string) {
  return request<Tag>(`/api/tags/${id}`, { method: "PATCH", body: JSON.stringify({ name }) })
}

export function deleteTag(id: string) {
  return request<{ ok: boolean }>(`/api/tags/${id}`, { method: "DELETE" })
}

export function listAgents() {
  return request<{ items: Agent[] }>("/api/agents")
}

export function createAgent(name: string, note: string) {
  return request<Agent>("/api/agents", { method: "POST", body: JSON.stringify({ name, note }) })
}

export function updateAgent(id: string, name: string, note: string) {
  return request<Agent>(`/api/agents/${id}`, { method: "PATCH", body: JSON.stringify({ name, note }) })
}

export function deleteAgent(id: string) {
  return request<{ ok: boolean }>(`/api/agents/${id}`, { method: "DELETE" })
}

export function listBackups() {
  return request<{ items: BackupItem[] }>("/api/backups")
}

export function createBackup() {
  return request<BackupItem>("/api/backups", { method: "POST" })
}

export function restoreBackup(name: string) {
  return request<{ ok: boolean }>(`/api/backups/${encodeURIComponent(name)}/restore`, { method: "POST" })
}

export function confirmIngest(payload: {
  staging_id: string
  decision: "new_artifact" | "new_version"
  artifact_id?: string
  title?: string
  description?: string
  project?: string
  tags?: string
  source_agent?: string
  filename?: string
}) {
  return request<IngestResult>("/api/ingest/confirm", { method: "POST", body: JSON.stringify(payload) })
}

export function importModel(path: string) {
  return request<{ model_type: string; path: string }>("/api/semantic/import", { method: "POST", body: JSON.stringify({ path }) })
}

export function enableSemantic(enabled: boolean) {
  return request<Status["semantic"]>("/api/semantic/enable", { method: "POST", body: JSON.stringify({ enabled }) })
}

export function rebuildSemantic() {
  return request<{ ok: boolean; queued: number }>("/api/semantic/rebuild", { method: "POST" })
}

export function clearSemantic() {
  return request<Status["semantic"]>("/api/semantic", { method: "DELETE" })
}

export function uploadFile(file: File, fields: Record<string, string>, onProgress: (ratio: number) => void) {
  return new Promise<IngestResult>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${session.base}/api/ingest`)
    if (session.token) xhr.setRequestHeader("Authorization", `Bearer ${session.token}`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total)
    }
    xhr.onerror = () => reject(new Error("上传失败"))
    xhr.onload = () => {
      let body: IngestResult & { detail?: string } = { status: "error" }
      try {
        body = JSON.parse(xhr.responseText || "{}")
      } catch {
        reject(new Error("响应无法解析"))
        return
      }
      if (xhr.status === 409 && body.status === "needs_decision") {
        resolve(body)
        return
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body)
        return
      }
      reject(new Error(body.detail || "上传失败"))
    }
    const data = new FormData()
    data.append("file", file)
    Object.entries(fields).forEach(([key, value]) => data.append(key, value))
    xhr.send(data)
  })
}

export async function fetchVerifiedBlob(path: string): Promise<{ blob: Blob; verified: boolean; sha: string }> {
  const headers = new Headers()
  if (session.token) headers.set("Authorization", `Bearer ${session.token}`)
  const response = await fetch(`${session.base}${path}`, { headers })
  if (!response.ok) throw new Error("文件读取失败")
  const buffer = await response.arrayBuffer()
  const expected = (response.headers.get("X-Content-SHA256") || "").toLowerCase()
  const digest = await crypto.subtle.digest("SHA-256", buffer)
  const actual = [...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")
  return { blob: new Blob([buffer]), verified: !expected || actual === expected, sha: expected }
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export async function downloadArtifact(artifactId: string, versionId: string | undefined, filename: string) {
  const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : ""
  const file = await fetchVerifiedBlob(`/api/artifacts/${artifactId}/download${query}`)
  if (!file.verified) throw new Error("哈希校验失败，已取消保存")
  saveBlob(file.blob, filename)
  return file.sha
}

export async function restoreUploadedBackup(file: File) {
  const data = new FormData()
  data.append("file", file)
  return request<{ ok: boolean }>("/api/backups/upload-restore", { method: "POST", body: data })
}

export function downloadUrl(name: string) {
  return `${session.base}/api/backups/${encodeURIComponent(name)}/download`
}

export async function downloadBackup(name: string) {
  const file = await fetchVerifiedBlob(`/api/backups/${encodeURIComponent(name)}/download`)
  saveBlob(file.blob, name)
}
