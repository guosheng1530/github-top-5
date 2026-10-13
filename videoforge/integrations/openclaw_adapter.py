"""OpenClaw 适配器（基于本机 2026.4.11 实测命令）。

已核实事实
----------
* ``openclaw --version`` → ``OpenClaw 2026.4.11 (c836fd2)``；
* Gateway 默认 ``ws://127.0.0.1:18789``，配置文件 ``~/.openclaw/openclaw.json``；
* 健康检查：``openclaw health --json``（网关未运行时 1006 异常闭合并退出非 0）；
* 投递一次 Agent 对话：``openclaw agent --json --timeout <s> -m <text>``。

Windows 注意：npm 安装的可执行文件真正能被 CreateProcess 启动的是
``openclaw.cmd`` 垫片，因此这里按 ``.cmd`` → 无后缀顺序解析。

边界：核心视频流水线不依赖 OpenClaw。适配器只做 (1) 安装探测
(2) 网关健康检查 (3) 显式 opt-in（``OPENCLAW_NOTIFY=1``）后的完成通知。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from videoforge.logging_utils import get_logger

logger = get_logger("videoforge.openclaw")


def _resolve() -> str | None:
    """返回可在当前平台被 subprocess 直接启动的命令名。"""
    if sys.platform.startswith("win"):
        for cand in ("openclaw.cmd", "openclaw.exe", "openclaw.bat", "openclaw"):
            if shutil.which(cand):
                return cand
        return None
    return shutil.which("openclaw")


class OpenClawAdapter:
    def __init__(self, notify_enabled: bool = False):
        self.notify_enabled = notify_enabled
        self.cmd = _resolve()

    def detect(self) -> dict:
        if not self.cmd:
            return {"installed": False, "version": None, "path": None}
        try:
            out = subprocess.run([self.cmd, "--version"], capture_output=True,
                                 text=True, timeout=20, shell=False)
            head = (out.stdout or out.stderr).strip().splitlines()[0]
            # 形如：🦞 OpenClaw 2026.4.11 (c836fd2) — ...
            parts = head.split()
            version = next((p.strip("()") for p in parts
                            if any(ch.isdigit() for ch in p) and "." in p), head)
        except Exception as exc:
            return {"installed": True, "version": f"检测失败: {exc}",
                    "path": shutil.which(self.cmd)}
        return {"installed": True, "version": version.strip(),
                "path": shutil.which(self.cmd)}

    def gateway_health(self) -> dict:
        if not self.cmd:
            return {"online": False, "detail": "openclaw 未安装/不在 PATH"}
        proc = subprocess.run([self.cmd, "health", "--json", "--timeout", "4000"],
                              capture_output=True, text=True, timeout=30, shell=False)
        if proc.returncode == 0:
            try:
                return {"online": True,
                        "detail": json.loads(proc.stdout.strip().splitlines()[-1])}
            except Exception:
                return {"online": True, "detail": proc.stdout.strip()[-300:]}
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return {"online": False,
                "detail": ("网关未运行（" + (tail[0] if tail else "无输出") + "）")[:200]}

    def notify_completion(self, job_id: str, video_path: str, passed: bool) -> dict:
        if not self.notify_enabled:
            return {"sent": False,
                    "reason": "未设置 OPENCLAW_NOTIFY=1，默认不触发外部 Agent turn"}
        health = self.gateway_health()
        if not health["online"]:
            return {"sent": False, "reason": f"网关离线: {health['detail']}"}
        msg = (f"[AgentVideoForge] 任务 {job_id} 已完成，QA {'通过' if passed else '有未决问题'}，"
               f"成片：{video_path}")
        proc = subprocess.run(
            [self.cmd, "agent", "--json", "--timeout", "90", "-m", msg],
            capture_output=True, text=True, timeout=120, shell=False)
        return {"sent": proc.returncode == 0,
                "detail": (proc.stdout or proc.stderr)[-300:]}
