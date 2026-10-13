"""火山方舟图片 / 视频 / TTS Provider。

图片（Seedream，v1.2.0 起为**真实实现**）
------------------------------------------
``ArkImageProvider`` 调用火山方舟 **Agent Plan** 的同步生图接口
``POST {base_url}/images/generations``（OpenAI 兼容）。核心事实（2026-10，官方文档核实）：

* Agent Plan 专属 Base URL 路径含 ``/plan``：
  ``https://ark.cn-beijing.volces.com/api/plan/v3``；
* 使用 Agent Plan **专属 API Key**（Coding Plan Key 无法在 Agent Plan 调用）；
* 模型 ``doubao-seedream-5-0-pro``（文生图 ✓，分辨率 1K/2K，输出 png/jpeg）；
* 请求体 ``{model, prompt, size, output_format, response_format, watermark}``；
  seedream-5-0-pro **不接受** ``sequential_image_generation`` / ``stream``（传了会 400）；
* 同步接口：无 job_id、无轮询；``data[0].url``（临时签名 URL，约 24h 过期）或
  ``data[0].b64_json``（纯 base64）。本实现统一把结果**立即下载落盘**，
  避免临时 URL 过期；
* seedream-5-0-pro 约 2 分钟/张，客户端超时需 ≥240s。

未配置 ``ARK_IMAGE_MODEL`` 时仍抛 :class:`CapabilityUnavailable`，由 VisualAgent
走显式的 Pillow 信息卡回退——绝不把回退画面伪装成 AI 生成。

视频 / TTS 仍为未开通占位：让“能力是否存在”成为显式状态，工作流只能走被标记为
template/synthetic 的回退，无法悄悄伪造。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from tenacity import (retry, retry_if_exception, stop_after_attempt,
                      wait_exponential)

from videoforge.budget import BudgetTracker
from videoforge.logging_utils import get_logger, redact
from videoforge.providers.base import (CapabilityUnavailable, ProviderError,
                                       ProviderJob)

logger = get_logger("videoforge.ark.image")

# seedream-5-0-pro / 5-0-flash 这两个模型传 sequential_image_generation 或 stream 会 400，
# 其余版本可接受 "disabled"。为稳妥，Pro 系列一律不发这些字段。
_NO_SEQUENTIAL_MODELS = ("seedream-5-0-pro", "seedream-5-0-flash")


def _is_transient(exc: object) -> bool:
    return isinstance(exc, ProviderError) and exc.klass == "transient"


class ArkImageProvider:
    """火山方舟 Agent Plan Seedream 生图适配器。

    参数
    ----
    model     : 推理模型，如 ``doubao-seedream-5-0-pro``；留空视为未开通。
    api_key   : Agent Plan 专属 Key；留空视为未开通。
    base_url  : Agent Plan 专属 Base URL（路径含 /plan）。
    size/output_format/watermark/timeout : 见 config。
    budget    : 预算计量；成功一张计一次 ``kind="image"``（失败不计费、仅审计）。
    """

    provider_name = "volcengine_ark_seedream"

    def __init__(self, model: str = "", *, api_key: str = "",
                 base_url: str = "https://ark.cn-beijing.volces.com/api/plan/v3",
                 size: str = "2K", output_format: str = "png",
                 watermark: bool = False, timeout: float = 300.0,
                 budget: BudgetTracker | None = None):
        self.model = (model or "").strip()
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.size = size
        self.output_format = (output_format or "png").lower()
        self.watermark = watermark
        self.timeout = timeout
        self.budget = budget
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------- helpers
    @property
    def configured(self) -> bool:
        return bool(self.model and self.api_key)

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
            )
        return self._client

    def _record_failure(self, msg: str) -> None:
        if self.budget is None:
            return
        try:
            self.budget.record(provider=self.provider_name, kind="image",
                               ok=False, redacted_error=msg[:300])
        except Exception:  # noqa: BLE001 - 计量失败不得掩盖原始错误
            pass

    # --------------------------------------------------------------- call
    @retry(reraise=True, stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=2, max=30),
           retry=retry_if_exception(_is_transient))
    def _post_generation(self, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._ensure_client()
        try:
            resp = client.post("/images/generations", json=payload)
        except httpx.HTTPError as exc:
            err = ProviderError(f"网络错误: {redact(str(exc))}", "transient")
            self._record_failure(str(err))
            raise err
        if resp.status_code in (429, 500, 502, 503, 504):
            err = ProviderError(
                f"方舟生图临时错误 {resp.status_code}: {redact(resp.text[:300])}",
                "transient", resp.status_code)
            self._record_failure(str(err))
            raise err
        if resp.status_code in (401, 403):
            err = ProviderError(
                f"方舟生图鉴权失败 {resp.status_code}：请确认使用 Agent Plan 专属 Key 与 "
                f"专属 Base URL（含 /plan），且已开通 {self.model}",
                "permanent", resp.status_code)
            self._record_failure(str(err))
            raise err
        if resp.status_code >= 400:
            err = ProviderError(
                f"方舟生图错误 {resp.status_code}: {redact(resp.text[:300])}",
                "permanent", resp.status_code)
            self._record_failure(str(err))
            raise err
        return resp.json()

    def generate(self, prompt: str, out_path: Path | str,
                 *, size: str | None = None) -> str:
        """文生图并把结果落盘到 ``out_path``，返回落盘路径字符串。

        未配置能力时抛 :class:`CapabilityUnavailable`，由上层走 Pillow 回退。
        """
        if not self.configured:
            raise CapabilityUnavailable(
                "ark_image",
                "ARK_IMAGE_MODEL / ARK_IMAGE_API_KEY 未配置；需使用火山方舟 Agent Plan "
                "专属 Key 与专属 Base URL（含 /plan）调用 Seedream。已回退 Pillow 程序化信息卡。",
            )
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "size": size or self.size,
            "output_format": self.output_format,
            "response_format": "url",
            "watermark": self.watermark,
        }
        # 仅对支持的模型下发 sequential_image_generation（Pro/Flash 传了会 400）。
        if not any(tag in self.model for tag in _NO_SEQUENTIAL_MODELS):
            payload["sequential_image_generation"] = "disabled"

        data = self._post_generation(payload)
        items = data.get("data") or []
        if not items:
            err = ProviderError(f"方舟生图返回无 data：{redact(str(data)[:200])}",
                                "validation")
            self._record_failure(str(err))
            raise err
        item = items[0]

        # 结果可能是临时 URL 或 base64；统一立即下载/解码落盘（临时 URL 约 24h 过期）。
        if item.get("b64_json"):
            import base64
            out_path.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            try:
                img_resp = self._ensure_client().get(item["url"])
                img_resp.raise_for_status()
            except httpx.HTTPError as exc:
                err = ProviderError(f"下载生图结果失败: {redact(str(exc))}", "transient")
                self._record_failure(str(err))
                raise err
            out_path.write_bytes(img_resp.content)
        else:
            err = ProviderError("方舟生图 data[0] 既无 url 也无 b64_json", "validation")
            self._record_failure(str(err))
            raise err

        if self.budget is not None:
            # usage 字段各版本不稳定，这里只记一次成功的图片调用（计入硬预算与审计）。
            self.budget.record(provider=self.provider_name, kind="image")
        logger.info("Seedream 生图成功：%s (%d bytes)", out_path.name,
                    out_path.stat().st_size)
        return str(out_path)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


class ArkVideoProvider:
    def __init__(self, model: str = ""):
        self.model = model

    def submit(self, prompt: str, duration_sec: float = 5) -> ProviderJob:
        if not self.model:
            raise CapabilityUnavailable(
                "ark_video",
                "ARK_VIDEO_MODEL 未配置；异步视频任务不可用。已回退程序化画面。",
            )
        raise NotImplementedError("开通后在此实现 submit/poll/cancel 与 job_id 持久化")

    def poll(self, job: ProviderJob) -> ProviderJob:
        raise NotImplementedError


class ArkSpeechProvider:
    def __init__(self, model: str = ""):
        self.model = model

    def synthesize(self, text: str, voice: str = "") -> str:
        if not self.model:
            raise CapabilityUnavailable(
                "ark_tts",
                "ARK_TTS_MODEL 未配置；已回退本地 SAPI「Microsoft Huihui」真实语音，"
                "而非伪造云端 TTS。",
            )
        raise NotImplementedError("开通后在此实现音频内容生成接口")
