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
        duration = max(2.5, min(60.0, len(text) / 3.5))
        # 0.5s 880Hz 提示音（两次），其余静音，明确可听辨这是占位音轨
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"anullsrc=r=44100:cl=stereo:d={duration:.2f}",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=0.4",
            "-filter_complex",
            "[1:a]volume=0.15[beep];[0:a][beep]overlay=0.5:0[a1];"
            f"[a1][beep]overlay={duration - 1.0:.2f}:0[a]",
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
