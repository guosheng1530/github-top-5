"""制作线 4 个 Agent：Visual / Voice / Render / QA。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from videoforge.agents.base import BaseAgent
from videoforge.agents.prompts import QA_PROMPT, RENDER_PROMPT, VISUAL_PROMPT, VOICE_PROMPT
from videoforge.artifacts import register
from videoforge.media import cards, ffmpeg_tools
from videoforge.media.subtitles import (build_scene_cues, build_srt,
                                        validate_srt, write_scene_srt, write_srt)
from videoforge.schemas import (QualityReport, QAIssue, StageName, Storyboard,
                                SubtitleFile)


class VisualAgent(BaseAgent):
    name = "visual_asset_agent"
    stage = StageName.VISUAL
    system_prompt = VISUAL_PROMPT
    allowed_tools = ("pillow.render_card", "filesystem.write_asset")
    timeout_sec = 180

    def run(self, storyboard: Storyboard) -> dict[str, Path]:
        img_dir = self.ctx.assets_dir / "images"
        images: dict[str, Path] = {}
        for i, scene in enumerate(storyboard.scenes):
            out = img_dir / f"{scene.scene_id}.png"
            cards.render_scene_image(
                scene, out,
                width=self.ctx.settings.video_width,
                height=self.ctx.settings.video_height)
            images[scene.scene_id] = out
            register(self.ctx.db, self.ctx.job_id, out, type="image", origin="template",
                     provider="pillow", note=f"{scene.visual_type} 程序化信息卡",
                     root=self.ctx.job_dir)
        # 封面缩略图：用第一镜（标题卡）渲染 1280x720 版本
        thumb = self.ctx.job_dir / "thumbnail.png"
        first = storyboard.scenes[0]
        cards.render_thumbnail(first.card_data.get("title", ""),
                               first.card_data.get("subtitle", ""), thumb)
        register(self.ctx.db, self.ctx.job_id, thumb, type="thumbnail", origin="template",
                 provider="pillow", root=self.ctx.job_dir)
        self.logger.info("视觉完成：%d 张信息卡 + 封面", len(images))
        return images


class VoiceAgent(BaseAgent):
    name = "voice_subtitle_agent"
    stage = StageName.VOICE
    system_prompt = VOICE_PROMPT
    allowed_tools = ("tts.synthesize", "ffprobe.duration", "subtitles.write_srt")
    timeout_sec = 900

    def run(self, storyboard: Storyboard) -> tuple[dict[str, Path], dict[str, str], SubtitleFile]:
        audio_dir = self.ctx.assets_dir / "audio"
        audio_paths: dict[str, Path] = {}
        origins: dict[str, str] = {}
        durations: list[float] = []
        for scene in storyboard.scenes:
            target = audio_dir / f"{scene.scene_id}.wav"
            path, origin, provider = self.ctx.tts.synthesize(scene.voiceover, target)
            audio_paths[scene.scene_id] = path
            origins[scene.scene_id] = f"{origin}:{provider}"
            dur = ffmpeg_tools.duration_of(path)
            scene.duration_sec = round(dur, 3)  # 以实测音频时长回填分镜
            durations.append(scene.duration_sec)
            register(self.ctx.db, self.ctx.job_id, path, type="audio", origin=origin,
                     provider=provider, note=f"{scene.scene_id} 旁白",
                     root=self.ctx.job_dir)
        sub = build_srt(storyboard.scenes, durations)
        srt_path = self.ctx.job_dir / "subtitles.srt"
        write_srt(sub, srt_path)
        register(self.ctx.db, self.ctx.job_id, srt_path, type="subtitle", origin="real",
                 provider="local", note="按实测音频时长生成", root=self.ctx.job_dir)
        n_real = sum(1 for o in origins.values() if o.startswith("real"))
        self.logger.info("配音完成：真实语音 %d/%d；总时长 %.1f 秒",
                         n_real, len(origins), sum(durations))
        return audio_paths, origins, sub


class RenderAgent(BaseAgent):
    name = "video_render_agent"
    stage = StageName.RENDER
    system_prompt = RENDER_PROMPT
    allowed_tools = ("ffmpeg.build_segment", "ffmpeg.concat", "ffprobe.inspect")
    timeout_sec = 1800

    def run(self, payload: tuple[Storyboard, dict[str, Path]]) -> Path:
        storyboard, audio_paths = payload
        seg_dir = self.ctx.assets_dir / "segments"
        seg_dir.mkdir(parents=True, exist_ok=True)
        segments: list[Path] = []
        for scene in storyboard.scenes:
            image = self.ctx.assets_dir / "images" / f"{scene.scene_id}.png"
            audio = audio_paths[scene.scene_id]
            seg = seg_dir / f"{scene.scene_id}.mp4"
            # 每镜一份片段本地时间轴 SRT（从 0 开始），交给 libass 烧录
            srt = seg_dir / f"{scene.scene_id}.srt"
            write_scene_srt(build_scene_cues(scene.voiceover, scene.duration_sec), srt)
            ffmpeg_tools.build_scene_segment(
                image, audio, seg, scene.duration_sec,
                width=self.ctx.settings.video_width,
                height=self.ctx.settings.video_height,
                fps=self.ctx.settings.fps,
                fade=(scene.transition == "fade"),
                subtitle_path=srt)
            segments.append(seg)
        final = self.ctx.job_dir / "final_video.mp4"
        ffmpeg_tools.concat_segments(segments, final, seg_dir)
        register(self.ctx.db, self.ctx.job_id, final, type="video", origin="real",
                 provider="ffmpeg", note="确定性合成（素材来源见 manifest）",
                 root=self.ctx.job_dir)
        info = ffmpeg_tools.video_stream_info(final)
        self.logger.info("渲染完成：%s (%sx%s, %.1f fps)",
                         final.name, info.get("width"), info.get("height"), info.get("fps", 0))
        return final


class QAAgent(BaseAgent):
    name = "quality_review_agent"
    stage = StageName.QA
    system_prompt = QA_PROMPT
    allowed_tools = ("ffprobe.inspect", "ffmpeg.astats", "subtitles.validate", "db.query")
    timeout_sec = 600

    def run(self, payload: tuple[Storyboard, Path, dict[str, str], SubtitleFile],
            rework_round: int = 0) -> QualityReport:
        storyboard, final, audio_origins, sub = payload
        s = self.ctx.settings
        issues: list[QAIssue] = []
        checks: dict[str, bool] = {}

        probe = ffmpeg_tools.probe(final)
        vinfo = next((x for x in probe.get("streams", []) if x["codec_type"] == "video"), {})
        ainfo = next((x for x in probe.get("streams", []) if x["codec_type"] == "audio"), {})
        duration = float(probe["format"]["duration"])

        checks["video_h264"] = vinfo.get("codec_name") == "h264"
        checks["resolution"] = (int(vinfo.get("width", 0)), int(vinfo.get("height", 0))) == (
            s.video_width, s.video_height)
        num, _, den = vinfo.get("r_frame_rate", "0/1").partition("/")
        fps = float(num) / float(den or 1)
        checks["fps"] = abs(fps - s.fps) < 1.0
        checks["audio_present"] = bool(ainfo)
        checks["audio_aac"] = ainfo.get("codec_name") in ("aac", "mp4a")

        volume = ffmpeg_tools.mean_volume_db(final) if ainfo else None
        checks["audio_audible"] = volume is not None and volume > -45

        srt_problems = validate_srt(sub, duration)
        checks["srt_timeline"] = not srt_problems

        # 每个上榜项目都应在口播中被点名
        names = [sc.card_data.get("name", "") for sc in storyboard.scenes
                 if sc.visual_type == "project_card"]
        joined_voice = "".join(sc.voiceover for sc in storyboard.scenes)
        missing = [n for n in names if n.split("/")[-1].lower() not in joined_voice.lower()]
        checks["all_projects_narrated"] = not missing

        target = s.target_duration_sec
        checks["duration_in_range"] = target * 0.5 <= duration <= target * 1.6

        asset_origins = Counter()
        for art in self.ctx.db.list_artifacts(self.ctx.job_id):
            asset_origins[art["origin"]] += 1
        synthetic_scenes = [k for k, v in audio_origins.items() if v.startswith("synthetic")]
        checks["no_synthetic_audio"] = not synthetic_scenes

        # ---- 形成问题单 ----
        def add(sev, owner, instruction, evidence, sid=None):
            issues.append(QAIssue(
                issue_id=f"qa-r{rework_round}-{len(issues)+1:03d}", severity=sev,
                scene_id=sid, owner_agent=owner, repair_instruction=instruction,
                evidence=evidence, retry_count=rework_round))

        if not checks["video_h264"]:
            add("high", "video_render_agent", "重新编码为 H.264", f"实际编码 {vinfo.get('codec_name')}")
        if not checks["resolution"]:
            add("high", "video_render_agent", "重新缩放到目标分辨率",
                f"{vinfo.get('width')}x{vinfo.get('height')}")
        if not checks["fps"]:
            add("medium", "video_render_agent", "统一帧率", f"实际 {fps:.1f}fps")
        if not checks["audio_present"]:
            add("high", "voice_subtitle_agent", "重新合成并映射音轨", "成片无音频流")
        elif not checks["audio_audible"]:
            add("high", "voice_subtitle_agent", "重新合成旁白（疑似静音）",
                f"RMS={volume} dB", )
        for p in srt_problems:
            add("medium", "voice_subtitle_agent", "修复字幕时间轴", p)
        if missing:
            add("medium", "script_agent", "补全缺失项目的口播段落", "未点名：" + ",".join(missing))
        if not checks["duration_in_range"]:
            add("low", "script_agent", "下次调整脚本长度",
                f"时长 {duration:.0f}s，目标 {target:.0f}s（允许 0.5x~1.6x）")
        if synthetic_scenes:
            add("medium", "voice_subtitle_agent",
                "这些镜头使用了合成提示音轨，请在接入真实 TTS 后重跑配音",
                ",".join(synthetic_scenes))
        for issue in issues:
            self.ctx.db.add_qa_issue(self.ctx.job_id, rework_round, issue.model_dump())

        high = [i for i in issues if i.severity == "high"]
        report = QualityReport(
            passed=not high, duration_sec=round(duration, 2),
            video_codec=vinfo.get("codec_name", ""), audio_codec=ainfo.get("codec_name", ""),
            width=int(vinfo.get("width", 0)), height=int(vinfo.get("height", 0)),
            fps=round(fps, 2), audio_mean_volume_db=volume,
            issues=issues, asset_origins=dict(asset_origins),
            checks=checks, rework_round=rework_round)
        self.logger.info("QA 第 %d 轮：%s（高优先级问题 %d 个）",
                         rework_round, "通过" if report.passed else "不通过", len(high))
        return report
