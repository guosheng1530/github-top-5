"""情报线 4 个 Agent：Discovery / Research / FactCheck / Ranking。"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from pydantic import ValidationError

from videoforge.agents.base import BaseAgent
from videoforge.agents.prompts import (DISCOVERY_PROMPT, FACTCHECK_PROMPT,
                                       RANKING_PROMPT, RESEARCH_PROMPT)
from videoforge.artifacts import register, save_json
from videoforge.providers.base import ProviderError
from videoforge.schemas import (Claim, ProjectProfile, ProjectRecord,
                                RankedProject, StageName)

_FIT_KEYWORDS = ("agent", "agents", "llm", "mcp", "autonomous", "swarm",
                 "multi-agent", "copilot", "assistant", "workflow", "orchestr")
_PERMISSIVE = {"mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause", "isc"}


# --------------------------------------------------------------------------- #
# 1. 趋势发现
# --------------------------------------------------------------------------- #
class DiscoveryAgent(BaseAgent):
    name = "trend_discovery_agent"
    stage = StageName.DISCOVERY
    system_prompt = DISCOVERY_PROMPT
    allowed_tools = ("github.search_repositories", "github.get_repository")
    timeout_sec = 240

    def run(self, payload: None = None) -> list[ProjectRecord]:
        s = self.ctx.settings
        if self.ctx.github is None:
            raise ProviderError("GitHub 客户端未配置", "capability")
        raw = self.ctx.github.search_agent_repos(
            min_stars=s.min_stars, pushed_within_days=s.pushed_within_days)
        self.logger.info("搜索召回 %d 个候选，开始逐个 GET 复核", len(raw))

        records: list[ProjectRecord] = []
        cutoff = datetime.now(timezone.utc).timestamp() - s.pushed_within_days * 86400
        for item in raw[: s.candidate_pool * 3]:
            full = item["full_name"]
            try:
                repo = self.ctx.github.get_repo(full)  # 搜索结果不直接当事实
            except ProviderError:
                continue
            if repo.get("archived") or repo.get("fork"):
                continue
            pushed = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00")).timestamp()
            if pushed < cutoff:
                continue
            haystack = " ".join([
                repo.get("description") or "", " ".join(repo.get("topics") or []),
                repo.get("name") or "",
            ]).lower()
            if not any(k in haystack for k in _FIT_KEYWORDS):
                continue
            lic = (repo.get("license") or {}).get("spdx_id")
            records.append(ProjectRecord(
                full_name=repo["full_name"],
                repo_url=repo["html_url"],
                description=repo.get("description") or "",
                stars=repo["stargazers_count"],
                forks=repo["forks_count"],
                watchers=repo["subscribers_count"],
                open_issues=repo.get("open_issues_count", 0),
                language=repo.get("language"),
                license=None if lic in ("NOASSERTION", None) else lic,
                topics=repo.get("topics") or [],
                created_at=repo["created_at"],
                pushed_at=repo["pushed_at"],
                archived=repo.get("archived", False),
                collected_at=datetime.now(timezone.utc).isoformat(),
                evidence_urls=[repo["html_url"]],
            ))
            if len(records) >= s.candidate_pool:
                break

        records.sort(key=lambda r: r.stars, reverse=True)
        if not records:
            raise ProviderError("发现阶段没有找到符合条件的仓库（检查网络/GitHub token）",
                                "permanent")
        out = self.ctx.research_dir / "candidates.json"
        save_json([r.model_dump(mode="json") for r in records], out)
        register(self.ctx.db, self.ctx.job_id, out, type="data", origin="real",
                 provider="github_rest", model="", note=f"{len(records)} 个候选",
                 root=self.ctx.job_dir)
        self.logger.info("发现阶段确认 %d 个候选", len(records))
        return records


# --------------------------------------------------------------------------- #
# 2. 项目研究（并行）
# --------------------------------------------------------------------------- #
class ResearchAgent(BaseAgent):
    name = "research_agent"
    stage = StageName.RESEARCH
    system_prompt = RESEARCH_PROMPT
    allowed_tools = ("github.get_repository", "github.get_readme", "ark.chat_json")
    timeout_sec = 300

    def _one(self, record: ProjectRecord) -> ProjectProfile:
        if self.ctx.llm is None:
            # demo/离线模式：不消耗 README 配额，直接用 API 事实降级
            return ProjectProfile(
                record=record,
                one_liner=record.description or "（离线模式：仅保留 GitHub 元数据）",
                limitations=["离线模式，LLM 研究未启用，仅保留经 API 核验的元数据"],
                claims=[], readme_fetched=False, evidence_urls=[str(record.repo_url)])
        readme, ok = self.ctx.github.get_readme(record.full_name)
        user_prompt = (
            f"仓库：{record.full_name}\nGitHub 描述：{record.description}\n"
            f"语言：{record.language}；主题：{', '.join(record.topics[:10])}\n\n"
            f"README 摘要（前 9000 字，可能不完整）：\n{readme[:9000]}\n\n"
            "输出 JSON：{\"one_liner\":..., \"features\":[...], \"architecture\":..., "
            "\"install_hint\":..., \"limitations\":[...], "
            "\"claims\":[{\"text\":..., \"evidence\":...}]}")
        try:
            data = self._llm_json(user_prompt, max_tokens=2200, temperature=0.4)
            claims = [Claim(**c) for c in data.get("claims", [])][:6]
            return ProjectProfile(
                record=record, one_liner=str(data.get("one_liner", ""))[:200],
                features=[str(x)[:120] for x in data.get("features", [])][:6],
                architecture=str(data.get("architecture", ""))[:600],
                install_hint=str(data.get("install_hint", ""))[:300],
                limitations=[str(x)[:160] for x in data.get("limitations", [])][:4],
                claims=claims, readme_fetched=ok,
                evidence_urls=[str(record.repo_url)],
            )
        except (ProviderError, ValidationError) as exc:
            self.logger.warning("研究 %s 失败，使用 API 事实降级：%s",
                                record.full_name, str(exc)[:120])
            return ProjectProfile(
                record=record,
                one_liner=record.description or "（研究摘要暂缺，仅保留 GitHub 元数据）",
                features=[], limitations=["LLM 研究失败，仅保留经 API 核验的元数据"],
                claims=[], readme_fetched=ok, evidence_urls=[str(record.repo_url)])

    def run(self, records: list[ProjectRecord]) -> list[ProjectProfile]:
        profiles: list[ProjectProfile] = []
        with ThreadPoolExecutor(max_workers=self.ctx.settings.research_parallel) as pool:
            futures = {pool.submit(self._one, r): r for r in records}
            for fut in as_completed(futures):
                profiles.append(fut.result())
        profiles.sort(key=lambda p: p.record.stars, reverse=True)
        out = self.ctx.research_dir / "profiles.json"
        save_json([p.model_dump(mode="json") for p in profiles], out)
        register(self.ctx.db, self.ctx.job_id, out, type="data", origin="real",
                 provider="github_rest+ark", note=f"{len(profiles)} 份资料卡",
                 root=self.ctx.job_dir)
        return profiles


# --------------------------------------------------------------------------- #
# 3. 事实核验
# --------------------------------------------------------------------------- #
class FactCheckAgent(BaseAgent):
    name = "fact_check_agent"
    stage = StageName.FACT_CHECK
    system_prompt = FACTCHECK_PROMPT
    allowed_tools = ("ark.chat_json",)
    timeout_sec = 300

    def _verify_one(self, p: ProjectProfile) -> ProjectProfile:
        # 3a. API 事实直接入表（这是最高可信级）
        api_claims = [
            Claim(text=f"GitHub Star 数为 {p.record.stars}", status="verified",
                  evidence="stargazers_count (GitHub REST)", source_url=str(p.record.repo_url)),
            Claim(text=f"最近代码推送时间 {p.record.pushed_at[:10]}", status="verified",
                  evidence="pushed_at (GitHub REST)", source_url=str(p.record.repo_url)),
            Claim(text=f"开源许可证为 {p.record.license or '未声明'}", status="verified",
                  evidence="license.spdx_id (GitHub REST)", source_url=str(p.record.repo_url)),
        ]
        if not p.claims:
            p.claims = api_claims
            return p
        # 3b. LLM 对 README 声明逐条核验
        prompt = (
            f"仓库：{p.record.full_name}\n已确认 API 事实：star={p.record.stars}，"
            f"license={p.record.license}，language={p.record.language}，"
            f"pushed_at={p.record.pushed_at}\n待核验声明：\n"
            + "\n".join(f"{i+1}. {c.text}" for i, c in enumerate(p.claims))
            + "\n输出 JSON：{\"verdicts\":[{\"index\":从1开始, \"status\":"
              "verified/uncertain/false, \"evidence\":...}]}")
        try:
            data = self._llm_json(prompt, max_tokens=1500, temperature=0.1)
            verdicts = {int(v["index"]): v for v in data.get("verdicts", []) if "index" in v}
            for i, c in enumerate(p.claims, start=1):
                v = verdicts.get(i)
                if v and v.get("status") in ("verified", "uncertain", "false"):
                    c.status = v["status"]
                    c.evidence = str(v.get("evidence", ""))[:200]
                    c.source_url = str(p.record.repo_url)
                else:
                    c.status = "uncertain"
        except ProviderError as exc:
            self.logger.warning("核验 %s 的 LLM 调用失败，声明降级 uncertain：%s",
                                p.record.full_name, str(exc)[:100])
            for c in p.claims:
                if c.status == "uncertain":
                    c.evidence = (c.evidence + "；LLM 核验不可用").strip("；")
        p.claims = api_claims + p.claims
        return p

    def run(self, profiles: list[ProjectProfile]) -> list[ProjectProfile]:
        checked = [self._verify_one(p) for p in profiles]
        verified = sum(1 for p in checked for c in p.claims if c.status == "verified")
        uncertain = sum(1 for p in checked for c in p.claims if c.status == "uncertain")
        false_n = sum(1 for p in checked for c in p.claims if c.status == "false")
        self.logger.info("核验完成：verified=%d uncertain=%d false=%d",
                         verified, uncertain, false_n)
        out = self.ctx.research_dir / "profiles_verified.json"
        save_json([p.model_dump(mode="json") for p in checked], out)
        register(self.ctx.db, self.ctx.job_id, out, type="data", origin="real",
                 provider="ark+github_rest", note="已核验资料卡", root=self.ctx.job_dir)
        return checked


# --------------------------------------------------------------------------- #
# 4. 排名（确定性评分 + LLM 中文点评）
# --------------------------------------------------------------------------- #
class RankingAgent(BaseAgent):
    name = "ranking_agent"
    stage = StageName.RANKING
    system_prompt = RANKING_PROMPT
    allowed_tools = ("ark.chat_json",)
    timeout_sec = 240

    # Star 子分：在 [100, 500_000] 之间做 log 归一化。
    # 旧公式 25*log10(stars) 在 10 万星即触顶 100，2026 年的头部 agent 仓库普遍
    # 十几万星，导致五个项目并列 100、排名失去区分度（真实任务实测）。
    STARS_FLOOR, STARS_CEIL = 100, 500_000

    @classmethod
    def _scores(cls, p: ProjectProfile) -> tuple[float, float, float, float]:
        r = p.record
        span = math.log10(cls.STARS_CEIL) - math.log10(cls.STARS_FLOOR)
        s_stars = min(100.0, max(0.0, 100.0 * (
            math.log10(max(cls.STARS_FLOOR, r.stars)) - math.log10(cls.STARS_FLOOR)) / span))
        days = (time.time() - datetime.fromisoformat(
            r.pushed_at.replace("Z", "+00:00")).timestamp()) / 86400
        s_recency = 100 if days <= 30 else 70 if days <= 90 else 40 if days <= 180 else 10
        hay = (" ".join(r.topics) + " " + (r.description or "")).lower()
        hits = sum(1 for k in _FIT_KEYWORDS if k in hay)
        s_fit = min(100.0, 40.0 + 20.0 * hits)
        lic = (r.license or "").lower()
        s_license = 100.0 if lic in _PERMISSIVE else 60.0 if lic else 20.0
        return round(s_stars, 1), round(s_recency, 1), round(s_fit, 1), round(s_license, 1)

    def run(self, profiles: list[ProjectProfile], top_n: int = 5) -> list[RankedProject]:
        ranked: list[RankedProject] = []
        for p in profiles:
            a, b, c, d = self._scores(p)
            total = round(a * 0.35 + b * 0.20 + c * 0.30 + d * 0.15, 1)
            ranked.append(RankedProject(profile=p, rank=0, score_stars=a,
                                        score_recency=b, score_fit=c, score_license=d,
                                        total_score=total))
        ranked.sort(key=lambda x: x.total_score, reverse=True)
        ranked = ranked[:top_n]
        for i, r in enumerate(ranked, start=1):
            r.rank = i

        # LLM 只负责点评，不允许改分数
        try:
            listing = "\n".join(
                f"{i+1}. {r.profile.record.full_name}（{r.total_score} 分，"
                f"定位：{r.profile.one_liner}）" for i, r in enumerate(ranked))
            data = self._llm_json(
                f"以下是按固定权重算出的 Top{len(ranked)}（分数不可修改）：\n{listing}\n"
                "输出 JSON：{\"notes\":[按顺序每个项目一句中文点评]}",
                max_tokens=1200, temperature=0.6)
            notes = data.get("notes", [])
            for i, r in enumerate(ranked):
                if i < len(notes):
                    r.rationale = str(notes[i])[:220]
        except ProviderError as exc:
            self.logger.warning("排名点评 LLM 失败，使用模板点评：%s", str(exc)[:100])
            for r in ranked:
                r.rationale = (f"综合启发式评分 {r.total_score} 分：活跃度与 Agent 主题契合度"
                               f"综合表现排名第 {r.rank}（点评生成失败，仅保留程序评分说明）")
        out = self.ctx.research_dir / "rankings.json"
        save_json([r.model_dump(mode="json") for r in ranked], out)
        register(self.ctx.db, self.ctx.job_id, out, type="data", origin="real",
                 provider="heuristic+ark", note="Top5 与评分明细", root=self.ctx.job_dir)
        return ranked
