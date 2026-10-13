"""可选的本地任务 API（FastAPI）。

安全默认值：
* 绑定 127.0.0.1，不暴露公网；
* 设置了环境变量 LOCAL_API_TOKEN 时，每个请求必须带 ``X-API-TOKEN``；
* 只暴露任务的启动/查询/产物索引，不提供任意文件读写。

启动：python -m videoforge.cli serve
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException

from videoforge.config import get_settings
from videoforge.db import Database
from videoforge.workflow import Workflow

settings = get_settings()
app = FastAPI(title="AgentVideoForge", version="1.0.0")

_jobs_lock = threading.Lock()


def _check_token(x_api_token: str | None = Header(default=None)) -> None:
    token = settings.local_api_token
    if token and x_api_token != token:
        raise HTTPException(status_code=401, detail="需要 X-API-TOKEN")


def _db() -> Database:
    return Database(settings.output_root / "videoforge.db")


def _start(mode: str, topic: str) -> str:
    # 先在主线程构造以获得 job_id；HTTP/TTS 客户端不跨线程共享，run 内在线程里重建。
    with _jobs_lock:
        from videoforge.providers.github_client import GitHubClient
        from videoforge.providers.tts import TTSChain
        github = GitHubClient(settings.github_token)
        tts = TTSChain(settings.tts_engine, settings.tts_voice,
                       settings.sapi_voice_keyword, settings.sapi_rate)
        wf = Workflow(settings=settings, mode=mode, topic=topic,
                      llm=None, github=github, tts=tts)
        job_id = wf.job_id
        wf.db.close()

    def runner() -> None:
        from videoforge.providers.github_client import GitHubClient
        from videoforge.providers.tts import TTSChain
        tts = TTSChain(settings.tts_engine, settings.tts_voice,
                       settings.sapi_voice_keyword, settings.sapi_rate)
        github = GitHubClient(settings.github_token)
        # 必须把同一个 job_id 传进去（早期版本这里漏传，线程里生成了新 ID，
        # 导致 API 返回的任务和真正在跑的任务对不上）。
        wf = Workflow(settings=settings, mode=mode, topic=topic,
                      llm=None, github=github, tts=tts, job_id=job_id)
        if mode == "real":
            from videoforge.providers.ark_text import ArkTextClient
            llm = ArkTextClient(api_key=settings.ark_api_key, base_url=settings.ark_base_url,
                                model=settings.ark_model, budget=wf.budget,
                                timeout=settings.ark_timeout)
            wf.llm = llm
            wf.ctx.llm = llm
        wf.run()

    threading.Thread(target=runner, name=f"job-{job_id}", daemon=True).start()
    return job_id


@app.get("/health", dependencies=[Depends(_check_token)])
def health():
    return {"ok": True}


@app.post("/jobs", dependencies=[Depends(_check_token)])
def create_job(mode: str = "demo", topic: str = "近期热门 AI Agent 开源项目 Top 5"):
    if mode not in ("demo", "real"):
        raise HTTPException(400, "mode 仅支持 demo / real")
    return {"job_id": _start(mode, topic)}


@app.get("/jobs", dependencies=[Depends(_check_token)])
def list_jobs():
    db = _db()
    try:
        return db.list_jobs()
    finally:
        db.close()


@app.get("/jobs/{job_id}", dependencies=[Depends(_check_token)])
def get_job(job_id: str):
    db = _db()
    try:
        jobs = [j for j in db.list_jobs(100) if j["job_id"] == job_id]
        if not jobs:
            raise HTTPException(404, "job 不存在")
        job = jobs[0]
        job["events"] = db.list_events(job_id)[-12:]
        job["usage"] = db.usage_totals(job_id)
        return job
    finally:
        db.close()


@app.get("/jobs/{job_id}/artifacts", dependencies=[Depends(_check_token)])
def get_artifacts(job_id: str):
    db = _db()
    try:
        return db.list_artifacts(job_id)
    finally:
        db.close()
