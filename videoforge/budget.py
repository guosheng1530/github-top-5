"""预算与调用计量。

三级防护：
1. 每次 LLM 调用前后检查 *硬预算*（调用次数 / token 总量），超限直接拒绝新请求；
2. 超过 *软预算*（硬预算的 80%）只告警；
3. 每次调用都落库（``api_calls`` 表），成本可审计、可复算。

媒体生成类请求的“防重复扣费”不在这里——那是 Provider 层的幂等职责
（保存 provider job ID、超时先查状态再决定是否重发），重试库不能替代它。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class BudgetExceeded(RuntimeError):
    """硬预算超限：工作流必须停止发起新的付费请求。"""


class UsageSink(Protocol):
    def record_api_call(self, *, provider: str, kind: str, prompt_tokens: int,
                        completion_tokens: int, estimate_cost_cny: float,
                        ok: bool, redacted_error: str = "") -> None: ...


@dataclass
class BudgetTracker:
    hard_calls: int
    hard_tokens: int
    price_input_per_1k: float = 0.0
    price_output_per_1k: float = 0.0

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    sink: UsageSink | None = None
    warnings: list[str] = field(default_factory=list)

    SOFT_RATIO = 0.8

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def estimated_cost_cny(self) -> float:
        return round(
            self.prompt_tokens / 1000 * self.price_input_per_1k
            + self.completion_tokens / 1000 * self.price_output_per_1k,
            4,
        )

    def check_before_call(self) -> None:
        """发起付费请求前调用。"""
        if self.calls >= self.hard_calls:
            raise BudgetExceeded(f"硬预算：LLM 调用次数已达 {self.hard_calls}")
        if self.total_tokens >= self.hard_tokens:
            raise BudgetExceeded(f"硬预算：token 用量已达 {self.hard_tokens}")

    def record(self, *, provider: str, kind: str, prompt_tokens: int = 0,
               completion_tokens: int = 0, ok: bool = True,
               redacted_error: str = "") -> None:
        """记录一次真实返回了 usage 的调用。"""
        self.calls += 1
        self.prompt_tokens += max(0, prompt_tokens)
        self.completion_tokens += max(0, completion_tokens)
        cost = (
            max(0, prompt_tokens) / 1000 * self.price_input_per_1k
            + max(0, completion_tokens) / 1000 * self.price_output_per_1k
        )
        if self.sink:
            self.sink.record_api_call(
                provider=provider, kind=kind,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                estimate_cost_cny=round(cost, 4), ok=ok, redacted_error=redacted_error,
            )
        soft_calls = self.hard_calls * self.SOFT_RATIO
        soft_tokens = self.hard_tokens * self.SOFT_RATIO
        if self.calls == int(soft_calls) or (soft_tokens and self.total_tokens >= soft_tokens
                                             and len(self.warnings) < 2):
            self.warnings.append(f"软预算提醒：calls={self.calls}, tokens={self.total_tokens}")

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_cny": self.estimated_cost_cny,
            "hard_calls": self.hard_calls,
            "hard_tokens": self.hard_tokens,
            "warnings": self.warnings,
        }
