"""创作线 2 个 Agent：Script（编剧）/ Storyboard（分镜）。"""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import ValidationError

from videoforge.agents.base import BaseAgent
from videoforge.agents.prompts import SCRIPT_PROMPT, STORYBOARD_PROMPT
from videoforge.artifacts import register, save_json
from videoforge.providers.base import ProviderError
from videoforge.schemas import (RankedProject, Script, ScriptSection, StageName,
                                Storyboard, StoryboardScene)

# Huihui 语速 150 实测约 5.1 字/秒（2026-10-13 真实任务 3272 字 / 635 秒）；
# 估算只用于分镜初稿，VoiceAgent 会以 ffprobe 实测音频时长回填。
_CHARS_PER_SEC = 5.0
_MIN_SCENE_SEC = 6.0
_MAX_SCENE_SEC = 75.0

# 口播长度护栏：目标成片约 5 分钟（~1500 字 / 5 字每秒）。
# LLM 提示词要求每项目段 130-180 字；模型偶发不遵守或走确定性降级时，用这两个值兜底。
_PROJECT_HARD_CHARS = 220       # 单段硬上限（超出按句号裁断；实测混合英文/数字
                                # 内容 SAPI 约 4.4 字/秒，220×5+首尾≈1500 字≈340 秒）
_FALLBACK_ONELINER = 64         # 降级段：一句话定位裁剪长度
_FALLBACK_FEAT = 40             # 降级段：单条亮点裁剪长度


def _format_stars(n: int) -> str:
    return f"{n / 10000:.1f} 万" if n >= 10000 else str(n)


def _clip(text: str, n: int) -> str:
    """把不可信的长文本（研究 LLM 生成的 features/one_liner）裁到 n 字以内。"""
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= n:
        return text
    return text[:n - 1].rstrip("，；、,; 　") + "…"


def _shrink_to_sentences(text: str, limit: int) -> str:
    """在 limit 以内按标点截断，尽量保留信息量、不切成半句话。

    优先句末标点（。！？；）。真实 LLM 常把一段写成一个 280 字的长句，
    若 limit 内最后的句号过早（< limit*0.75），退而求其次在 limit 附近的
    逗号处收束（补句号），避免把后半段特性介绍全部丢掉（实测事故）。
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind("。"), head.rfind("！"), head.rfind("？"), head.rfind("；"))
    if cut >= int(limit * 0.75):
        return head[:cut + 1]
    comma = max(head.rfind("，"), head.rfind("、"))
    if comma >= int(limit * 0.75):
        return head[:comma].rstrip("，；、,; ") + "。"
    if cut >= 40:
        return head[:cut + 1]
    return head.rstrip("，；、,; ") + "。"


def estimate_duration(text: str) -> float:
    return round(max(_MIN_SCENE_SEC, min(_MAX_SCENE_SEC, len(text) / _CHARS_PER_SEC)), 2)


class ScriptAgent(BaseAgent):
    name = "script_agent"
    stage = StageName.SCRIPT
    system_prompt = SCRIPT_PROMPT
    allowed_tools = ("ark.chat_json",)
    timeout_sec = 300

    def _fallback_section(self, kind: str, r: RankedProject | None) -> ScriptSection:
        if kind == "intro":
            return ScriptSection(kind="intro", title="开场",
                narration="大家好，欢迎收看本期开源情报。今天我们用 GitHub 的实时数据，"
                         "盘点近期最值得关注的五个 AI Agent 开源项目。数据有采集时间，"
                         "排名是我们自己的启发式评分，不是 GitHub 官方榜单。")
        if kind == "outro":
            return ScriptSection(kind="outro", title="结尾",
                narration="以上就是本期五个项目。所有数据来自 GitHub REST API，"
                         "点评由大模型基于项目 README 生成并经过事实核验，画面是程序化信息卡，"
                         "配音来自系统离线语音。开源世界变化很快，动手前请以官方仓库为准。感谢观看。")
        p = r.profile  # type: ignore[union-attr]
        # 研究 LLM 写的 features/limitations 可能长达数百字，降级段必须显式裁剪，
        # 否则单段口播可冲到 700 字（实测 635 秒成片的根因）。
        feats = [_clip(x, _FALLBACK_FEAT) for x in p.features[:2] if x.strip()]
        parts = [f"第 {r.rank} 个项目是 {p.record.full_name}。{_clip(p.one_liner, _FALLBACK_ONELINER)}"]
        if feats:
            parts.append("核心亮点：" + "；".join(feats) + "。")
        parts.append(f"GitHub {_format_stars(p.record.stars)} stars，"
                     f"{p.record.pushed_at[:10]} 推送，{p.record.license or '未声明'}许可。")
        if p.limitations:
            parts.append("注意：" + _clip(p.limitations[0], 42) + "。")
        parts.append("感兴趣可以到官方仓库了解。")
        return ScriptSection(
            kind="project", project_full_name=p.record.full_name,
            title=p.record.full_name, narration="".join(parts))

    def run(self, ranked: list[RankedProject]) -> Script:
        listing = "\n".join(
            f"## 第{i+1}名 {r.profile.record.full_name}（{r.profile.record.stars} stars, "
            f"{r.profile.record.license or '无许可证'}）\n定位：{r.profile.one_liner}\n"
            f"特性：{'；'.join(r.profile.features[:5])}\n"
            f"局限：{'；'.join(r.profile.limitations[:3])}\n"
            f"核验声明：{'；'.join(c.text + '(' + c.status + ')' for c in r.profile.claims[:5])}"
            for i, r in enumerate(ranked))
        prompt = (
            f"今天 {time.strftime('%Y-%m-%d')}，主题：近期热门 AI Agent 开源项目 Top5。\n"
            f"已核验材料（只能使用其中事实）：\n{listing}\n\n"
            "输出 JSON：{\"title\":..., \"sections\":[{\"kind\":\"intro|overview|project|outro\", "
            "\"project_full_name\":project 段必须填完整仓库名或 null, \"title\":..., "
            "\"narration\":口播稿, \"on_screen_bullets\":[屏幕要点]}]}。"
            "必须恰好包含 1 intro、1 overview、5 project（每个给定项目各一段）、1 outro。")
        script_generator, gen_reason = "ark", ""
        try:
            # 推理模型的 reasoning_tokens 也占 completion 额度（实测 300 字答案要耗
            # ~1300 reasoning tokens），4000 会让长脚本被截断/超时，放宽到 6000。
            data = self._llm_json(prompt, max_tokens=6000, temperature=0.75)
            sections = [ScriptSection(**s) for s in data.get("sections", [])]
            script = Script(title=str(data.get("title", "GitHub AI Agent Top 5")), sections=sections)
        except (ProviderError, ValidationError, TypeError) as exc:
            gen_reason = str(exc)[:200]
            self.logger.warning("编剧 LLM 失败/不合规，使用确定性脚本：%s", gen_reason[:120])
            script = Script(title="GitHub 热门 AI Agent 项目 Top 5", sections=[])
            script_generator = "deterministic_fallback"

        # ---- 归一化：保证结构完整且五个项目各有一段（LLM 可能漏写/合并）----
        by_name = {s.project_full_name: s for s in script.sections if s.kind == "project"}
        norm: list[ScriptSection] = []
        fallback_sections = 0
        intro = next((s for s in script.sections if s.kind == "intro"), None)
        if intro:
            norm.append(intro)
        else:
            norm.append(self._fallback_section("intro", None)); fallback_sections += 1
        overview = next((s for s in script.sections if s.kind == "overview"), None)
        if overview:
            norm.append(overview)
        else:
            norm.append(ScriptSection(
                kind="overview", title="榜单总览",
                narration="本期榜单：" + "、".join(
                    r.profile.record.full_name.split("/")[-1] for r in ranked)
                    + "。评分综合了星标数量、近期活跃度、主题契合度和许可证，下面逐个来看。"))
            fallback_sections += 1
        for r in ranked:
            name = r.profile.record.full_name
            sec = by_name.get(name)
            if sec and len(sec.narration) >= 40:
                # 模型可能不遵守 130-180 字要求：超长按句截断到硬上限，保护成片总时长。
                if len(sec.narration) > _PROJECT_HARD_CHARS:
                    sec = sec.model_copy(update={
                        "narration": _shrink_to_sentences(sec.narration, _PROJECT_HARD_CHARS)})
                norm.append(sec)
            else:
                norm.append(self._fallback_section("project", r))
                fallback_sections += 1
        outro = next((s for s in script.sections if s.kind == "outro"), None)
        if outro:
            norm.append(outro)
        else:
            norm.append(self._fallback_section("outro", None)); fallback_sections += 1
        if script_generator == "ark" and fallback_sections:
            script_generator = "ark+deterministic_fallback"
        script = Script(title=script.title or "GitHub AI Agent Top 5", sections=norm)

        md = ["# " + script.title, ""]
        for s in script.sections:
            md += [f"## [{s.kind}] {s.title}" + (f" — {s.project_full_name}" if s.project_full_name else ""),
                   "", s.narration, ""]
        out = self.ctx.job_dir / "script.md"
        out.write_text("\n".join(md), encoding="utf-8")
        is_ark = script_generator == "ark"
        register(self.ctx.db, self.ctx.job_id, out, type="data",
                 origin="real" if is_ark else "template",
                 provider="ark" if is_ark else "deterministic",
                 model=self.ctx.settings.ark_model if is_ark else "",
                 note=f"中文口播脚本（{script_generator}）", root=self.ctx.job_dir)
        sj = self.ctx.job_dir / "script.json"
        save_json(script.model_dump(mode="json"), sj)
        # 编剧来源 sidecar：尾卡/恢复/审计据此如实标注，失败原因也留档
        save_json({"generator": script_generator, "fallback_sections": fallback_sections,
                   "reason": gen_reason, "at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                  self.ctx.job_dir / "script_origin.json")
        self.logger.info("脚本完成：%d 段，约 %d 字（来源：%s）",
                         len(script.sections), script.narration_chars, script_generator)
        return script


class StoryboardAgent(BaseAgent):
    name = "storyboard_agent"
    stage = StageName.STORYBOARD
    system_prompt = STORYBOARD_PROMPT
    allowed_tools = ()  # 纯确定性转换，不需要外部工具
    timeout_sec = 60

    def run(self, payload: tuple[Script, list[RankedProject]]) -> Storyboard:
        script, ranked = payload
        by_name = {r.profile.record.full_name: r for r in ranked}
        scenes: list[StoryboardScene] = []
        si = 0

        intro = next(s for s in script.sections if s.kind == "intro")
        scenes.append(StoryboardScene(
            scene_id=f"scene-{si:02d}", section_index=si,
            duration_sec=estimate_duration(intro.narration), voiceover=intro.narration,
            visual_type="title_card", on_screen_text=script.title,
            card_data={"title": script.title,
                       "subtitle": "近期热门 AI Agent 开源项目 · Top 5",
                       "meta": f"{time.strftime('%Y-%m-%d')} 数据采集 · 程序化画面"}))
        si += 1

        overview = next((s for s in script.sections if s.kind == "overview"), None)
        ov_voice = overview.narration if overview else (
            "本期榜单：" + "、".join(r.profile.record.full_name.split("/")[-1] for r in ranked)
            + "。评分综合了星标数量、近期活跃度、主题契合度和许可证，下面逐个来看。")
        scenes.append(StoryboardScene(
            scene_id=f"scene-{si:02d}", section_index=si,
            duration_sec=estimate_duration(ov_voice), voiceover=ov_voice,
            visual_type="ranking_card",
            card_data={"title": "Top 5 总览",
                       "items": [{"name": r.profile.record.full_name,
                                  "stars": r.profile.record.stars,
                                  "score": r.total_score} for r in ranked]}))
        si += 1

        for sec in (s for s in script.sections if s.kind == "project"):
            r = by_name.get(sec.project_full_name or "")
            if not r:
                continue
            p = r.profile
            bullets = list(p.features[:4])
            if r.rationale:
                bullets.append("点评：" + r.rationale)
            scenes.append(StoryboardScene(
                scene_id=f"scene-{si:02d}", section_index=si,
                duration_sec=estimate_duration(sec.narration), voiceover=sec.narration,
                visual_type="project_card",
                on_screen_text=sec.title,
                card_data={"rank": r.rank, "name": p.record.full_name,
                           "stars": p.record.stars, "forks": p.record.forks,
                           "language": p.record.language, "license": p.record.license,
                           "one_liner": p.one_liner, "bullets": bullets,
                           "url": str(p.record.repo_url)}))
            si += 1

        outro = next(s for s in script.sections if s.kind == "outro")
        # 尾卡必须如实标注编剧来源（读 ScriptAgent 写的 script_origin.json）
        origin_path = self.ctx.job_dir / "script_origin.json"
        gen = "demo_offline"
        if origin_path.exists():
            try:
                gen = json.loads(origin_path.read_text("utf-8")).get("generator", gen)
            except (json.JSONDecodeError, OSError):
                pass
        llm_lines = {
            "ark": "研究/事实核验/编剧：火山方舟 ark-code-latest",
            "ark+deterministic_fallback": "研究/事实核验：火山方舟；编剧：方舟+确定性模板补齐",
            "deterministic_fallback": "研究/事实核验：火山方舟；编剧：确定性模板（方舟超时回退）",
            "demo_offline": "零 LLM 费用演示：研究/编剧均为确定性离线模式",
        }
        scenes.append(StoryboardScene(
            scene_id=f"scene-{si:02d}", section_index=si,
            duration_sec=estimate_duration(outro.narration), voiceover=outro.narration,
            visual_type="end_card",
            card_data={"title": "感谢观看",
                       "lines": ["数据：GitHub REST API（含采集时间）",
                                 llm_lines.get(gen, llm_lines["deterministic_fallback"]),
                                 "配音：Windows SAPI5 离线语音 · 画面：Pillow 程序化生成",
                                 "本排名为自定义启发式评分，非 GitHub 官方榜单"]}))

        storyboard = Storyboard(scenes=scenes)
        out = self.ctx.job_dir / "storyboard.json"
        save_json(storyboard.model_dump(mode="json"), out)
        register(self.ctx.db, self.ctx.job_id, out, type="data", origin="real",
                 note=f"{len(scenes)} 个分镜", root=self.ctx.job_dir)
        est = sum(x.duration_sec for x in scenes)
        self.logger.info("分镜完成：%d 镜，预估总时长 %.0f 秒", len(scenes), est)
        return storyboard
