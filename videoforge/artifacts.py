"""产物落盘与登记工具：文件 -> SHA-256 -> SQLite artifacts 表 -> ArtifactRef。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from videoforge.db import Database, now_iso


def sha256_file(path: Path, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def save_json(obj, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def register(db: Database, job_id: str, path: Path, *, type: str, origin: str,
             provider: str = "", model: str = "", note: str = "",
             root: Path | None = None) -> dict:
    """计算哈希、登记 DB，返回可放进 manifest 的字典。"""
    digest = sha256_file(path)
    db.register_artifact(job_id, path=str(path.relative_to(root)) if root else str(path),
                         type=type, origin=origin, sha256=digest,
                         provider=provider, model=model, note=note)
    return {"path": str(path.relative_to(root)) if root else str(path),
            "type": type, "origin": origin, "sha256": digest,
            "provider": provider, "model": model, "created_at": now_iso(), "note": note}
