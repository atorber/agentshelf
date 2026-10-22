from __future__ import annotations

import json
import logging
import threading

from agentshelf.db import connect, db_session
from agentshelf.library import now_iso

logger = logging.getLogger("agentshelf")


def recover_interrupted_jobs(db_path) -> int:
    with db_session(db_path, write=True) as conn:
        cursor = conn.execute(
            "UPDATE jobs SET status = 'pending', updated_at = ? WHERE status = 'running'",
            (now_iso(),),
        )
        return int(cursor.rowcount or 0)


def claim_job(db_path) -> dict | None:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        conn.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        conn.commit()
        data = dict(row)
        data["attempts"] = int(data["attempts"]) + 1
        return data
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_job(db_path, job_id: int, *, status: str, error: str = "") -> None:
    with db_session(db_path, write=True) as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error[:500], now_iso(), job_id),
        )


def process_one(library) -> bool:
    job = claim_job(library.settings.db_path)
    if job is None:
        return False
    try:
        payload = json.loads(job["payload"])
        if job["kind"] != "index_version":
            raise RuntimeError(f"未知任务 {job['kind']}")
        library.index_version(int(payload["version_id"]))
        finish_job(library.settings.db_path, int(job["id"]), status="done")
    except Exception as exc:  # noqa: BLE001
        logger.exception("index job failed")
        status = "pending" if int(job["attempts"]) < 3 else "failed"
        finish_job(library.settings.db_path, int(job["id"]), status=status, error=str(exc))
    return True


def drain_jobs(library, limit: int = 200) -> None:
    for _ in range(limit):
        if not process_one(library):
            return


class Worker:
    def __init__(self, library) -> None:
        self.library = library
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        recover_interrupted_jobs(self.library.settings.db_path)
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="agentshelf-index", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = process_one(self.library)
            except Exception:
                logger.exception("index worker")
                worked = False
            if not worked:
                self._stop.wait(0.3)
