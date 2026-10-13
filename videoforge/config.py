"""配置加载：从项目根目录的 ``.env`` 读取密钥与开关。

教学要点
--------
* **为什么不用把密钥写进代码？** 代码会被提交、分享、截图；``.env`` 在 ``.gitignore``
  中，只存在于本机。
* 本模块自带一个极简 .env 解析器（不引入额外依赖）。真实项目也可以用
  ``python-dotenv``，原理相同：解析键值对 -> 写入 ``os.environ``。
* 能力开关（图片/视频/TTS 模型名）留空即为 ``not_configured``，
  对应 Provider 会抛出 :class:`~videoforge.providers.base.CapabilityUnavailable`，
  工作流据此走明确的回退路径，而不是伪造成功。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output"


def load_dotenv(path: Path | None = None) -> None:
    """把 ``.env`` 中的 KEY=VALUE 注入 ``os.environ``（不覆盖已存在的环境变量）。

    这样既支持 .env 文件，也支持 CI/Shell 里直接设置环境变量，后者优先级更高。
    """
    env_path = path or (PROJECT_ROOT / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Settings:
    """运行期配置。所有密钥只保存在内存里，日志层负责脱敏。"""

    # ---- 火山方舟文本（OpenAI 兼容协议）----
    ark_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    ark_base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    )
    ark_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "ark-code-latest"))
    # 单次 HTTP 读超时（秒）。推理模型生成长 JSON（如 4000 token 编剧稿）可能需要数分钟，
    # 120s 会在网络层误杀本来正常的请求；超时只触发 transient 重试。
    ark_timeout: float = field(default_factory=lambda: float(os.getenv("ARK_TIMEOUT", "300")))

    # ---- GitHub ----
    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))

    # ---- 未开通的媒体能力（留空 = not_configured）----
    ark_image_model: str = field(default_factory=lambda: os.getenv("ARK_IMAGE_MODEL", ""))
    ark_video_model: str = field(default_factory=lambda: os.getenv("ARK_VIDEO_MODEL", ""))
    ark_tts_model: str = field(default_factory=lambda: os.getenv("ARK_TTS_MODEL", ""))

    # ---- 视频参数（蓝图默认：中文、16:9、1080p、30fps、约 5 分钟）----
    video_width: int = field(default_factory=lambda: int(os.getenv("VIDEO_WIDTH", "1920")))
    video_height: int = field(default_factory=lambda: int(os.getenv("VIDEO_HEIGHT", "1080")))
    fps: int = field(default_factory=lambda: int(os.getenv("VIDEO_FPS", "30")))
    target_duration_sec: float = field(
        default_factory=lambda: float(os.getenv("TARGET_DURATION_SEC", "300"))
    )

    # ---- 配音 ----
    # auto：优先 edge-tts（更自然，需联网且未被风控），失败回退 SAPI 离线语音，
    # 再失败才使用 ffmpeg 生成“明确标记的合成静音/提示音”。
    tts_engine: str = field(default_factory=lambda: os.getenv("TTS_ENGINE", "sapi"))
    tts_voice: str = field(default_factory=lambda: os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural"))
    sapi_voice_keyword: str = field(default_factory=lambda: os.getenv("SAPI_VOICE_KEYWORD", "HUIHUI"))
    sapi_rate: int = field(default_factory=lambda: int(os.getenv("SAPI_RATE", "150")))

    # ---- 研究范围 ----
    candidate_pool: int = field(default_factory=lambda: int(os.getenv("CANDIDATE_POOL", "8")))
    research_parallel: int = field(default_factory=lambda: int(os.getenv("RESEARCH_PARALLEL", "3")))
    min_stars: int = field(default_factory=lambda: int(os.getenv("MIN_STARS", "800")))
    pushed_within_days: int = field(default_factory=lambda: int(os.getenv("PUSHED_WITHIN_DAYS", "90")))

    # ---- 预算（硬预算达到即停止新的付费请求；默认值很宽松）----
    hard_budget_calls: int = field(default_factory=lambda: int(os.getenv("HARD_BUDGET_CALLS", "120")))
    hard_budget_tokens: int = field(default_factory=lambda: int(os.getenv("HARD_BUDGET_TOKENS", "2_000_000")))
    # 估算单价（元 / 1K tokens）。Coding Plan 多为套餐制，默认 0 仅记录用量，
    # 报告中会明确“估算不等于真实账单”。
    price_input_per_1k: float = field(default_factory=lambda: float(os.getenv("PRICE_INPUT_PER_1K", "0")))
    price_output_per_1k: float = field(default_factory=lambda: float(os.getenv("PRICE_OUTPUT_PER_1K", "0")))

    # ---- 本地 API（FastAPI）----
    local_api_host: str = field(default_factory=lambda: os.getenv("LOCAL_API_HOST", "127.0.0.1"))
    local_api_port: int = field(default_factory=lambda: int(os.getenv("LOCAL_API_PORT", "8765")))
    local_api_token: str = field(default_factory=lambda: os.getenv("LOCAL_API_TOKEN", ""))

    # ---- 路径 ----
    output_root: Path = field(default_factory=lambda: OUTPUT_ROOT)

    @property
    def image_capability_configured(self) -> bool:
        return bool(self.ark_image_model.strip())

    @property
    def video_capability_configured(self) -> bool:
        return bool(self.ark_video_model.strip())

    @property
    def tts_capability_configured(self) -> bool:
        return bool(self.ark_tts_model.strip())


_settings: Settings | None = None


def get_settings() -> Settings:
    """全局单例。首次调用时加载 .env。"""
    global _settings
    if _settings is None:
        load_dotenv()
        _settings = Settings()
        _settings.output_root.mkdir(parents=True, exist_ok=True)
    return _settings
