"""端到端工作流测试：Fake LLM + Fake GitHub，但 SAPI 语音与 FFmpeg 都是真的。

覆盖：DAG 全阶段、并行研究、事实核验门禁、确定性归一化、
字幕时间轴、真实合成、ffprobe 质检、SQLite 终态。
"""

import json
from datetime import datetime, timezone

import pytest

from videoforge.config import Settings
from videoforge.media import ffmpeg_tools
from videoforge.providers.base import ProviderError
from videoforge.workflow import Workflow

pytestmark = pytest.mark.slow

NAMES = [f"demo-org/agent-{i}" for i in range(1, 6)]
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeGitHub:
    def search_agent_repos(self, *, min_stars, pushed_within_days, per_page=30):
        return [{"full_name": n} for n in NAMES]

    def get_repo(self, full_name):
        i = NAMES.index(full_name) + 1
        return {
            "full_name": full_name, "html_url": f"https://github.com/{full_name}",
            "description": "An autonomous AI agent framework with LLM tool use",
            "stargazers_count": 1000 * i, "forks_count": 100 * i,
            "subscribers_count": 50, "open_issues_count": 10, "language": "Python",
            "license": {"spdx_id": "MIT"}, "topics": ["ai-agents", "llm"],
            "created_at": "2024-01-01T00:00:00Z", "pushed_at": NOW,
            "archived": False, "fork": False,
        }

    def get_readme(self, full_name, max_chars=12000):
        return f"# {full_name}\nAn AI agent framework. Supports MCP and workflows.", True


class FakeLLM:
    def chat_json(self, system_prompt, user_prompt, *, max_tokens=3000, temperature=0.5):
        if "README 摘要" in user_prompt:
            return {"one_liner": "一个用于演示的 AI Agent 框架",
                    "features": ["工具调用", "多 Agent 协作"],
                    "architecture": "Python", "install_hint": "pip install",
                    "limitations": ["演示数据"],
                    "claims": [{"text": "支持工具调用", "evidence": "README"}]}
        if "待核验声明" in user_prompt:
            return {"verdicts": [{"index": 1, "status": "verified", "evidence": "README"}]}
        if "固定权重算出" in user_prompt:
            return {"notes": ["点评"] * 5}
        if "已核验材料" in user_prompt:
            sections = [
                {"kind": "intro", "title": "开场", "project_full_name": None,
                 "narration": "大家好，欢迎收看本期测试榜单。",
                 "on_screen_bullets": []},
                {"kind": "overview", "title": "总览", "project_full_name": None,
                 "narration": "今天一共有五个演示项目上榜。", "on_screen_bullets": []},
            ]
            for i, n in enumerate(NAMES, start=1):
                sections.append({
                    "kind": "project", "title": n, "project_full_name": n,
                    "narration": f"第{i}名 {n}，一个演示用 Agent 项目，测试口播长度。",
                    "on_screen_bullets": ["演示"]})
            sections.append({"kind": "outro", "title": "结尾", "project_full_name": None,
                             "narration": "以上就是本期测试，感谢观看。", "on_screen_bullets": []})
            return {"title": "测试榜单", "sections": sections}
        raise ProviderError("fake: 未预期的提示", "permanent")

    def chat(self, *a, **k):
        return "{}"


def test_full_pipeline_end_to_end(tmp_path, monkeypatch):
    for k, v in {
        "VIDEO_WIDTH": "640", "VIDEO_HEIGHT": "360", "VIDEO_FPS": "15",
        "CANDIDATE_POOL": "5", "MIN_STARS": "1", "RESEARCH_PARALLEL": "2",
        "TARGET_DURATION_SEC": "90", "TTS_ENGINE": "sapi",
    }.items():
        monkeypatch.setenv(k, v)
    settings = Settings()
    settings.output_root = tmp_path

    from videoforge.providers.tts import TTSChain
    wf = Workflow(settings=settings, mode="demo", github=FakeGitHub(),
                  llm=FakeLLM(), tts=TTSChain("sapi"), topic="测试主题")
    video = wf.run()

    assert video.exists()
    info = ffmpeg_tools.video_stream_info(video)
    assert (info["width"], info["height"]) == (640, 360)
    assert abs(info["fps"] - 15) < 0.1
    assert ffmpeg_tools.has_audio_stream(video)
    assert ffmpeg_tools.duration_of(video) > 20

    assert wf.db.get_status(wf.job_id).value == "completed"
    storyboard = json.loads((wf.job_dir / "storyboard.json").read_text("utf-8"))
    assert len(storyboard["scenes"]) == 8  # intro + overview + 5 projects + outro
    top5 = json.loads((wf.job_dir / "top5_projects.json").read_text("utf-8"))
    assert len(top5) == 5 and top5[0]["rank"] == 1

    report = json.loads((wf.job_dir / "quality_report.json").read_text("utf-8"))
    assert report["passed"] is True
    assert report["checks"]["srt_timeline"] is True
    assert report["checks"]["all_projects_narrated"] is True
    manifest = json.loads((wf.job_dir / "run_manifest.json").read_text("utf-8"))
    assert manifest["quality_passed"] is True
    assert any(a["type"] == "audio" and a["origin"] == "real"
               for a in manifest["artifacts"])
    assert (wf.job_dir / "thumbnail.png").exists()
    assert (wf.job_dir / "subtitles.srt").exists()
    assert (wf.job_dir / "script.md").exists()
