"""一次性运维脚本：用改进后的长度护栏重新调用一次 ScriptAgent（方舟）。

rankings.json 已复算，直接读；成功后 script.json 即为 220 字护栏归一化后的成品。
"""

from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from videoforge.agents.creative import ScriptAgent
from videoforge.config import get_settings
from videoforge.providers.ark_text import ArkTextClient
from videoforge.schemas import RankedProject
from videoforge.workflow import Workflow

JOB = "20261013-090433-c915d2"
s = get_settings()
wf = Workflow(settings=s, mode="real", job_id=JOB, llm=None, github=None, tts=None)
ranked = [RankedProject(**r) for r in
          json.loads((wf.job_dir / "research/rankings.json").read_text("utf-8"))]
client = ArkTextClient(api_key=s.ark_api_key, base_url=s.ark_base_url,
                       model=s.ark_model, budget=wf.budget, timeout=s.ark_timeout)
wf.llm = client
wf.ctx.llm = client
script = ScriptAgent(wf.ctx).run(ranked)
origin = json.loads((wf.job_dir / "script_origin.json").read_text("utf-8"))
print("SCRIPT_RERUN", origin["generator"], script.narration_chars,
      [len(x.narration) for x in script.sections if x.kind == "project"], flush=True)
