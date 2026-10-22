export type PreviewKind = "markdown" | "text" | "csv" | "json" | "image" | "video" | "pdf" | "unsupported"

export interface ArtifactFile {
  id: string
  filename: string
  mime_type: string
  size_bytes: number
  sha256: string
  preview_kind: PreviewKind
  extract_status: string
  extract_error: string
}

export interface Version {
  id: string
  version_number: number
  filename: string
  mime_type: string
  size_bytes: number
  sha256: string
  note: string
  preview_kind: PreviewKind
  extract_status: string
  extract_error: string
  created_at: string
  is_current: boolean
  file_count: number
  files: ArtifactFile[]
}

export interface Artifact {
  id: string
  title: string
  description: string
  project: { id: string; name: string } | null
  source_agent: { id: string; name: string } | null
  tags: string[]
  created_at: string
  updated_at: string
  version_count: number
  current_version: Version | null
  versions: Version[]
  status?: string
  message?: string
  stored_new_blob?: boolean
}

export interface LibraryItem {
  artifact_id: string
  version_id: string
  version_number: number
  title: string
  description: string
  filename: string
  mime_type: string
  preview_kind: PreviewKind
  sha256: string
  project: string | null
  source_agent: string | null
  tags: string[]
  updated_at: string
  is_current: boolean
  file_count: number
  snippet: string
  score?: number
}

export interface Candidate {
  artifact_id: string
  title: string
  filename: string
  versions: number[]
}

export interface IngestResult extends Partial<Artifact> {
  status: string
  message?: string
  staging_id?: string
  sha256?: string
  filename?: string
  candidates?: Candidate[]
  stored_new_blob?: boolean
}

export interface Project {
  id: string
  name: string
  description: string
  artifact_count: number
  created_at: string
  updated_at: string
}

export interface Tag {
  id: string
  name: string
  artifact_count: number
  created_at: string
}

export interface Agent {
  id: string
  name: string
  note: string
  artifact_count: number
  created_at: string
}

export interface BackupItem {
  name: string
  size_bytes: number
  created_at: string
}

export interface Status {
  version: string
  host: string
  data_dir: string
  db_ok: boolean
  fts_tokenizer: string
  jobs: {
    pending: number
    running: number
    failed: number
    done: number
    recent: Array<{ id: number; kind: string; status: string; error: string; attempts: number; updated_at: string }>
  }
  storage: {
    data_dir: string
    db_bytes: number
    objects_bytes: number
    backup_bytes: number
    total_bytes: number
    artifact_count: number
    version_count: number
    blob_count: number
  }
  semantic: {
    enabled: boolean
    requested: boolean
    package_ready: boolean
    model_path: string
    model_type: string
    indexed_versions: number
    reason: string
  }
}

export interface Preview {
  artifact_id: string
  version_id: string
  file_id?: string
  version_number: number
  filename: string
  mime_type: string
  preview_kind: PreviewKind
  size_bytes: number
  sha256: string
  text?: string
  truncated?: boolean
  rows?: string[][]
  json?: unknown
  page_count?: number | null
  error?: string
}
