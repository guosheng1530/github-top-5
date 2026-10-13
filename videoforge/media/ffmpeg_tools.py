"""FFmpeg / ffprobe 封装：确定性的媒体变换工具。

安全约定（必须遵守）：
* 永远用参数数组 + ``shell=False``，绝不把用户/LLM 文本拼进 shell 命令字符串；
* ffmpeg 是“工具”不是 Agent：做什么由工作流决定，ffmpeg 只负责精确执行；
* 所有产物用 ffprobe 读真实轨道元数据验收，不能只看文件扩展名。

分段策略：每个分镜 = 一张信息卡 PNG + 一条配音 → 独立 MP4（统一 1920x1080、
30fps、yuv420p、AAC 44.1kHz），再用 concat demuxer 无损拼接，避免一条超长
filter graph 难以排错。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from videoforge.logging_utils import get_logger

logger = get_logger("videoforge.ffmpeg")


class FFmpegError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run(cmd: list[str], timeout: int = 600) -> str:
    logger.info("运行：%s", " ".join(cmd[:8]) + (" ..." if len(cmd) > 8 else ""))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
    if proc.returncode != 0:
        raise FFmpegError(f"命令失败({proc.returncode}): {' '.join(cmd[:6])}\n{proc.stderr[-800:]}")
    return proc.stdout


def probe(path: Path) -> dict:
    """返回 ffprobe 的 streams/format 信息。"""
    if not Path(path).exists():
        raise FFmpegError(f"文件不存在: {path}")
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=60, shell=False,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe 失败: {proc.stderr[-400:]}")
    return json.loads(proc.stdout)


def duration_of(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def video_stream_info(path: Path) -> dict:
    for s in probe(path).get("streams", []):
        if s.get("codec_type") == "video":
            num, _, den = s.get("r_frame_rate", "30/1").partition("/")
            fps = float(num) / float(den or 1)
            return {"codec": s.get("codec_name"), "width": s.get("width"),
                    "height": s.get("height"), "fps": fps}
    return {}


def has_audio_stream(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))


def mean_volume_db(path: Path) -> float | None:
    """整段平均响度（dB，越小越安静；纯静音为 -91 左右，无音频返回 None）。"""
    proc = subprocess.run(
        ["ffmpeg", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=300, shell=False,
    )
    for line in proc.stderr.splitlines():
        if "mean_volume:" in line:
            value = line.split("mean_volume:")[1].strip().split(" ")[0]
            try:
                return float(value)
            except ValueError:
                return None
    return None


def _libass_path(p: Path) -> str:
    """libass filtergraph 路径转义：正斜杠 + 转义盘符冒号。"""
    return str(Path(p)).replace("\\", "/").replace(":", "\\:")


def build_scene_segment(image: Path, audio: Path, out: Path, duration: float, *,
                        width: int = 1920, height: int = 1080, fps: int = 30,
                        fade: bool = True, subtitle_path: Path | None = None) -> Path:
    """一镜：静态信息卡 + 配音 → 标准化 MP4 片段。

    subtitle_path 给定时，用 libass 在片段本地时间轴上烧录该镜 SRT
    （这才是观众实际看到的动态字幕；卡片 PNG 不再内嵌字幕）。
    """
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p"
    )
    if subtitle_path is not None:
        style = ("FontName=Microsoft YaHei,Fontsize=20,Bold=1,"
                 "PrimaryColour=&H00FFFFFF,OutlineColour=&H00101820,"
                 "BorderStyle=1,Outline=1,Shadow=0,BackColour=&H78000000,MarginV=30")
        vf += (f",subtitles='{_libass_path(subtitle_path)}':fontsdir='{_libass_path(Path('C:/Windows/Fonts'))}'"
               f":force_style='{style}'")
    if fade and duration > 1.2:
        vf += f",fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, duration - 0.4):.2f}:d=0.4"
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(fps), "-i", str(image),
        "-i", str(audio),
        "-filter_complex",
        f"[0:v]{vf}[v];[1:a]aresample=44100,aformat=channel_layouts=stereo,apad,atrim=duration={duration:.3f}[a]",
        "-map", "[v]", "-map", "[a]",
        # 静态信息卡运动极少，veryfast + crf20 与 medium 观感几乎无差，编码快数倍
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{duration:.3f}", "-shortest", str(out),
    ]
    _run(cmd, timeout=300)
    return out


def concat_segments(segments: list[Path], out: Path, work_dir: Path) -> Path:
    """concat demuxer 拼接（编码参数一致时可直接 -c copy，秒级完成）。"""
    list_file = work_dir / "concat.txt"
    list_file.write_text(
        "".join(f"file '{s.name}'\n" for s in segments), encoding="utf-8"
    )
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
           "-c", "copy", str(out)]
    try:
        _run(cmd, timeout=600)
    except FFmpegError:
        # 极端情况下时间戳不齐 → 退回 concat filter 重编码
        logger.warning("concat demuxer 失败，回退 concat filter 重编码")
        inputs: list[str] = []
        for s in segments:
            inputs += ["-i", str(s)]
        n = len(segments)
        streams = "".join(f"[{i}:v][{i}:a]" for i in range(n))
        cmd = ["ffmpeg", "-y"] + inputs + [
            "-filter_complex",
            f"{streams}concat=n={n}:v=1:a=1[v][a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-c:a", "aac", "-b:a", "128k", str(out),
        ]
        _run(cmd, timeout=1200)
    return out
