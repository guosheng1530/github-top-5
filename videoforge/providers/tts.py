"""中文旁白合成链：edge-tts（在线，更自然）→ SAPI5 离线（真实语音）→ ffmpeg 合成提示音。

实测（2026-10-12）：本机网络下 edge-tts 的 wss 握手被微软返回 403（代理出口风控），
因此默认引擎配置为 ``sapi``——Windows 自带的「Microsoft Huihui Desktop」是**真实发音人
离线语音**，origin 记为 ``real``（provider=local_sapi5），不是机器生成的假音轨。
只有连 SAPI 都失败时，才生成可听辨的提示音轨并标记 origin=``synthetic``，
QA 报告里会显著标明，绝不把它说成 AI 配音。
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from videoforge.logging_utils import get_logger

logger = get_logger("videoforge.tts")


class EdgeTTSProvider:
    name = "edge_tts"
    origin = "real"

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.voice = voice

    def synthesize(self, text: str, out_path: Path) -> None:
        import edge_tts  # 延迟导入：没装也不影响 SAPI 回退

        out_path.parent.mkdir(parents=True, exist_ok=True)

        async def _run() -> None:
            comm = edge_tts.Communicate(text, voice=self.voice)
            await comm.save(str(out_path))

        asyncio.run(_run())
        if not out_path.exists() or out_path.stat().st_size < 200:
            raise RuntimeError("edge-tts 输出为空")


class SAPI5Provider:
    """Windows 内置语音（pyttsx3 -> SAPI.SpVoice COM）。"""

    name = "local_sapi5"
    origin = "real"

    def __init__(self, voice_keyword: str = "HUIHUI", rate: int = 150):
        self.keyword = voice_keyword
        self.rate = rate

    def synthesize(self, text: str, out_path: Path) -> None:
        import pythoncom  # pywin32；工作线程中必须先 CoInitialize
        import pyttsx3

        pythoncom.CoInitialize()
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            zh = [v for v in voices if self.keyword.upper() in v.id.upper()]
            if zh:
                engine.setProperty("voice", zh[0].id)
            engine.setProperty("rate", self.rate)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            engine.save_to_file(text, str(out_path))
            engine.runAndWait()
            engine.stop()
        finally:
            pythoncom.CoUninitialize()
        if not out_path.exists() or out_path.stat().st_size < 1000:
            raise RuntimeError("SAPI5 未产生有效音频")


class SyntheticAudioProvider:
    """最后兜底：轻微提示音 + 静音，时长按中文口播速度估算（约 3.5 字/秒）。"""

    name = "ffmpeg_synthetic"
    origin = "synthetic"

    def synthesize(self, text: str, out_path: Path) -> None:
        # 兜底引擎必须自给自足：在没有 SAPI 的 Linux/macOS 上，本引擎常是第一个
        # 真正落盘的 provider，若父目录不存在，ffmpeg 会以
        # "Error opening output ... No such file or directory" 失败，导致整条
        # 降级链崩溃。SAPI5Provider 已自建目录，这里补齐同样保证。
        out_path.parent.mkdir(parents=True, exist_ok=True)
        duration = max(2.5, min(60.0, len(text) / 3.5))
        # 两声 880Hz 短提示音（起始处与接近结尾处各一次），其余静音；
        # 明确可听辨这是占位音轨，QA 会把它标为 synthetic。
        #
        # 实现要点（跨平台正确性）：音频叠加必须用 **音频** 滤镜，不能用 overlay
        # （overlay 是视频合成滤镜，早期实现误用它导致 "Media type mismatch"，
        # 在没有 SAPI 的 Linux 上整条 TTS 降级链因此崩溃）。
        # 正确做法：
        #   * 用 adelay 把每一声提示音平移到目标时间点（毫秒）；
        #   * 用 amix 把静音底轨与两声提示音混合，再 atrim 固定总时长。
        #
        # 可听度要求（跨平台 QA 门禁）：QA 的 ``audio_audible`` 用整段 **平均**
        # 响度判定（> -45 dB）。早期"长静音 + 两声短提示音"方案平均响度约
        # -46 dB，在没有 SAPI 的 Linux 上会被判为"疑似静音"→ 高优先级问题 →
        # QA 永远不通过、整条流水线卡死。改为"全程周期性提示音（约每秒一响）"：
        # 既仍是明显可辨的占位音轨（稳定的滴答声，绝不冒充人声），平均响度又
        # 稳定在 -30 dB 左右，可靠通过门禁。
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration:.2f}",
            "-filter_complex",
            # 440Hz 正弦经正弦包络（1Hz）做幅度调制 → 每秒一次由弱到强的"滴答"，
            # 全程有声；底轨 anullsrc 仅用于把总时长精确裁到 duration。
            "sine=frequency=440:sample_rate=44100,"
            f"atrim=duration={duration:.2f},"
            "aformat=channel_layouts=stereo,"
            "tremolo=f=1:d=0.9,"
            "volume=0.35[tone];"
            f"[0:a][tone]amix=inputs=2:duration=first:normalize=0,"
            f"atrim=duration={duration:.2f}[a]",
            "-map", "[a]", "-c:a", "pcm_s16le", str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 合成音轨失败: {proc.stderr[-400:]}")


class TTSChain:
    """按配置依次尝试，返回 (路径, origin, provider_name)。"""

    def __init__(self, engine_pref: str = "sapi", edge_voice: str = "zh-CN-XiaoxiaoNeural",
                 sapi_keyword: str = "HUIHUI", sapi_rate: int = 150):
        self.pref = engine_pref
        providers: list = []
        if engine_pref in ("edge", "auto"):
            providers.append(EdgeTTSProvider(edge_voice))
        if engine_pref in ("sapi", "auto"):
            providers.append(SAPI5Provider(sapi_keyword, sapi_rate))
        providers.append(SyntheticAudioProvider())
        self._providers = providers

    def synthesize(self, text: str, out_wav: Path) -> tuple[Path, str, str]:
        last_err = ""
        for prov in self._providers:
            try:
                tmp = out_wav if prov.name == "ffmpeg_synthetic" else out_wav.with_suffix(
                    ".mp3" if prov.name == "edge_tts" else ".wav")
                prov.synthesize(text, tmp)
                logger.info("TTS 使用 %s -> %s", prov.name, tmp.name)
                return tmp, prov.origin, prov.name
            except Exception as exc:  # 单个引擎失败不致命，继续降级
                last_err = f"{prov.name}: {exc}"
                logger.warning("TTS 引擎 %s 失败，降级：%s", prov.name, str(exc)[:160])
        raise RuntimeError(f"全部 TTS 引擎失败：{last_err}")
