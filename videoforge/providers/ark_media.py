"""火山方舟图片 / 视频 / TTS Provider —— 当前账号**未开通**的占位实现。

为什么保留“会报错”的代码？
1. 让“能力是否存在”成为显式状态（``CapabilityUnavailable``），
   工作流只能走被标记为 template/synthetic 的回退，无法悄悄伪造；
2. 将来在控制台开通后，在这里补真实 HTTP 调用即可，Agent 层不变；
3. 教学：真实媒体 API 是 *异步* 的（submit -> 保存 job_id -> 轮询 -> 下载），
   接口签名已经按此预留。
"""

from __future__ import annotations

from videoforge.providers.base import CapabilityUnavailable, ProviderJob


class ArkImageProvider:
    def __init__(self, model: str = ""):
        self.model = model

    def generate(self, prompt: str, size: str = "1920x1080") -> str:
        if not self.model:
            raise CapabilityUnavailable(
                "ark_image",
                "ARK_IMAGE_MODEL 未配置；当前 Key 属于 Coding Plan (api/plan/v3)，"
                "标准 /api/v3 图像接口返回 401。已回退 Pillow 程序化信息卡。",
            )
        raise NotImplementedError("开通后在此实现 images/generations 真实调用")


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
