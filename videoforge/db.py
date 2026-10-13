"""SQLite 持久化：业务最终状态的**唯一权威来源**。

为什么需要它（而不是只靠内存变量）？
------------------------------------
* 媒体生成是异步、长耗时的：进程重启后必须能从“上次做到哪”恢复；
* QA 返工、防重复扣费、产物追踪都需要历史记录；
* 一个数据库文件免部署，契合本机单用户场景。

表设计：``jobs / stage_runs / events / api_calls / artifacts / qa_issues``。
schema 版本通过 ``PRAGMA user_version`` 管理，后续改动写迁移，而不是删库。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from videoforge.logging_utils import redact
from videoforge.schemas import JobStatus, LEGAL_TRANSITIONS

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    topic TEXT NOT NULL,
    status TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    stage TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    detail_json TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    ts TEXT NOT NULL,
    stage TEXT,
    from_status TEXT,
    to_status TEXT,
    message TEXT
);
CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    ts TEXT NOT NULL,
    provider TEXT NOT NULL,
    kind TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    estimate_cost_cny REAL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 1,
    redacted_error TEXT
);
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    path TEXT NOT NULL,
    type TEXT NOT NULL,
    origin TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    note TEXT DEFAULT '',
    UNIQUE(job_id, path)
);
CREATE TABLE IF NOT EXISTS qa_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    rework_round INTEGER NOT NULL DEFAULT 0,
    issue_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    scene_id TEXT,
    owner_agent TEXT NOT NULL,
    repair_instruction TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'open'
);
"""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class Database:
    """线程安全的 SQLite 封装（研究阶段会并发调用）。"""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA busy_timeout = 8000;")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            cur = self.conn.execute("PRAGMA user_version;")
            version = cur.fetchone()[0]
            if version == 0:
                self.conn.executescript(_SCHEMA_SQL)
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION};")
                self.conn.commit()
            # 未来：if version < 2: ... ALTER TABLE ...

    # ------------------------------------------------------------------ jobs
    def create_job(self, job_id: str, mode: str, topic: str, config: dict[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO jobs(job_id, mode, topic, status, config_json, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (job_id, mode, topic, JobStatus.CREATED.value,
                 json.dumps(config, ensure_ascii=False), now_iso(), now_iso()),
            )
            self.conn.commit()

    def transition(self, job_id: str, to_status: JobStatus, message: str = "",
                   stage: str | None = None) -> JobStatus:
        """带合法性校验的状态迁移；非法迁移直接报错，防止状态机被写坏。"""
        with self._lock:
            row = self.conn.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"job 不存在: {job_id}")
            current = JobStatus(row["status"])
            if to_status != current and to_status not in LEGAL_TRANSITIONS.get(current, set()):
                raise ValueError(f"非法状态迁移: {current.value} -> {to_status.value}")
            self.conn.execute(
                "UPDATE jobs SET status=?, updated_at=? WHERE job_id=?",
                (to_status.value, now_iso(), job_id),
            )
            self.conn.execute(
                "INSERT INTO events(job_id, ts, stage, from_status, to_status, message) "
                "VALUES (?,?,?,?,?,?)",
                (job_id, now_iso(), stage, current.value, to_status.value, redact(message)),
            )
            self.conn.commit()
            return current

    def reopen_job(self, job_id: str) -> None:
        """--resume 时把 completed/failed 任务重置为 created（留事件，便于审计）。"""
        with self._lock:
            row = self.conn.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            old = row["status"] if row else None
            self.conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE job_id=?",
                              (JobStatus.CREATED.value, now_iso(), job_id))
            self.conn.execute(
                "INSERT INTO events(job_id, ts, stage, from_status, to_status, message) "
                "VALUES (?,?,?,?,?,?)",
                (job_id, now_iso(), None, old, JobStatus.CREATED.value, "resume 重开任务"))
            self.conn.commit()

    def get_status(self, job_id: str) -> JobStatus:
        with self._lock:
            row = self.conn.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return JobStatus(row["status"]) if row else None  # type: ignore[return-value]

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT job_id, mode, topic, status, updated_at FROM jobs "
                "ORDER BY updated_at DESC LIMIT ?", (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------ stage runs
    def start_stage(self, job_id: str, stage: str, attempt: int = 1) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO stage_runs(job_id, stage, attempt, status, started_at) "
                "VALUES (?,?,?,'running',?)", (job_id, stage, attempt, now_iso()),
            )
            self.conn.commit()

    def end_stage(self, job_id: str, stage: str, ok: bool, detail: dict | None = None,
                  error: str = "") -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE stage_runs SET status=?, ended_at=?, detail_json=?, error=? "
                "WHERE id=(SELECT id FROM stage_runs WHERE job_id=? AND stage=? "
                "ORDER BY id DESC LIMIT 1)",
                ("ok" if ok else "failed", now_iso(),
                 json.dumps(detail or {}, ensure_ascii=False), redact(error), job_id, stage),
            )
            self.conn.commit()

    # ------------------------------------------------------------- api calls
    def record_api_call(self, *, provider: str, kind: str, prompt_tokens: int,
                        completion_tokens: int, estimate_cost_cny: float, ok: bool,
                        redacted_error: str = "") -> None:
        # job_id 由调用方在外部拼接；这里用线程局部变量更简单：见 set_job_context
        job_id = getattr(self, "_ctx_job_id", "global")
        with self._lock:
            self.conn.execute(
                "INSERT INTO api_calls(job_id, ts, provider, kind, prompt_tokens, "
                "completion_tokens, estimate_cost_cny, ok, redacted_error) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (job_id, now_iso(), provider, kind, prompt_tokens, completion_tokens,
                 estimate_cost_cny, 1 if ok else 0, redacted_error),
            )
            self.conn.commit()

    def set_job_context(self, job_id: str) -> None:
        self._ctx_job_id = job_id

    def usage_totals(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(prompt_tokens),0) p, "
                "COALESCE(SUM(completion_tokens),0) q, COALESCE(SUM(estimate_cost_cny),0) cost "
                "FROM api_calls WHERE job_id=? AND ok=1", (job_id,),
            ).fetchone()
            return {"calls": row["c"], "prompt_tokens": row["p"],
                    "completion_tokens": row["q"], "estimated_cost_cny": round(row["cost"], 4)}

    # -------------------------------------------------------------- artifacts
    def register_artifact(self, job_id: str, *, path: str, type: str, origin: str,
                          sha256: str, provider: str = "", model: str = "", note: str = "") -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO artifacts(job_id, path, type, origin, sha256, provider, model, created_at, note) "
                "VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(job_id, path) DO UPDATE SET "
                "origin=excluded.origin, sha256=excluded.sha256, note=excluded.note",
                (job_id, path, type, origin, sha256, provider, model, now_iso(), note),
            )
            self.conn.commit()

    def list_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT path, type, origin, sha256, provider, model, note, created_at "
                "FROM artifacts WHERE job_id=? ORDER BY id", (job_id,)).fetchall()]

    # -------------------------------------------------------------- qa issues
    def add_qa_issue(self, job_id: str, rework_round: int, issue: dict[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO qa_issues(job_id, rework_round, issue_id, severity, scene_id, "
                "owner_agent, repair_instruction, evidence, status) VALUES (?,?,?,?,?,?,?,?,?)",
                (job_id, rework_round, issue["issue_id"], issue["severity"],
                 issue.get("scene_id"), issue["owner_agent"], issue["repair_instruction"],
                 issue.get("evidence", ""), issue.get("status", "open")),
            )
            self.conn.commit()

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT ts, stage, from_status, to_status, message FROM events "
                "WHERE job_id=? ORDER BY id", (job_id,)).fetchall()]

    def close(self) -> None:
        with self._lock:
            self.conn.close()
