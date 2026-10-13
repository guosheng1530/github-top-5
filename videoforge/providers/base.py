"""Provider 通用类型与异常。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ErrorClass = Literal["transient", "permanent", "validation", "capability"]


class ProviderError(RuntimeError):
    """带错误分类的 Provider 异常，Agent 据此决定重试/修复/中止。"""

    def __init__(self, message: str, klass: ErrorClass = "transient", status_code: int | None = None):
        super().__init__(message)
        self.klass = klass
        self.status_code = status_code


class CapabilityUnavailable(ProviderError):
    """能力未开通/未配置。工作流必须走显式回退，绝不允许伪装成功。"""

    def __init__(self, capability: str, reason: str):
        super().__init__(f"能力不可用 [{capability}]：{reason}", klass="capability")
        self.capability = capability
        self.reason = reason


@dataclass
class ProviderJob:
    """异步媒体任务句柄：必须持久化，超时先查询再决定是否重发（防重复扣费）。"""

    job_id: str
    provider: str
    model: str
    status: Literal["submitted", "processing", "succeeded", "failed", "timeout"] = "submitted"
    request_hash: str | None = None
    result_path: str | None = None
