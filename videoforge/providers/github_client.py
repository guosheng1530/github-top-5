"""GitHub REST API 客户端（真实数据源）。

职责边界（Discovery Agent 只负责收集，不负责排名）：
* :meth:`search_agent_repos` —— 用多个查询召回近期仍活跃的 AI Agent 候选仓库；
* :meth:`get_repo` —— 对每个候选再发一次 ``GET /repos/{owner}/{repo}`` 复核，
  搜索接口结果不直接当事实，防止异常/缓存数据进入视频；
* :meth:`get_readme` —— 取默认分支上的 README 原文（供 Research Agent 阅读）。

限流：search 接口 30 次/分钟（带 token）。查询之间主动 sleep，429 按
Retry-After/退避处理（tenacity）。所有数字记录采集时间——
“总 Star 数”不等于“近期趋势”，这一点在排名阶段会被显式说明。
"""

from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from videoforge.providers.base import ProviderError


class GitHubClient:
    API = "https://api.github.com"

    def __init__(self, token: str = "", min_delay_sec: float = 2.2):
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "agent-video-forge/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(timeout=30, headers=headers)
        self._min_delay = min_delay_sec
        self._last_search = 0.0

    @retry(reraise=True, stop=stop_after_attempt(4),
           wait=wait_exponential(multiplier=2, min=3, max=30),
           retry=retry_if_exception_type(ProviderError))
    def _get(self, url: str, params: dict | None = None) -> Any:
        resp = self._client.get(url, params=params)
        if resp.status_code in (429, 500, 502, 503):
            wait = float(resp.headers.get("Retry-After", "5"))
            time.sleep(min(wait, 30) if resp.status_code == 429 else 3)
            raise ProviderError(f"GitHub 临时错误 {resp.status_code}", "transient",
                                resp.status_code)
        if resp.status_code == 404:
            raise ProviderError(f"GitHub 404: {url}", "permanent", 404)
        if resp.status_code >= 400:
            raise ProviderError(f"GitHub 错误 {resp.status_code}: {resp.text[:200]}",
                                "permanent", resp.status_code)
        remaining = int(resp.headers.get("X-RateLimit-Remaining", "1"))
        if remaining <= 1:
            reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
            time.sleep(max(1, min(reset - time.time() + 1, 40)))
        return resp.json()

    def _search_throttled(self, query: str, sort: str, per_page: int) -> dict:
        wait = self._min_delay - (time.time() - self._last_search)
        if wait > 0:
            time.sleep(wait)
        try:
            return self._get(f"{self.API}/search/repositories",
                             {"q": query, "sort": sort, "per_page": per_page})
        finally:
            self._last_search = time.time()

    def search_agent_repos(self, *, min_stars: int, pushed_within_days: int,
                           per_page: int = 30) -> list[dict]:
        """多查询召回。返回搜索接口的原始 items（之后必须逐个 GET 复核）。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=pushed_within_days)).strftime("%Y-%m-%d")
        queries = [
            f"topic:ai-agents stars:>{min_stars} pushed:>{cutoff}",
            f"topic:llm-agents stars:>{min_stars} pushed:>{cutoff}",
            f"topic:agent-framework stars:>{min_stars} pushed:>{cutoff}",
            f"ai agent in:name,description,topics stars:>{min_stars} pushed:>{cutoff}",
        ]
        seen: dict[str, dict] = {}
        for q in queries:
            try:
                data = self._search_throttled(q, "stars", per_page)
            except ProviderError:
                continue
            for item in data.get("items", []):
                seen[item["full_name"].lower()] = item
        return list(seen.values())

    def get_repo(self, full_name: str) -> dict:
        return self._get(f"{self.API}/repos/{full_name}")

    def get_readme(self, full_name: str, max_chars: int = 12000) -> tuple[str, bool]:
        """返回 (README 纯文本/markdown 原文, 是否成功)。优先 README.md，解码 base64。"""
        try:
            data = self._get(f"{self.API}/repos/{full_name}/readme")
        except ProviderError:
            return "", False
        try:
            if data.get("encoding") == "base64":
                raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            else:
                import httpx as _h
                r = self._client.get(data["download_url"])
                raw = r.text if r.status_code == 200 else ""
            return raw[:max_chars], bool(raw)
        except Exception:
            return "", False

    def close(self) -> None:
        self._client.close()
