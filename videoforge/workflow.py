"""工作流控制器：视频业务 DAG、状态机、预算、检查点恢复与 QA 返工。

它和 Ruflo/OpenClaw 的分工（见技术说明书 1.2）：
* 本控制器 = 业务最终状态（research_done / rendered / qa_failed / completed…），
  以 SQLite 为唯一权威；
* OpenClaw/Ruflo = 入口/Agent 协作平台，不允许各自宣布“视频已完成”。

阶段顺序（含并行与门禁）：
Discovery → Research(并行) → FactCheck(强制门禁) → Ranking → Script →
Storyboard → Visual ∥ Voice → Render → QA（最多两轮定向返工）→ Completed
"""

from __future__ import annotations

import json
import time
import traceback
import uuid
from pathlib import Path

from videoforge.agents.creative import ScriptAgent, StoryboardAgent
from videoforge.agents.intelligence import (DiscoveryAgent, FactCheckAgent,
                                            RankingAgent, ResearchAgent)
from videoforge.agents.production import (QAAgent, RenderAgent, VisualAgent,
                                          VoiceAgent)
from videoforge.artifacts import register, save_json
from videoforge.budget import BudgetTracker
from videoforge.config import Settings, get_settings
from videoforge.db import Database
from videoforge.integrations.openclaw_adapter import OpenClawAdapter
from videoforge.integrations.ruflo_adapter import RufloAdapter
from videoforge.logging_utils import get_logger, redact
from videoforge.agents.base import AgentContext
from videoforge.schemas import JobStatus, StageName


class Workflow:
    def __init__(self, *, settings: Settings | None = None, mode: str = "real",
                 job_id: str | None = None, topic: str = "近期热门 AI Agent 开源项目 Top 5",
                 llm=None, github=None, tts=None, image_provider=None, logger=None):
        self.settings = settings or get_settings()
        self.mode = mode
        self.job_id = job_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.topic = topic
        self.settings.output_root.mkdir(parents=True, exist_ok=True)
        self.job_dir = self.settings.output_root / self.job_id
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.settings.output_root / "videoforge.db")
        self.db.set_job_context(self.job_id)
        self.logger = logger or get_logger(
            "videoforge", audit_path=self.job_dir / "run.log.jsonl")
        self.budget = BudgetTracker(
            hard_calls=self.settings.hard_budget_calls,
            hard_tokens=self.settings.hard_budget_tokens,
            price_input_per_1k=self.settings.price_input_per_1k,
            price_output_per_1k=self.settings.price_output_per_1k,
            sink=self.db)
        self.llm = llm
        self.github = github
        self.tts = tts
        self.image_provider = image_provider
        self._closed = False
        self.ctx = AgentContext(
            job_id=self.job_id, settings=self.settings, db=self.db,
            budget=self.budget, job_dir=self.job_dir, logger=self.logger,
            llm=llm, github=github, tts=tts, image_provider=image_provider)

    def close(self) -> None:
        """释放外部资源：SQLite 连接、HTTP 客户端。

        原实现把 DB 连接交给进程生命周期，在单次 CLI 调用里问题不大，但在
        多任务、--resume、FastAPI 常驻进程或测试里会累积未关闭的连接；
        Windows 上未关闭的 SQLite 连接还会持有文件锁，影响后续访问。
        幂等：重复调用安全。
        """
        if self._closed:
            return
        self._closed = True
        for obj in (self.llm, self.github, self.image_provider):
            try:
                if obj is not None and hasattr(obj, "close"):
                    obj.close()
            except Exception:  # noqa: BLE001 清理阶段不抛
                pass
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "Workflow":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------- helpers
    def _to(self, status: JobStatus, stage: str | None = None, msg: str = "") -> None:
        before = self.db.get_status(self.job_id)
        self.db.transition(self.job_id, status, msg, stage=stage)
        self.logger.info("状态迁移 %s -> %s", before.value if before else "-", status.value)

    def _exists(self, rel: str) -> bool:
        return (self.job_dir / rel).exists()

    def _capabilities(self) -> dict:
        oc = OpenClawAdapter()
        rf = RufloAdapter()
        oc_info = oc.detect()
        if self.image_provider is not None and getattr(self.image_provider, "configured", False):
            ark_image = (f"verified (Agent Plan plan/v3, {self.image_provider.model}, "
                         f"size={self.settings.ark_image_size})")
        else:
            ark_image = ("not_configured (ARK_IMAGE_MODEL 为空；需 Agent Plan 专属 Key "
                         "与专属 Base URL/plan，已回退 Pillow 信息卡)")
        return {
            "ark_text": "verified (plan/v3, ark-code-latest)" if self.llm else "not_used_in_demo",
            "ark_image": ark_image,
            "ark_video": "not_configured (api/v3 401, ARK_VIDEO_MODEL 为空)",
            "ark_tts": "not_configured (ARK_TTS_MODEL 为空)",
            "github_api": "configured" if self.github else "not_configured",
            "tts_chain": self.settings.tts_engine,
            "openclaw": ("installed " + str(oc_info.get("version"))
                         if oc_info.get("installed") else "not_installed"),
            "ruflo": "installed" if rf.detect()["installed"] else "not_installed",
        }

    # --------------------------------------------------------------- main
    def run(self, *, resume: bool = False) -> Path:
        existing = self.db.list_jobs(200)
        job_row = next((j for j in existing if j["job_id"] == self.job_id), None)
        if job_row is None:
            if resume:
                raise FileNotFoundError(f"找不到可恢复的任务 {self.job_id}；"
                                        f"可用 `python -m videoforge.cli jobs` 查看")
            self.db.create_job(self.job_id, self.mode, self.topic,
                               {"model": self.settings.ark_model,
                                "pool": self.settings.candidate_pool,
                                "target_duration": self.settings.target_duration_sec})
        elif resume and job_row["status"] in ("completed", "failed", "cancelled"):
            self.db.reopen_job(self.job_id)
        try:
            self._stage_discovery(resume)
            self._stage_research(resume)
            self._stage_factcheck(resume)
            ranked = self._stage_ranking(resume)
            script = self._stage_script(resume, ranked)
            storyboard = self._stage_storyboard(resume, script, ranked)
            self._stage_assets_and_render(storyboard, resume)
            report = self._stage_qa(storyboard)
            self._finalize(report)
            return self.job_dir / "final_video.mp4"
        except Exception as exc:
            self.logger.error("任务失败：%s\n%s", redact(str(exc)),
                              redact(traceback.format_exc()[-1200:]))
            try:
                self._to(JobStatus.FAILED, msg=str(exc))
            except Exception:
                pass
            raise



    # --- stages ---------------------------------------------------------
    def _stage_discovery(self, resume: bool):
        f = self.ctx.research_dir / "candidates.json"
        if resume and f.exists():
            from videoforge.schemas import ProjectRecord
            self._to(JobStatus.DISCOVERING, StageName.DISCOVERY.value, "检查点跳过")
            records = [ProjectRecord(**r) for r in json.loads(f.read_text("utf-8"))]
            self._to(JobStatus.RESEARCHING, StageName.DISCOVERY.value, "恢复完成")
            return records
        self._to(JobStatus.DISCOVERING, StageName.DISCOVERY.value)
        self.db.start_stage(self.job_id, StageName.DISCOVERY.value)
        records = DiscoveryAgent(self.ctx).run()
        self.db.end_stage(self.job_id, StageName.DISCOVERY.value, True, {"n": len(records)})
        self._to(JobStatus.RESEARCHING, StageName.DISCOVERY.value)
        return records

    def _stage_research(self, resume: bool):
        from videoforge.schemas import ProjectRecord, ProjectProfile
        f = self.ctx.research_dir / ("profiles.json")
        records = [ProjectRecord(**r) for r in json.loads(
            (self.ctx.research_dir / "candidates.json").read_text("utf-8"))]
        if resume and f.exists():
            self._to(JobStatus.VERIFYING, StageName.RESEARCH.value, "检查点跳过")
            return [ProjectProfile(**r) for r in json.loads(f.read_text("utf-8"))]
        self.db.start_stage(self.job_id, StageName.RESEARCH.value)
        profiles = ResearchAgent(self.ctx).run(records)
        self.db.end_stage(self.job_id, StageName.RESEARCH.value, True, {"n": len(profiles)})
        self._to(JobStatus.VERIFYING, StageName.RESEARCH.value)
        return profiles

    def _stage_factcheck(self, resume: bool):
        from videoforge.schemas import ProjectProfile
        f = self.ctx.research_dir / "profiles_verified.json"
        profiles = [ProjectProfile(**r) for r in json.loads(
            (self.ctx.research_dir / "profiles.json").read_text("utf-8"))]
        if resume and f.exists():
            self._to(JobStatus.RANKING, StageName.FACT_CHECK.value, "检查点跳过")
            return [ProjectProfile(**r) for r in json.loads(f.read_text("utf-8"))]
        self.db.start_stage(self.job_id, StageName.FACT_CHECK.value)
        checked = FactCheckAgent(self.ctx).run(profiles)
        self.db.end_stage(self.job_id, StageName.FACT_CHECK.value, True)
        self._to(JobStatus.RANKING, StageName.FACT_CHECK.value)
        return checked

    def _stage_ranking(self, resume: bool):
        from videoforge.schemas import ProjectProfile, RankedProject
        profiles = [ProjectProfile(**r) for r in json.loads(
            (self.ctx.research_dir / "profiles_verified.json").read_text("utf-8"))]
        f = self.ctx.research_dir / "rankings.json"
        if resume and f.exists():
            ranked = [RankedProject(**r) for r in json.loads(f.read_text("utf-8"))]
        else:
            self.db.start_stage(self.job_id, StageName.RANKING.value)
            ranked = RankingAgent(self.ctx).run(profiles)
            self.db.end_stage(self.job_id, StageName.RANKING.value, True)
        top5_path = self.job_dir / "top5_projects.json"
        save_json([r.model_dump(mode="json") for r in ranked], top5_path)
        register(self.db, self.job_id, top5_path, type="data", origin="real",
                 provider="heuristic+ark", note="最终 Top5", root=self.job_dir)
        if self.db.get_status(self.job_id) == JobStatus.RANKING:
            self._to(JobStatus.SCRIPTING, StageName.RANKING.value)
        return ranked

    def _stage_script(self, resume: bool, ranked):
        from videoforge.schemas import Script
        f = self.job_dir / "script.json"
        if resume and f.exists():
            self._to(JobStatus.STORYBOARDING, StageName.SCRIPT.value, "检查点跳过")
            return Script(**json.loads(f.read_text("utf-8")))
        self.db.start_stage(self.job_id, StageName.SCRIPT.value)
        script = ScriptAgent(self.ctx).run(ranked)
        self.db.end_stage(self.job_id, StageName.SCRIPT.value, True,
                          {"chars": script.narration_chars})
        self._to(JobStatus.STORYBOARDING, StageName.SCRIPT.value)
        return script

    def _stage_storyboard(self, resume: bool, script, ranked):
        from videoforge.schemas import Storyboard
        f = self.job_dir / "storyboard.json"
        if resume and f.exists():
            self._to(JobStatus.GENERATING_ASSETS, StageName.STORYBOARD.value, "检查点跳过")
            return Storyboard(**json.loads(f.read_text("utf-8")))
        self.db.start_stage(self.job_id, StageName.STORYBOARD.value)
        storyboard = StoryboardAgent(self.ctx).run((script, ranked))
        self.db.end_stage(self.job_id, StageName.STORYBOARD.value, True,
                          {"scenes": len(storyboard.scenes)})
        self._to(JobStatus.GENERATING_ASSETS, StageName.STORYBOARD.value)
        return storyboard

    def _stage_assets_and_render(self, storyboard, resume: bool):
        self.db.start_stage(self.job_id, StageName.VISUAL.value)
        VisualAgent(self.ctx).run(storyboard)
        self.db.end_stage(self.job_id, StageName.VISUAL.value, True)
        self.db.start_stage(self.job_id, StageName.VOICE.value)
        audio_paths, self.audio_origins, self.subtitle = VoiceAgent(self.ctx).run(storyboard)
        # 配音实测时长会回填分镜，重写一次 storyboard.json
        save_json(storyboard.model_dump(mode="json"), self.job_dir / "storyboard.json")
        self.db.end_stage(self.job_id, StageName.VOICE.value, True)
        self._to(JobStatus.RENDERING, StageName.VOICE.value)
        self.db.start_stage(self.job_id, StageName.RENDER.value)
        RenderAgent(self.ctx).run((storyboard, audio_paths))
        self.db.end_stage(self.job_id, StageName.RENDER.value, True)
        self._to(JobStatus.QUALITY_REVIEW, StageName.RENDER.value)
        self.storyboard = storyboard

    def _revoice_and_rerender(self, storyboard, round_n: int):
        """定向返工：只重做配音 → 重渲染，不碰研究/编剧。"""
        self._to(JobStatus.RETRYING, StageName.QA.value, f"第 {round_n} 轮返工：配音/渲染")
        self._to(JobStatus.GENERATING_ASSETS, StageName.QA.value)
        self.db.start_stage(self.job_id, StageName.VOICE.value, attempt=round_n + 1)
        audio_paths, self.audio_origins, self.subtitle = VoiceAgent(self.ctx).run(storyboard)
        save_json(storyboard.model_dump(mode="json"), self.job_dir / "storyboard.json")
        self.db.end_stage(self.job_id, StageName.VOICE.value, True)
        self._to(JobStatus.RENDERING, StageName.VOICE.value)
        self.db.start_stage(self.job_id, StageName.RENDER.value, attempt=round_n + 1)
        RenderAgent(self.ctx).run((storyboard, audio_paths))
        self.db.end_stage(self.job_id, StageName.RENDER.value, True)
        self._to(JobStatus.QUALITY_REVIEW, StageName.RENDER.value)

    def _stage_qa(self, storyboard):
        final = self.job_dir / "final_video.mp4"
        for round_n in range(3):  # 初审 + 最多两轮返工
            self.db.start_stage(self.job_id, StageName.QA.value, attempt=round_n + 1)
            report = QAAgent(self.ctx).run(
                (storyboard, final, self.audio_origins, self.subtitle),
                rework_round=round_n)
            self.db.end_stage(self.job_id, StageName.QA.value, report.passed,
                              {"high_issues": sum(1 for i in report.issues if i.severity == "high")})
            if report.passed or round_n >= 2:
                self.report = report
                return report
            if any(i.owner_agent == "voice_subtitle_agent" and i.severity == "high"
                   for i in report.issues):
                self._revoice_and_rerender(storyboard, round_n + 1)
            else:
                # 其余高问题（编码/分辨率）直接重渲染
                self._to(JobStatus.RETRYING, StageName.QA.value, f"第 {round_n+1} 轮返工：重渲染")
                self._to(JobStatus.RENDERING, StageName.QA.value)
                audio_dir = self.ctx.assets_dir / "audio"
                audio_paths = {}
                missing = []
                for sc in storyboard.scenes:
                    hit = next(iter(sorted(audio_dir.glob(f"{sc.scene_id}.*"))), None)
                    if hit is None:
                        missing.append(sc.scene_id)
                    else:
                        audio_paths[sc.scene_id] = hit
                if missing:
                    # 音频缺失说明上一步配音未完整落盘：重做配音而非盲目重渲染
                    self.logger.warning("重渲染发现缺失音频 %s，改走重配音", ",".join(missing))
                    self._revoice_and_rerender(storyboard, round_n + 1)
                    continue
                RenderAgent(self.ctx).run((storyboard, audio_paths))
                self._to(JobStatus.QUALITY_REVIEW, StageName.RENDER.value)

    # --- finalize -------------------------------------------------------
    def _finalize(self, report):
        from videoforge.schemas import RunManifest
        # quality_report.md / .json
        qj = self.job_dir / "quality_report.json"
        save_json(report.model_dump(mode="json"), qj)
        register(self.db, self.job_id, qj, type="data", origin="real",
                 provider="ffprobe+program", root=self.job_dir)
        md = ["# 质量报告", "",
              f"- 结论：{'✅ 通过（无高优先级问题）' if report.passed else '❌ 仍有高优先级问题'}",
              f"- 时长：{report.duration_sec:.1f} 秒；分辨率：{report.width}x{report.height}；"
              f"帧率：{report.fps} fps",
              f"- 视频编码：{report.video_codec}；音频编码：{report.audio_codec}；"
              f"平均响度：{report.audio_mean_volume_db} dB",
              f"- QA 轮次：{report.rework_round}",
              "", "## 自动检查项", ""]
        for k, v in report.checks.items():
            md.append(f"- {'✅' if v else '❌'} {k}: {v}")
        md += ["", "## 素材来源统计（条）", ""]
        for k, v in report.asset_origins.items():
            md.append(f"- {k}: {v}")
        if report.issues:
            md += ["", "## 问题单", ""]
            for i in report.issues:
                md.append(f"- [{i.severity}] ({i.owner_agent}) {i.repair_instruction} —— {i.evidence}")
        (self.job_dir / "quality_report.md").write_text("\n".join(md), encoding="utf-8")

        totals = self.db.usage_totals(self.job_id)
        artifacts = self.db.list_artifacts(self.job_id)
        from videoforge.schemas import ArtifactRef
        refs = [ArtifactRef(**a) for a in artifacts]
        safe_settings = {
            "model": self.settings.ark_model, "base_url": self.settings.ark_base_url,
            "resolution": f"{self.settings.video_width}x{self.settings.video_height}",
            "fps": self.settings.fps,
            "candidate_pool": self.settings.candidate_pool,
            "tts_engine": self.settings.tts_engine,
            "image_provider": (self.settings.image_provider
                               + (f":{self.settings.ark_image_model}"
                                  if self.settings.image_capability_configured else ":pillow")),
        }
        manifest = RunManifest(
            job_id=self.job_id, mode=self.mode,  # type: ignore[arg-type]
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            completed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            topic=self.topic, settings=safe_settings,
            capabilities=self._capabilities(), artifacts=refs,
            llm_calls=totals["calls"], llm_tokens=totals["prompt_tokens"] + totals["completion_tokens"],
            estimated_cost_cny=totals["estimated_cost_cny"],
            final_video="final_video.mp4", subtitles="subtitles.srt",
            quality_passed=report.passed)
        mp = self.job_dir / "run_manifest.json"
        save_json(manifest.model_dump(mode="json"), mp)
        self._to(JobStatus.COMPLETED, StageName.QA.value,
                 f"成片 {report.duration_sec:.0f}s, QA={'pass' if report.passed else 'fail'}")

        # OpenClaw 通知（默认关闭：不触发外部账号的 agent turn）
        import os
        if os.getenv("OPENCLAW_NOTIFY") == "1":
            result = OpenClawAdapter(notify_enabled=True).notify_completion(
                self.job_id, str(self.job_dir / "final_video.mp4"), report.passed)
            self.logger.info("OpenClaw 通知：%s", result)
        # 企业微信群机器人通知（默认关闭：需 WECHAT_NOTIFY=1 且配置 Webhook）
        if self.settings.wechat_notify:
            from videoforge.integrations.wechat_adapter import WeChatAdapter
            wx = WeChatAdapter(self.settings.wechat_webhook_url, notify_enabled=True)
            wx_result = wx.notify_completion(
                self.job_id, str(self.job_dir / "final_video.mp4"),
                report.passed, duration_sec=report.duration_sec)
            self.logger.info("企业微信通知：%s", wx_result)
        # 数据库连接由调用方在任务结束后统一关闭（Workflow.close() / 上下文管理器）；
        # 此处 finalize 已完成全部落库，终态与产物均已持久化。
