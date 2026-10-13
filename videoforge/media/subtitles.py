"""SRT 字幕：按分镜实际音频时长构造时间轴。

同步原理
--------
视频分段是“一镜一音频”，因此每镜边界就是天然时间锚点。镜内没有词级时间戳，
我们按每个字幕块的字数比例切分镜内时长（中文口播语速与字数近似成正比）。
若将来接入带字级时间戳的 TTS（如部分云端 TTS 的 SSML bookmark），
可在 :func:`build_srt` 处替换为真实时间戳，其它代码不用改。
"""

from __future__ import annotations

import re
from pathlib import Path

from videoforge.schemas import SubtitleCue, SubtitleFile

# 句读标点：先按这些切句，再按最大字数二次切分
_PUNCT = "。！？；!?;，、,.:："
_MAX_CHARS = 20


def _chunk_text(text: str, max_chars: int = _MAX_CHARS) -> list[str]:
    pieces: list[str] = []
    buf = ""
    for ch in re.sub(r"\s+", "", text):
        buf += ch
        if ch in _PUNCT and len(buf) >= 6:
            pieces.append(buf)
            buf = ""
        elif len(buf) >= max_chars:
            pieces.append(buf)
            buf = ""
    if buf:
        pieces.append(buf)
    return pieces


def _fmt_ts(t: float) -> str:
    if t < 0:
        t = 0
    ms = int(round((t - int(t)) * 1000))
    s = int(t)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_scene_cues(text: str, dur: float, start_index: int = 1,
                     time_offset: float = 0.0) -> list[SubtitleCue]:
    """单镜头内的 cue 列表；time_offset=0 即片段本地时间轴（供逐段烧录用）。"""
    chunks = _chunk_text(text) or [""]
    total_chars = sum(max(1, len(c)) for c in chunks)
    cues: list[SubtitleCue] = []
    local = 0.0
    idx = start_index
    for c in chunks:
        cd = dur * max(1, len(c)) / total_chars
        cue = SubtitleCue(
            index=idx,
            start_sec=round(time_offset + local, 3),
            end_sec=round(time_offset + local + cd - 0.04, 3),
            text=c,
        )
        if cue.end_sec <= cue.start_sec:
            cue.end_sec = cue.start_sec + 0.3
        cues.append(cue)
        local += cd
        idx += 1
    return cues


def build_srt(scenes: list, scene_durations: list[float]) -> SubtitleFile:
    """scenes: StoryboardScene 列表；scene_durations: 每镜实测秒数（全局时间轴）。"""
    cues: list[SubtitleCue] = []
    cursor = 0.0
    idx = 1
    for scene, dur in zip(scenes, scene_durations):
        scene_cues = build_scene_cues(scene.voiceover, dur, idx, cursor)
        cues.extend(scene_cues)
        idx += len(scene_cues)
        cursor += dur
    return SubtitleFile(cues=cues)


def render_srt(cues: list[SubtitleCue]) -> str:
    """渲染成 SRT 文本（无 BOM；libass 直接吃 UTF-8）。"""
    lines: list[str] = []
    for cue in cues:
        lines.append(str(cue.index))
        lines.append(f"{_fmt_ts(cue.start_sec)} --> {_fmt_ts(cue.end_sec)}")
        lines.append(cue.text)
        lines.append("")
    return "\n".join(lines)


def write_scene_srt(cues: list[SubtitleCue], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_srt(cues), encoding="utf-8")
    return out_path


def write_srt(sub: SubtitleFile, out_path: Path) -> Path:
    lines = []
    for cue in sub.cues:
        lines.append(str(cue.index))
        lines.append(f"{_fmt_ts(cue.start_sec)} --> {_fmt_ts(cue.end_sec)}")
        lines.append(cue.text)
        lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 with BOM：部分 Windows 播放器对无 BOM 的中文字幕识别不佳
    out_path.write_bytes(chr(0xFEFF).encode("utf-8") + "\n".join(lines).encode("utf-8"))
    return out_path


def validate_srt(sub: SubtitleFile, total_duration: float) -> list[str]:
    """返回发现的问题列表；空列表 = 通过。"""
    problems: list[str] = []
    prev_end = -1.0
    for cue in sub.cues:
        if cue.end_sec <= cue.start_sec:
            problems.append(f"cue {cue.index} 时长非正")
        if cue.start_sec + 1e-6 < prev_end:
            problems.append(f"cue {cue.index} 与上一条时间重叠")
        if cue.start_sec < -0.01 or cue.end_sec > total_duration + 0.6:
            problems.append(f"cue {cue.index} 超出视频时间轴")
        prev_end = cue.end_sec
    return problems
