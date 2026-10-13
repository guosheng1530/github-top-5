"""Provider 层测试：方舟 JSON 解析/修复（mock）、脱敏、未开通媒体能力。"""

import httpx
import pytest

from videoforge.budget import BudgetTracker
from videoforge.logging_utils import redact
from videoforge.providers.ark_text import ArkTextClient
from videoforge.providers.ark_media import (ArkImageProvider, ArkSpeechProvider,
                                           ArkVideoProvider)
from videoforge.providers.base import CapabilityUnavailable, ProviderError


def _client_with_handler(handler):
    budget = BudgetTracker(hard_calls=20, hard_tokens=1_000_000)
    client = ArkTextClient.__new__(ArkTextClient)  # 不走真实 __init__
    client.model = "test-model"
    client.budget = budget
    client._client = httpx.Client(base_url="https://ark.test/api/v3",
                                  transport=httpx.MockTransport(handler))
    return client, budget


def test_redact_masks_all_secret_shapes():
    text = ("key=ark-c87d3909-aaaa token=github_pat_11APDXZ5Y0secretvalue "
            "Authorization: Bearer ghp_abcdef1234567890")
    out = redact(text)
    assert "c87d3909" not in out and "secretvalue" not in out and "abcdef" not in out
    assert "REDACTED" in out


def test_ark_chat_returns_usage():
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "你好"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7}})
    client, budget = _client_with_handler(handler)
    assert client.chat("s", "u") == "你好"
    assert budget.total_tokens == 12


def test_ark_usage_reaches_sink():
    """CLI/API 必须把带 DB sink 的预算接到客户端（真实任务曾因两个预算对象
    并存导致 api_calls 表 0 行、结尾用量打印为 0）。"""
    rows = []

    class Sink:
        def record_api_call(self, **kw):
            rows.append(kw)

    budget = BudgetTracker(hard_calls=5, hard_tokens=100_000, sink=Sink())
    client = ArkTextClient.__new__(ArkTextClient)
    client.model = "test-model"
    client.budget = budget

    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 22}})

    client._client = httpx.Client(base_url="https://ark.test/api/v3",
                                  transport=httpx.MockTransport(handler))
    client.chat("s", "u")
    assert len(rows) == 1
    assert rows[0]["provider"] == "volcengine_ark"
    assert rows[0]["prompt_tokens"] == 11 and rows[0]["completion_tokens"] == 22


def test_ark_chat_json_strips_code_fence():
    payload = '{"a": 1, "b": "中文"}'
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": f"```json\n{payload}\n```"}}],
            "usage": {}})
    client, _ = _client_with_handler(handler)
    assert client.chat_json("s", "u") == {"a": 1, "b": "中文"}


def test_ark_chat_json_repair_once():
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        body = "这不是JSON" if calls["n"] == 1 else '{"ok": true}'
        return httpx.Response(200, json={
            "choices": [{"message": {"content": body}}], "usage": {}})
    client, _ = _client_with_handler(handler)
    assert client.chat_json("s", "u") == {"ok": True}
    assert calls["n"] == 2


def test_ark_401_is_permanent_no_retry():
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})
    client, _ = _client_with_handler(handler)
    with pytest.raises(ProviderError) as ei:
        client.chat("s", "u")
    assert ei.value.klass == "permanent"
    assert calls["n"] == 1  # 鉴权错误绝不重试（也不会产生多笔计费）


def test_transient_failures_are_retried_and_recorded_ok_false(monkeypatch):
    """坏网络窗口下重试 6 次；每次失败都以 ok=0 落库（审计口径含失败尝试）。"""
    import tenacity
    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda *_: None)  # 跳过退避等待
    rows = []

    class Sink:
        def record_api_call(self, **kw):
            rows.append(kw)

    budget = BudgetTracker(hard_calls=20, hard_tokens=1_000_000, sink=Sink())
    client = ArkTextClient.__new__(ArkTextClient)
    client.model = "test-model"
    client.budget = budget

    def handler(request):
        return httpx.Response(503, text="busy")

    client._client = httpx.Client(base_url="https://ark.test/api/v3",
                                  transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as ei:
        client.chat("s", "u")
    assert ei.value.klass == "transient"
    assert len(rows) == 6
    assert all(r["ok"] is False and "503" in r["redacted_error"] for r in rows)


def test_unconfigured_media_capabilities_raise():
    with pytest.raises(CapabilityUnavailable) as e:
        ArkImageProvider().generate("x")
    assert e.value.capability == "ark_image"
    with pytest.raises(CapabilityUnavailable):
        ArkVideoProvider().submit("x")
    with pytest.raises(CapabilityUnavailable):
        ArkSpeechProvider().synthesize("x")
