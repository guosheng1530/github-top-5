"""一次性运维脚本（不进产品代码）：
1. 用新的 star 子分公式复算真实任务的 rankings.json（保留 LLM 点评）；
2. 在 TLS 抖动窗口里反复调用 ScriptAgent，直到编剧来源为 ark 或达到次数上限。
   每次失败都会走确定性降级（脚本始终可用），最后一次成功结果留在 script.json。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from videoforge.agents.creative import ScriptAgent
from videoforge.agents.intelligence import RankingAgent
from videoforge.artifacts import register, save_json
from videoforge.config import get_settings
from videoforge.providers.ark_text import ArkTextClient
from videoforge.schemas import ProjectProfile, RankedProject
from videoforge.workflow import Workflow

JOB = "20261013-090433-c915d2"
MAX_ATTEMPTS = 15

s = get_settings()
wf = Workflow(settings=s, mode="real", job_id=JOB, llm=None, github=None, tts=None)
jb: Path = wf.job_dir

# ---- 1. 新公式复算排名（成员/顺序通常不变，只变分数；点评按仓库名保留）----
profiles = [ProjectProfile(**r) for r in
            json.loads((jb / "research/profiles_verified.json").read_text("utf-8"))]
old = [RankedProject(**r) for r in
       json.loads((jb / "research/rankings.json").read_text("utf-8"))]
notes = {r.profile.record.full_name: r.rationale for r in old}
ranked = []
for p in profiles:
    a, b, c, d = RankingAgent._scores(p)
    total = round(a * 0.35 + b * 0.20 + c * 0.30 + d * 0.15, 1)
    ranked.append(RankedProject(profile=p, rank=0, score_stars=a, score_recency=b,
                                score_fit=c, score_license=d, total_score=total,
                                rationale=notes.get(p.record.full_name, "")))
ranked.sort(key=lambda x: x.total_score, reverse=True)
ranked = ranked[:5]
for i, r in enumerate(ranked, start=1):
    r.rank = i
rp = jb / "research" / "rankings.json"
save_json([r.model_dump(mode="json") for r in ranked], rp)
register(wf.db, JOB, rp, type="data", origin="real", provider="heuristic+ark",
         note="Top5 与评分明细（新 star 公式复算）", root=jb)
print("复算后分数：", [(r.profile.record.full_name, r.total_score) for r in ranked], flush=True)

# ---- 2. 编剧调用持久战役 ----
client = ArkTextClient(api_key=s.ark_api_key, base_url=s.ark_base_url,
                       model=s.ark_model, budget=wf.budget, timeout=s.ark_timeout)
wf.llm = client
wf.ctx.llm = client
origin_file = jb / "script_origin.json"
ok = False
for attempt in range(1, MAX_ATTEMPTS + 1):
    t0 = time.time()
    print(f"[campaign] 第 {attempt} 次编剧调用开始", flush=True)
    try:
        ScriptAgent(wf.ctx).run(ranked)
        gen = json.loads(origin_file.read_text("utf-8"))["generator"]
        print(f"[campaign] 第 {attempt} 次完成 -> {gen}，耗时 {time.time()-t0:.0f}s",
              flush=True)
        if gen == "ark":
            ok = True
            break
    except Exception as exc:  # noqa: BLE001 - 运维脚本必须打完全部轮次
        print(f"[campaign] 第 {attempt} 次异常：{type(exc).__name__}: {str(exc)[:150]}",
              flush=True)
    time.sleep(30)

print("CAMPAIGN_RESULT", "ark_ok" if ok else "fallback_final", flush=True)
sys.exit(0 if ok else 2)
