"""Agent 基类与运行上下文。"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videoforge.budget import BudgetTracker
from videoforge.config import Settings
from videoforge.db import Database
from videoforge.logging_utils import get_logger
from videoforge.providers.ark_text import ArkTextClient
from videoforge.providers.github_client import GitHubClient
from videoforge.providers.tts import TTSChain
from videoforge.schemas import StageName
from videoforge.providers.base import ProviderError

import logging


@dataclass
class AgentContext:
    """一次 Job 内所有 Agent 共享的上下文（依赖注入，便于测试替换）。"""

    job_id: str
    settings: Settings
    db: Database
    budget: BudgetTracker
    job_dir: Path
    logger: logging.Logger

    llm: ArkTextClient | None = None
    github: GitHubClient | None = None
    tts: TTSChain | None = None

    @property
    def assets_dir(self) -> Path:
        p = self.job_dir / "assets"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def research_dir(self) -> Path:
        p = self.job_dir / "research"
        p.mkdir(parents=True, exist_ok=True)
        return p


class BaseAgent:
    """所有专业 Agent 的基类。

    子类声明：
    * ``name`` / ``stage``：身份与状态机阶段；
    * ``system_prompt``：独立角色指令；
    * ``allowed_tools``：工具白名单——名字也许看起来“只是文档”，
      但它同时是代码审查清单：``run()`` 里出现白名单外的副作用即属违约。
    """

    name: str = "base"
    stage: StageName
    system_prompt: str = ""
    allowed_tools: tuple[str, ...] = ()
    timeout_sec: float = 180

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self.logger = ctx.logger

    def _llm_json(self, user_prompt: str, *, max_tokens: int = 3000,
                  temperature: float = 0.5) -> dict[str, Any]:
        """对白名单外能力的调用一律视为编程错误。"""
        if self.ctx.llm is None:
            raise ProviderError(f"{self.name} 需要 LLM，但当前为离线/demo 模式",
                                "capability")
        self.logger.info("[%s] 调用方舟文本 (tools=%s)", self.name, self.allowed_tools)
        return self.ctx.llm.chat_json(self.system_prompt, user_prompt,
                                      max_tokens=max_tokens, temperature=temperature)

    def run(self, payload: Any) -> Any:  # pragma: no cover - 抽象方法
        raise NotImplementedError
