"""媒体层测试：信息卡渲染、SRT 时间轴、FFmpeg 真实合成 smoke test。"""

import subprocess
from pathlib import Path

import pytest

from videoforge.media import cards, ffmpeg_tools
from videoforge.media.subtitles import build_srt, validate_srt, write_srt
from videoforge.schemas import StoryboardScene

pytestmark = pytest.mark.slow


def _scene(kind, sid, voice, **card):
    return StoryboardScene(scene_id=sid, section_index=0, voiceover=voice,
                           visual_type=kind, card_data=card)


def test_all_card_types_render(tmp_path):
    scenes = [
        _scene("title_card", "s0", "开场字幕测试", title="标题", subtitle="副标题"),
        _scene("ranking_card", "s1", "榜单字幕", items=[
            {"name": "a/b", "stars": 1000, "score": 80},
            {"name": "c/d", "stars": 500, "score": 60}]),
        _scene("project_card", "s2", "项目卡片字幕", rank=1, name="o/repo",
               stars=1234, forks=12, language="Python", license="MIT",
               one_liner="一句话定位", bullets=["特性一", "特性二"],
               url="https://github.com/o/repo"),
        _scene("section_card", "s3", "章节字幕", title="章节标题"),
        _scene("end_card", "s4", "结尾字幕", lines=["声明一", "声明二"]),
    ]
    for s in scenes:
        out = tmp_path / f"{s.scene_id}.png"
        cards.render_scene_image(s, out, width=640, height=360)
        assert out.stat().st_size > 5000


def test_srt_timing_and_validation(tmp_path):
    scenes = [_scene("title_card", "s0", "第一句，比较短。"),
              _scene("end_card", "s1", "第二句内容稍长一些，用来测试时间分配。")]
    sub = build_srt(scenes, [2.0, 4.0])
    assert sub.cues[0].start_sec == 0.0
    assert abs(sub.cues[-1].end_sec - 6.0) < 0.2
    assert validate_srt(sub, total_duration=6.0) == []
    path = write_srt(sub, tmp_path / "sub.srt")
    assert b"1\n" in path.read_bytes()


def test_srt_detects_overrun():
    scenes = [_scene("title_card", "s0", "测试。")]
    sub = build_srt(scenes, [2.0])
    problems = validate_srt(sub, total_duration=1.0)  # 视频比字幕短
    assert any("超出视频时间轴" in p for p in problems)


def test_ffmpeg_segment_and_concat_roundtrip(tmp_path):
    # 两张卡 + 两条 2 秒提示音 → 两个片段 → concat → ffprobe 验证
    img_dir, seg_dir = tmp_path / "img", tmp_path / "seg"
    img_dir.mkdir(); seg_dir.mkdir()
    segments = []
    for i in range(2):
        scene = _scene("title_card", f"s{i}", f"镜头{i}")
        img = img_dir / f"{i}.png"
        cards.render_scene_image(scene, img, 640, 360)
        audio = tmp_path / f"a{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                        "-c:a", "pcm_s16le", str(audio)],
                       capture_output=True, timeout=60, shell=False)
        seg = seg_dir / f"{i}.mp4"
        ffmpeg_tools.build_scene_segment(img, audio, seg, 2.0, width=640, height=360)
        segments.append(seg)
    final = tmp_path / "final.mp4"
    ffmpeg_tools.concat_segments(segments, final, seg_dir)

    info = ffmpeg_tools.video_stream_info(final)
    assert info["codec"] == "h264" and info["width"] == 640 and abs(info["fps"] - 30) < 0.1
    assert ffmpeg_tools.has_audio_stream(final)
    assert abs(ffmpeg_tools.duration_of(final) - 4.0) < 0.4
    vol = ffmpeg_tools.mean_volume_db(final)
    assert vol is not None and vol > -40  # 440Hz 正弦音明显可闻
