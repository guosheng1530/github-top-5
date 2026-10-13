"""命令行入口：check / demo / run / serve / jobs。

示例：
  python -m videoforge.cli check          # 环境与能力核查（含一次最小真实 LLM 调用）
  python -m videoforge.cli demo           # 零 LLM 费用闭环（真实 GitHub 数据 + 真实旁白）
  python -m videoforge.cli run            # 完整真实流水线（方舟 + GitHub）
  python -m videoforge.cli serve          # 启动本地 FastAPI（默认 127.0.0.1:8765）
"""

from __future__ import annotations

import argparse
import shutil
import sys

from videoforge import __version__
from videoforge.budget import BudgetTracker
from videoforge.config import get_settings
from videoforge.integrations.openclaw_adapter import OpenClawAdapter
from videoforge.integrations.ruflo_adapter import RufloAdapter
from videoforge.media import ffmpeg_tools
from videoforge.providers.ark_text import ArkTextClient
from videoforge.providers.base import ProviderError
from videoforge.providers.github_client import GitHubClient
from videoforge.providers.tts import TTSChain


def _build_tts_github(settings):
    """GitHub/TTS 客户端不产生 LLM 费用，demo/run 共用。"""
    github = GitHubClient(settings.github_token)
    tts = TTSChain(settings.tts_engine, settings.tts_voice,
                   settings.sapi_voice_keyword, settings.sapi_rate)
    return github, tts


def _attach_ark_client(wf):
    """把方舟客户端接到**工作流自己的预算**上：usage 才会写入 SQLite api_calls。

    （早期版本在 CLI 另建了一个无 sink 的 BudgetTracker，导致 run 结束打印用量为 0。）
    """
    s = wf.settings
    llm = ArkTextClient(api_key=s.ark_api_key, base_url=s.ark_base_url,
                        model=s.ark_model, budget=wf.budget, timeout=s.ark_timeout)
    wf.llm = llm
    wf.ctx.llm = llm
    return llm


def cmd_check(args) -> int:
    s = get_settings()
    print(f"AgentVideoForge v{__version__} 环境核查\n" + "=" * 56)
    print(f"Python      : {sys.version.split()[0]}")
    print(f"FFmpeg      : {'可用' if ffmpeg_tools.ffmpeg_available() else '❌ 不在 PATH'}")
    if ffmpeg_tools.ffmpeg_available():
        import subprocess
        v = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        print(f"             {v}")
    cjk = s.cjk_font_path
    print(f"中文字体    : {'有 → ' + cjk if cjk else '❌ 未找到（装 fonts-noto-cjk 或设 CJK_FONT_REGULAR）'}")
    oc = OpenClawAdapter().detect()
    print(f"OpenClaw    : {oc['version'] if oc['installed'] else '未安装'}")
    if oc["installed"]:
        print(f"  网关健康  : {OpenClawAdapter().gateway_health()}")
    print(f"Ruflo       : {RufloAdapter().detect()}")
    print(f"方舟文本    : key={'已配置' if s.ark_api_key else '❌ 缺失'}, model={s.ark_model}")
    print(f"  base_url  : {s.ark_base_url}")
    print(f"GitHub      : token={'已配置' if s.github_token else '未配置（低额度运行）'}")
    print(f"图片/视频/TTS: 未配置（回退程序化画面 + 本地语音）")
    if not args.no_ping and s.ark_api_key:
        print("\n正在发送最小真实请求验证方舟文本（max_tokens=16）...")
        try:
            budget = BudgetTracker(10, 100000)
            client = ArkTextClient(api_key=s.ark_api_key, base_url=s.ark_base_url,
                                   model=s.ark_model, budget=budget)
            answer = client.chat("你是连通性测试助手。", "回复：连通正常", max_tokens=16)
            print(f"✅ 方舟返回：{answer[:60]}；累计 {budget.summary()['calls']} 次调用")
            client.close()
        except ProviderError as exc:
            print(f"❌ 方舟调用失败（{exc.klass}）：{exc}")
            return 2
    print("\n核查完成。")
    return 0


def cmd_demo(args) -> int:
    from videoforge.workflow import Workflow
    s = get_settings()
    github, tts = _build_tts_github(s)
    wf = Workflow(settings=s, mode="demo", llm=None, github=github, tts=tts,
                  job_id=getattr(args, "job_id", None))
    print(f"启动 demo 任务 {wf.job_id}（零 LLM 费用；真实 GitHub 数据 + SAPI 旁白）")
    try:
        wf.run(resume=args.resume)
    finally:
        wf.close()
    print(f"\n✅ 完成：{wf.job_dir / 'final_video.mp4'}")
    print(f"   目录：{wf.job_dir}")
    return 0


def cmd_run(args) -> int:
    from videoforge.workflow import Workflow
    s = get_settings()
    if not s.ark_api_key:
        print("❌ 未配置 LLM_API_KEY；如只想免费用 demo，请运行 demo 子命令")
        return 2
    github, tts = _build_tts_github(s)
    wf = Workflow(settings=s, mode="real", llm=None, github=github, tts=tts,
                  job_id=getattr(args, "job_id", None))
    _attach_ark_client(wf)
    print(f"启动真实任务 {wf.job_id}（方舟 {s.ark_model} + GitHub）")
    try:
        wf.run(resume=args.resume)
    finally:
        wf.close()
    print(f"\n✅ 完成：{wf.job_dir / 'final_video.mp4'}")
    print(f"   LLM 用量：{wf.budget.summary()}")
    print(f"   目录：{wf.job_dir}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn
    s = get_settings()
    print(f"本地 API: http://{s.local_api_host}:{s.local_api_port}/docs  "
          f"（鉴权 {'已开启' if s.local_api_token else '未开启，仅限本机'}）")
    uvicorn.run("videoforge.api:app", host=s.local_api_host, port=s.local_api_port,
                reload=False)
    return 0


def cmd_jobs(args) -> int:
    from videoforge.db import Database
    s = get_settings()
    db = Database(s.output_root / "videoforge.db")
    for j in db.list_jobs():
        print(f"{j['job_id']}  {j['status']:<12} {j['mode']:<5} {j['topic'][:40]}")
    db.close()
    return 0


def main() -> int:
    # Windows 控制台默认 GBK，统一切到 UTF-8，避免中文日志乱码
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="videoforge", description="多 Agent 中文技术视频流水线")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="环境与能力核查"); c.add_argument("--no-ping", action="store_true")
    c.set_defaults(func=cmd_check)
    c = sub.add_parser("demo", help="零 LLM 费用 demo 闭环")
    c.add_argument("--resume", action="store_true")
    c.add_argument("--job-id", dest="job_id", default=None, help="恢复指定任务")
    c.set_defaults(func=cmd_demo)
    c = sub.add_parser("run", help="完整真实流水线")
    c.add_argument("--resume", action="store_true")
    c.add_argument("--job-id", dest="job_id", default=None, help="恢复指定任务")
    c.set_defaults(func=cmd_run)
    c = sub.add_parser("serve", help="启动本地 FastAPI"); c.set_defaults(func=cmd_serve)
    c = sub.add_parser("jobs", help="列出任务"); c.set_defaults(func=cmd_jobs)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
