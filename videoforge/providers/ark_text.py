"""火山方舟文本 Provider（OpenAI 兼容 /chat/completions）。

已用真实请求核实的事实（2026-10-12，本机 Key）：
* Base URL 来自环境变量 ``LLM_BASE_URL``，本 Key 为 Coding Plan：
  ``https://ark.cn-beijing.volces.com/api/plan/v3``；
* 模型路由名 ``ark-code-latest``，返回体与 OpenAI 兼容，含 ``usage``
  （该模型还会输出 ``reasoning_content`` 推理 token）；
* 标准方舟端点 ``/api/v3`` 对此 Key 返回 401，因此图片/视频/TTS 不在本适配器范围。

可靠性策略：
* 429 / 5xx / 网络错误：tenacity 指数退避重试；
* 401/400：permanent，不重试；
* 要求 JSON 输出时：解析失败带错误信息让模型“修复一次”，仍失败则 validation 错误；
* 每次调用计量 usage 并上报预算；任何异常文本都经过日志脱敏。
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from tenacity import (retry, retry_if_exception, stop_after_attempt,
                      wait_exponential)


def _is_transient(exc: object) -> bool:
    """只有 transient 错误才重试；permanent/validation 直接失败，避免无效等待与重复计费。"""
    return isinstance(exc, ProviderError) and exc.klass == "transient"

from videoforge.budget import BudgetTracker
from videoforge.logging_utils import get_logger, redact
from videoforge.providers.base import ProviderError

logger = get_logger("videoforge.ark")

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)```$", re.DOTALL | re.IGNORECASE)


class ArkTextClient:
    def __init__(self, *, api_key: str, base_url: str, model: str,
                 budget: BudgetTracker, timeout: float = 120.0):
        if not api_key:
            raise ProviderError("缺少 LLM_API_KEY", klass="permanent")
        self.model = model
        self.budget = budget
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    # ------------------------------------------------------------- low level
    # 实测本机网络对方舟长连接有约 1/3~2/3 的 TLS 握手重置（Clash TUN 路由波动），
    # 4 次重试在坏窗口内仍可能全灭；放宽到 6 次、退避上限 30s。
    @retry(reraise=True, stop=stop_after_attempt(6),
           wait=wait_exponential(multiplier=1, min=2, max=30),
           retry=retry_if_exception(_is_transient))
    def _post_chat(self, messages: list[dict[str, str]], *, max_tokens: int = 2500,
                   temperature: float = 0.7) -> dict[str, Any]:
        self.budget.check_before_call()
        payload = {"model": self.model, "messages": messages,
                   "max_tokens": max_tokens, "temperature": temperature}
        try:
            resp = self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            err = ProviderError(f"网络错误: {redact(str(exc))}", "transient")
            self._record_failure(str(err))
            raise err
        if resp.status_code in (429, 500, 502, 503, 504):
            err = ProviderError(f"方舟临时错误 {resp.status_code}: {redact(resp.text[:300])}",
                                "transient", resp.status_code)
            self._record_failure(str(err))
            raise err
        if resp.status_code in (401, 403):
            err = ProviderError(f"方舟鉴权失败 {resp.status_code}：检查 Key / Endpoint 权限",
                                "permanent", resp.status_code)
            self._record_failure(str(err))
            raise err
        if resp.status_code >= 400:
            err = ProviderError(f"方舟错误 {resp.status_code}: {redact(resp.text[:300])}",
                                "permanent", resp.status_code)
            self._record_failure(str(err))
            raise err
        data = resp.json()
        usage = data.get("usage") or {}
        self.budget.record(
            provider="volcengine_ark", kind="chat",
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        return data

    def _record_failure(self, redacted_message: str) -> None:
        """失败调用同样落库（ok=0）：审计口径是“尝试过的调用”，不是只记成功。"""
        try:
            self.budget.record(provider="volcengine_ark", kind="chat",
                               ok=False, redacted_error=redacted_message[:300])
        except Exception:  # noqa: BLE001 - 计量失败绝不能掩盖原始错误
            pass

    # ---------------------------------------------------------------- public
    def chat(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 2500,
             temperature: float = 0.7) -> str:
        """纯文本对话。"""
        data = self._post_chat(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": user_prompt}],
            max_tokens=max_tokens, temperature=temperature,
        )
        return data["choices"][0]["message"]["content"].strip()

    def chat_json(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 3000,
                  temperature: float = 0.5) -> dict[str, Any]:
        """要求模型只返回 JSON 对象。解析失败带校验错误修复一次。"""
        sys_prompt = system_prompt + (
            "\n\n【输出格式硬性要求】只输出一个合法 JSON 对象，不要输出 Markdown 代码块、"
            "注释或任何解释文字；所有字符串使用双引号；中文直接写，不要转义成 \\uXXXX。"
        )
        try:
            content = self.chat(sys_prompt, user_prompt, max_tokens=max_tokens,
                                temperature=temperature)
            return self._parse_json(content)
        except ProviderError as parse_exc:
            if parse_exc.klass != "validation":
                raise
            detail = str(parse_exc)
        # 修复一次：把解析错误回喂模型
        repair = (f"你上次的输出无法被 json.loads 解析：{detail}\n"
                  "请只输出修复后的完整 JSON 对象，不要解释。")
        content = self.chat(sys_prompt, user_prompt + "\n\n" + repair,
                            max_tokens=max_tokens, temperature=temperature)
        return self._parse_json(content)

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        text = content.strip()
        fence = _FENCE_RE.match(text)
        if fence:
            text = fence.group(1).strip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            # 兜底：截取第一个 { 到最后一个 }
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                try:
                    result = json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    raise ProviderError(f"JSON 解析失败: {exc}", "validation")
            else:
                raise ProviderError(f"JSON 解析失败: {exc}", "validation")
        if not isinstance(result, dict):
            raise ProviderError("模型返回的 JSON 顶层不是对象", "validation")
        return result

    def close(self) -> None:
        self._client.close()
