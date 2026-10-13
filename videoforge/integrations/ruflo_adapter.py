"""Ruflo 适配器 —— 严格按事实实现，宁可报告“未接入”也不猜测。

核查记录（2026-10-12）
----------------------
* 蓝图写的仓库是 https://github.com/ruvnet/ruflo；
* 本机 ``ruflo`` 命令不存在；
* npm registry 上确有 ``ruflo`` 包（3.56.7，MIT），但其 ``repository.url`` 指向
  **github.com/ruvnet/claude-flow**（``npm view ruflo repository.url`` 实测）。
  即：npm 包名 ruflo 与 Claude Flow 同源，是围绕 Claude Code 的 swarm/flow CLI，
  并不是可被 Python 进程直接 import 的 Agent 运行库。

因此本适配器的真实职责到“探测与文档化”为止：
* 核心流水线以独立模式运行（蓝图允许并要求这一点）；
* 若将来要接入，正路是：安装 CLI → 用 ``ruflo --help`` 核实子命令 →
  以子进程方式触发其 swarm，再把结果文件交回本工作流；
  绝不能凭包名猜 HTTP 路径或 MCP 工具名。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from videoforge.logging_utils import get_logger

logger = get_logger("videoforge.ruflo")

_NPM = "npm.cmd" if sys.platform.startswith("win") else "npm"


class RufloAdapter:
    PACKAGE = "ruflo"

    def detect(self) -> dict:
        exe = shutil.which("ruflo")
        return {"installed": bool(exe), "path": exe,
                "npm_package": self.PACKAGE,
                "repository": "https://github.com/ruvnet/claude-flow（npm view 实测）",
                "license": "MIT",
                "blueprint_url": "https://github.com/ruvnet/ruflo（蓝图记录，需进一步核实）"}

    def inspect_npm(self) -> dict:
        """联网查看 npm 上的包元数据（安装决策前的事实核查）。"""
        try:
            proc = subprocess.run(
                [_NPM, "view", self.PACKAGE, "version", "repository.url", "license",
                 "--json"], capture_output=True, text=True, timeout=40, shell=False)
            if proc.returncode == 0:
                return json.loads(proc.stdout)
            return {"error": proc.stderr[-200:]}
        except FileNotFoundError:
            return {"error": "npm 不在 PATH"}
        except Exception as exc:
            return {"error": str(exc)}

    def trigger(self, *_args, **_kwargs) -> dict:
        """未核实前拒绝触发任何东西。"""
        info = self.detect()
        if not info["installed"]:
            return {"triggered": False,
                    "reason": "ruflo 未安装；且其 CLI 语义未经 help 核实，拒绝猜测式调用"}
        raise NotImplementedError("已检测到安装；请先实现并核实 `ruflo --help` 再接入")
