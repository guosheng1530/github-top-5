"""结构化日志与密钥脱敏。

* :func:`redact` 会在所有日志写出前把 Key/Token 替换成 ``***REDACTED***``，
  即使上游不小心把异常信息带进来也不会泄漏。
* :class:`JobLogger` 同时输出到控制台（人类可读）和任务目录下的 JSONL（机器可审计）。
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path

# ark-xxxx / Bearer xxxx / github_pat_xxxx / ghp_xxxx 等形态
_SECRET_PATTERNS = [
    re.compile(r"ark-[A-Za-z0-9\-]{6,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{6,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{6,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{6,}"),
    re.compile(r"(?i)(authorization[\"'\s:=]+)[A-Za-z0-9\-._~+/]{8,}"),
]


def redact(text: str) -> str:
    """把文本中的凭据替换为掩码。**任何日志出口都必须先经过本函数。**"""
    if not text:
        return text
    out = str(text)
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: m.group(0).split()[0][:3] + "***REDACTED***"
                      if m.group(0).lower().startswith(("bea", "aut")) else "***REDACTED***", out)
    return out


class JsonlAuditHandler(logging.Handler):
    """把日志事件落成 JSONL，便于事后审计（脱敏后再写）。"""

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "logger": record.name,
                "message": redact(record.getMessage()),
            }
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:  # 审计日志失败不能影响主流程
            self.handleError(record)


def get_logger(name: str = "videoforge", audit_path: Path | None = None, verbose: bool = True) -> logging.Logger:
    """获取一个配置好的 logger；同一 name 重复获取不会重复加 handler。"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, JsonlAuditHandler) for h in logger.handlers):
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                                          datefmt="%H:%M:%S"))
        sh.addFilter(lambda r: setattr(r, "msg", redact(str(r.msg))) or True)
        sh.setLevel(logging.INFO if verbose else logging.WARNING)
        logger.addHandler(sh)
    if audit_path and not any(getattr(h, "path", None) == audit_path for h in logger.handlers):
        logger.addHandler(JsonlAuditHandler(audit_path))
    return logger
