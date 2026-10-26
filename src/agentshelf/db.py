from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_agents (
  id INTEGER PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_objects (
  id INTEGER PRIMARY KEY,
  sha256 TEXT NOT NULL UNIQUE,
  size_bytes INTEGER NOT NULL,
  mime_type TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  source_agent_id INTEGER REFERENCES source_agents(id) ON DELETE SET NULL,
  current_version_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifact_versions (
  id INTEGER PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  file_object_id INTEGER NOT NULL REFERENCES file_objects(id),
  original_filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  preview_kind TEXT NOT NULL DEFAULT 'unsupported',
  extracted_text TEXT NOT NULL DEFAULT '',
  extract_status TEXT NOT NULL DEFAULT 'pending',
  extract_error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(artifact_id, version_number)
);

CREATE TABLE IF NOT EXISTS version_files (
  id INTEGER PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  version_id INTEGER NOT NULL REFERENCES artifact_versions(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  file_object_id INTEGER NOT NULL REFERENCES file_objects(id),
  original_filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  preview_kind TEXT NOT NULL DEFAULT 'unsupported',
  extracted_text TEXT NOT NULL DEFAULT '',
  extract_status TEXT NOT NULL DEFAULT 'pending',
  extract_error TEXT NOT NULL DEFAULT '',
  UNIQUE(version_id, position)
);

CREATE TABLE IF NOT EXISTS artifact_tags (
  artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (artifact_id, tag_id)
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
  version_id INTEGER PRIMARY KEY REFERENCES artifact_versions(id) ON DELETE CASCADE,
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL,
  model_type TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_versions_artifact ON artifact_versions(artifact_id);
CREATE INDEX IF NOT EXISTS idx_versions_sha ON artifact_versions(sha256);
CREATE INDEX IF NOT EXISTS idx_version_files_version ON version_files(version_id);
CREATE INDEX IF NOT EXISTS idx_version_files_sha ON version_files(sha256);
CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_updated ON artifacts(updated_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS inspector_skills (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  source_type TEXT NOT NULL,
  source_uri TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inspector_versions (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL REFERENCES inspector_skills(id) ON DELETE CASCADE,
  content_hash TEXT NOT NULL,
  mode TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inspector_files (
  id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL REFERENCES inspector_versions(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL,
  file_type TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  content_text TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS inspector_jobs (
  id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL REFERENCES inspector_versions(id) ON DELETE CASCADE,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  stage TEXT NOT NULL,
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS inspector_reports (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES inspector_jobs(id) ON DELETE CASCADE,
  version_id TEXT NOT NULL REFERENCES inspector_versions(id) ON DELETE CASCADE,
  schema_version TEXT NOT NULL,
  overview_json TEXT NOT NULL,
  report_json TEXT NOT NULL,
  model_info_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inspector_messages (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES inspector_reports(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  body TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inspector_versions_skill ON inspector_versions(skill_id);
CREATE INDEX IF NOT EXISTS idx_inspector_files_version ON inspector_files(version_id);
CREATE INDEX IF NOT EXISTS idx_inspector_reports_version ON inspector_reports(version_id);
CREATE INDEX IF NOT EXISTS idx_inspector_versions_hash ON inspector_versions(skill_id, content_hash, mode);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def db_session(path: Path, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def _fts_tokenizer(conn: sqlite3.Connection) -> str:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(body, tokenize='trigram')")
        conn.execute("DROP TABLE IF EXISTS _fts_probe")
        return "trigram"
    except sqlite3.OperationalError:
        return "unicode61"


def init_db(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        conn.executescript(SCHEMA)
        _backfill_version_files(conn)
        conn.commit()
        row = conn.execute("SELECT value FROM settings WHERE key = 'fts_tokenizer'").fetchone()
        if row:
            return str(row["value"])
        tokenizer = _fts_tokenizer(conn)
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS artifact_fts USING fts5(
              version_id UNINDEXED,
              artifact_id UNINDEXED,
              title,
              description,
              filename,
              body,
              tags,
              project,
              source,
              tokenize='{tokenizer}'
            )
            """
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('fts_tokenizer', ?)",
            (tokenizer,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES('schema_version', '1')"
        )
        conn.commit()
        return tokenizer
    finally:
        conn.close()


def _backfill_version_files(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT v.* FROM artifact_versions v
        WHERE NOT EXISTS (SELECT 1 FROM version_files vf WHERE vf.version_id = v.id)
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO version_files(
              public_id, version_id, position, file_object_id, original_filename, mime_type,
              size_bytes, sha256, preview_kind, extracted_text, extract_status, extract_error
            ) VALUES(?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                row["id"],
                row["file_object_id"],
                row["original_filename"],
                row["mime_type"],
                row["size_bytes"],
                row["sha256"],
                row["preview_kind"],
                row["extracted_text"],
                row["extract_status"],
                row["extract_error"],
            ),
        )


def integrity_ok(path: Path) -> bool:
    return _pragma_ok(path, "integrity_check")


def quick_check_ok(path: Path) -> bool:
    return _pragma_ok(path, "quick_check")


def _pragma_ok(path: Path, pragma: str) -> bool:
    try:
        with db_session(path) as conn:
            row = conn.execute(f"PRAGMA {pragma}").fetchone()
        return bool(row) and str(row[0]) == "ok"
    except sqlite3.DatabaseError:
        return False
