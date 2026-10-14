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
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output"


# --------------------------------------------------------------------------- #
# 跨平台中文字体发现
# --------------------------------------------------------------------------- #
# 为什么不再把字体路径写死成 ``C:/Windows/Fonts/msyh.ttc``？
#   原始实现只在 Windows 可用；在 Linux/macOS 上该文件不存在，Pillow 的
#   ``ImageFont.truetype`` 会抛 OSError，整个视觉阶段崩溃。这里按优先级探测
#   常见 CJK 字体（Windows 雅黑/黑体 → Noto CJK → 文泉驿 → macOS 苹方），
#   并允许用 ``CJK_FONT_REGULAR`` / ``CJK_FONT_BOLD`` 环境变量显式覆盖。
#   找不到任何中文字体时返回 None，由调用方给出清晰的、可诊断的错误，
#   而不是在渲染第一张卡时才神秘崩溃。

# (常规字体候选, 粗体字体候选)——粗体缺失时回退常规。
_CJK_REGULAR_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",            # 微软雅黑 (Windows)
    "C:/Windows/Fonts/simhei.ttf",          # 黑体 (Windows)
    # Debian/Ubuntu（fonts-noto-cjk / fonts-wqy-*）
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",       # 文泉驿正黑
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",     # 文泉驿微米黑
    "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
    # RHEL/Rocky/AlmaLinux/Fedora/CentOS（google-noto-sans-cjk-ttc-fonts / wqy-zenhei-fonts）
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    # Arch Linux（noto-fonts-cjk / wqy-zenhei）
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/wenquanyi/wqy-zenhei.ttc",
    # macOS（系统自带）
    "/System/Library/Fonts/PingFang.ttc",   # 苹方 (macOS)
    "/System/Library/Fonts/STHeiti Medium.ttc",
]
_CJK_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/msyhbd.ttc",          # 微软雅黑 Bold (Windows)
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    # RHEL/Rocky/Fedora
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/google-noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
]


def _first_existing(candidates: list[str], env_override: str | None = None) -> str | None:
    if env_override:
        p = os.getenv(env_override, "").strip()
        if p and Path(p).exists():
            return p
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _fontconfig_match() -> str | None:
    """用 fontconfig 的 ``fc-match`` 发现任意已安装的 CJK 字体。

    为什么需要这个兜底？
      硬编码路径永远跟不上所有发行版的打包差异（Debian/RHEL/Arch 的 Noto CJK
      安装目录各不相同；用户还可能装了其它中文字体）。只要系统装了 fontconfig
      （几乎所有带桌面/字体的 Linux 都有），``fc-match`` 就能按字符集返回一个
      能渲染中文的真实字体文件路径，彻底摆脱对固定目录的依赖。
      macOS 装了 fontconfig（如 brew）也适用；Windows 一般没有，走上面的候选表。
    """
    import shutil
    import subprocess

    if shutil.which("fc-match") is None:
        return None
    # 请求一个包含中文字形的字体：:lang=zh-cn 让 fontconfig 只在支持简中的字体里挑
    for query in ("Noto Sans CJK SC:lang=zh-cn", ":lang=zh-cn", ":lang=zh"):
        try:
            out = subprocess.run(
                ["fc-match", "-f", "%{file}", query],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:  # noqa: BLE001 - 兜底发现失败不致命
            return None
        path = out.stdout.strip()
        if path and Path(path).exists():
            return path
    return None


def resolve_cjk_font(bold: bool = False) -> str | None:
    """返回可用的中文字体文件绝对路径；都找不到返回 None。

    解析优先级：
      1. 环境变量 ``CJK_FONT_REGULAR`` / ``CJK_FONT_BOLD``（显式覆盖，最高）；
      2. 跨平台已知路径候选表（Windows/各 Linux 发行版/macOS）；
      3. ``fc-match`` fontconfig 动态发现（通用兜底，摆脱硬编码目录）。
    """
    if bold:
        return (_first_existing(_CJK_BOLD_CANDIDATES, "CJK_FONT_BOLD")
                or _first_existing(_CJK_REGULAR_CANDIDATES, "CJK_FONT_REGULAR")
                or _fontconfig_match())
    return (_first_existing(_CJK_REGULAR_CANDIDATES, "CJK_FONT_REGULAR")
            or _fontconfig_match())


def cjk_fontsdir() -> str | None:
    """libass ``fontsdir`` 用的目录：取已解析字体文件所在目录。"""
    f = resolve_cjk_font(False)
    return str(Path(f).parent) if f else None


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

    # ---- 火山方舟 Agent Plan 图片生成（Seedream，v1.2.0 新增）----
    # 重要：Agent Plan 使用**专属** Base URL（路径含 /plan）与**专属** API Key，
    # 二者均不同于标准方舟 /api/v3，也不同于 Coding Plan 的 Key；混用会 401 或产生额外费用。
    #   * ARK_IMAGE_MODEL   留空 = not_configured（VisualAgent 自动回退 Pillow 信息卡）；
    #                       开通 Agent Plan 生图后填 `doubao-seedream-5-0-pro`。
    #   * ARK_IMAGE_API_KEY 留空则回退到 LLM_API_KEY（仅当两者同属 Agent Plan 时才正确）。
    #   * ARK_IMAGE_BASE_URL 默认 Agent Plan 专属端点。
    ark_image_model: str = field(default_factory=lambda: os.getenv("ARK_IMAGE_MODEL", ""))
    ark_image_base_url: str = field(
        default_factory=lambda: os.getenv(
            "ARK_IMAGE_BASE_URL", "https://ark.cn-beijing.volces.com/api/plan/v3"))
    ark_image_api_key: str = field(
        default_factory=lambda: os.getenv("ARK_IMAGE_API_KEY", "")
        or os.getenv("LLM_API_KEY", ""))
    # size 取 1K/1.5K/2K 预设或精确像素（如 2048x1152 的 16:9）。seedream-5-0-pro 仅支持
    # 1K/2K 预设；默认用 2K 兼顾清晰度与速度（横图由模型按内容选比例，若需固定 16:9 用精确像素）。
    ark_image_size: str = field(default_factory=lambda: os.getenv("ARK_IMAGE_SIZE", "2K"))
    ark_image_output_format: str = field(
        default_factory=lambda: os.getenv("ARK_IMAGE_OUTPUT_FORMAT", "png"))
    # 商用成片通常关水印；默认关闭（显式 false），需要可用 ARK_IMAGE_WATERMARK=1 打开。
    ark_image_watermark: bool = field(
        default_factory=lambda: os.getenv("ARK_IMAGE_WATERMARK", "0").strip().lower()
        in ("1", "true", "yes", "on"))
    # seedream-5-0-pro 实测约 2 分钟/张，客户端超时需 ≥240s。
    ark_image_timeout: float = field(
        default_factory=lambda: float(os.getenv("ARK_IMAGE_TIMEOUT", "300")))
    # 画面来源策略：auto=有配置就用 Seedream、失败回退 Pillow；pillow=强制程序化信息卡；
    # seedream=强制生图（未配置则抛 CapabilityUnavailable，不回退——用于验证真实接入）。
    image_provider: str = field(
        default_factory=lambda: os.getenv("IMAGE_PROVIDER", "auto").strip().lower())
    # Seedream 失败是否回退 Pillow（仅在 image_provider=auto 时生效）。
    image_fallback_to_template: bool = field(
        default_factory=lambda: os.getenv("IMAGE_FALLBACK_TO_TEMPLATE", "1").strip().lower()
        not in ("0", "false", "no", "off"))

    # ---- 其余未开通的媒体能力（留空 = not_configured）----
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
    # 引擎选择按平台自适应（可用 TTS_ENGINE 覆盖）：
    #   * Windows：默认 'sapi'——系统自带「Huihui」离线真实中文语音；
    #   * 其他平台（Linux/macOS）：默认 'auto'——SAPI5 不存在，优先 edge-tts
    #     （需联网），失败再降级到显式标记的合成提示音轨。
    # 'auto' 语义：edge-tts → SAPI5 → 合成音轨，逐级降级。
    tts_engine: str = field(
        default_factory=lambda: os.getenv(
            "TTS_ENGINE", "sapi" if sys.platform == "win32" else "auto"))
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

    # ---- 企业微信群机器人通知（默认关闭；显式 opt-in）----
    # WECHAT_NOTIFY=1 且 WECHAT_WEBHOOK_URL 配置后，任务完成会推送一条文本通知。
    # 获取方式：企业微信群 → 右上角 → 添加群机器人 → 复制 Webhook 地址
    #   （形如 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx）。
    wechat_notify: bool = field(
        default_factory=lambda: os.getenv("WECHAT_NOTIFY", "0").strip().lower()
        in ("1", "true", "yes", "on"))
    wechat_webhook_url: str = field(
        default_factory=lambda: os.getenv("WECHAT_WEBHOOK_URL", ""))

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

    @property
    def cjk_font_path(self) -> str | None:
        """当前环境可用的中文字体文件路径（找不到返回 None）。"""
        return resolve_cjk_font(False)


_settings: Settings | None = None


def get_settings() -> Settings:
    """全局单例。首次调用时加载 .env。"""
    global _settings
    if _settings is None:
        load_dotenv()
        _settings = Settings()
        _settings.output_root.mkdir(parents=True, exist_ok=True)
    return _settings
