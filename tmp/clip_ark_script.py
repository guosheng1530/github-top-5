"""一次性运维脚本：对已落盘的 ark 脚本施加 220 字/段护栏并重写 script.json/script.md。

不改变编剧来源（裁剪的仍是模型原句，按句末标点截断），script_origin.json 保持 ark。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from videoforge.agents.creative import _PROJECT_HARD_CHARS, _shrink_to_sentences
from videoforge.schemas import Script

JOB = Path("output/20261013-090433-c915d2")
s = Script(**json.loads((JOB / "script.json").read_text("utf-8")))
before = s.narration_chars
clipped = 0
for sec in s.sections:
    if sec.kind == "project" and len(sec.narration) > _PROJECT_HARD_CHARS:
        sec.narration = _shrink_to_sentences(sec.narration, _PROJECT_HARD_CHARS)
        clipped += 1
(JOB / "script.json").write_text(
    json.dumps(s.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")

md = ["# " + s.title, ""]
for sec in s.sections:
    md += [f"## [{sec.kind}] {sec.title}"
           + (f" — {sec.project_full_name}" if sec.project_full_name else ""),
           "", sec.narration, ""]
(JOB / "script.md").write_text("\n".join(md), encoding="utf-8")
print(f"clipped_sections={clipped} chars {before} -> {s.narration_chars}")
