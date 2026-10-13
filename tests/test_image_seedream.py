"""v1.2.0 生图接入测试：火山方舟 Agent Plan Seedream 真实调用（MockTransport）
与 VisualAgent 的优先/回退/诚实标注逻辑。

要点：
* 真实 HTTP 用 httpx.MockTransport 拦截，验证 URL(路径含 /plan 的 images/generations)、
  payload（Pro 不发 sequential_image_generation）、以及把 url/b64_json 结果**落盘**；
* 未配置能力仍抛 CapabilityUnavailable；401 为 permanent 不重试；
* VisualAgent：配置可用 → origin=real/provider=volcengine_ark_seedream；
  provider 失败且 auto+允许回退 → origin=template/provider=pillow（绝不伪装）；
  mode=seedream（强制）失败 → 向上抛，不回退。
"""

import base64
import json
import logging
from pathlib import Path

import httpx
import pytest

from videoforge.budget import BudgetTracker
from videoforge.providers.ark_media import ArkImageProvider
from videoforge.providers.base import CapabilityUnavailable, ProviderError

# 一张 4x4 的最小合法 PNG（用于 b64_json 路径与 url 下载路径）。
_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAFElEQVR4nGPkEpFjgAEm"
            "BiSAmwMADKgARF46dO4AAAAASUVORK5CYII=")
_PNG_BYTES = base64.b64decode(_PNG_B64)


def _provider_with_handler(handler, *, budget=None, model="doubao-seedream-5-0-pro"):
    prov = ArkImageProvider(
        model, api_key="ark-agentplan-fake", size="2K", output_format="png",
        watermark=False, budget=budget,
        base_url="https://ark.cn-beijing.volces.com/api/plan/v3")
    prov._client = httpx.Client(
        base_url=prov.base_url, transport=httpx.MockTransport(handler))
    return prov


def test_seedream_url_path_downloads_and_records(tmp_path):
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path.endswith("/images/generations"):
            seen["payload"] = json.loads(request.content)
            seen["path"] = request.url.path
            return httpx.Response(200, json={"data": [
                {"url": "https://signed.example/img.png"}]})
        return httpx.Response(200, content=_PNG_BYTES)

    budget = BudgetTracker(hard_calls=10, hard_tokens=1_000_000)
    prov = _provider_with_handler(handler, budget=budget)
    out = tmp_path / "scene-01.png"
    result = prov.generate("一只赛博朋克猫", out)

    assert Path(result) == out and out.exists()
    assert out.read_bytes() == _PNG_BYTES
    assert seen["path"] == "/api/plan/v3/images/generations"
    assert seen["payload"]["model"] == "doubao-seedream-5-0-pro"
    assert seen["payload"]["prompt"] == "一只赛博朋克猫"
    assert seen["payload"]["size"] == "2K"
    assert seen["payload"]["response_format"] == "url"
    assert seen["payload"]["watermark"] is False
    assert "sequential_image_generation" not in seen["payload"]
    assert "stream" not in seen["payload"]
    assert budget.calls == 1


def test_seedream_b64_path_writes_file(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"data": [{"b64_json": _PNG_B64}]})

    prov = _provider_with_handler(handler)
    out = tmp_path / "scene-02.png"
    prov.generate("主题图", out)
    assert out.read_bytes() == _PNG_BYTES


def test_non_pro_model_sends_sequential_disabled(tmp_path):
    seen = {}

    def handler(request):
        if request.url.path.endswith("/images/generations"):
            seen["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"data": [{"b64_json": _PNG_B64}]})
        return httpx.Response(200, content=_PNG_BYTES)

    prov = _provider_with_handler(handler, model="doubao-seedream-5-0")
    prov.generate("x", tmp_path / "a.png")
    assert seen["payload"].get("sequential_image_generation") == "disabled"


def test_seedream_401_permanent_no_retry(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    prov = _provider_with_handler(handler)
    with pytest.raises(ProviderError) as ei:
        prov.generate("x", tmp_path / "a.png")
    assert ei.value.klass == "permanent"
    assert calls["n"] == 1  # 鉴权错误不重试


def test_seedream_unconfigured_raises_capability(tmp_path):
    with pytest.raises(CapabilityUnavailable) as e:
        ArkImageProvider().generate("x", tmp_path / "a.png")
    assert e.value.capability == "ark_image"


# --------------------------------------------------------------------------- #
# VisualAgent：优先 Seedream / 回退 Pillow / 诚实标注
# --------------------------------------------------------------------------- #
from videoforge.config import Settings
from videoforge.db import Database
from videoforge.agents.base import AgentContext
from videoforge.agents.production import VisualAgent
from videoforge.schemas import Storyboard, StoryboardScene


def _storyboard():
    return Storyboard(scenes=[
        StoryboardScene(scene_id="scene-01", section_index=0, voiceover="开场旁白",
                        visual_type="title_card",
                        card_data={"title": "开源 Agent Top5", "subtitle": "演示"}),
        StoryboardScene(scene_id="scene-02", section_index=1, voiceover="项目一",
                        visual_type="project_card",
                        card_data={"name": "demo/agent", "one_liner": "一个演示项目",
                                   "rank": 1, "stars": 1000}),
    ])


def _ctx(tmp_path, settings, image_provider):
    db = Database(tmp_path / "t.db")
    job_id = "job-visual"
    db.set_job_context(job_id)
    db.create_job(job_id, "real", "测试", {})
    (tmp_path / "job").mkdir(parents=True, exist_ok=True)
    ctx = AgentContext(
        job_id=job_id, settings=settings, db=db,
        budget=BudgetTracker(50, 1_000_000), job_dir=tmp_path / "job",
        logger=logging.getLogger("test"), image_provider=image_provider)
    return ctx, db


class _StubProvider:
    """可控的生图 provider 替身：mode='ok' 落盘真实 PNG；'fail' 抛 ProviderError。"""
    provider_name = "volcengine_ark_seedream"
    model = "doubao-seedream-5-0-pro"
    configured = True

    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = 0

    def generate(self, prompt, out_path, *, size=None):
        self.calls += 1
        if self.mode == "fail":
            raise ProviderError("方舟生图临时错误 503", "transient")
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(_PNG_BYTES)
        return str(out_path)

    def close(self):
        pass


def test_visual_agent_uses_seedream_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "auto")
    monkeypatch.setenv("ARK_IMAGE_MODEL", "doubao-seedream-5-0-pro")
    s = Settings()
    s.output_root = tmp_path
    prov = _StubProvider("ok")
    ctx, db = _ctx(tmp_path, s, prov)
    VisualAgent(ctx).run(_storyboard())
    arts = {a["path"]: a for a in db.list_artifacts("job-visual")}
    scene_imgs = [a for p, a in arts.items() if "images/scene-" in p]
    assert scene_imgs and all(a["origin"] == "real" for a in scene_imgs)
    assert all(a["provider"] == "volcengine_ark_seedream" for a in scene_imgs)
    assert prov.calls == 2
    thumb = [a for p, a in arts.items() if p.endswith("thumbnail.png")][0]
    assert thumb["origin"] == "template"
    db.close()


def test_visual_agent_falls_back_to_pillow_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "auto")
    monkeypatch.setenv("ARK_IMAGE_MODEL", "doubao-seedream-5-0-pro")
    monkeypatch.setenv("IMAGE_FALLBACK_TO_TEMPLATE", "1")
    s = Settings()
    s.output_root = tmp_path
    ctx, db = _ctx(tmp_path, s, _StubProvider("fail"))
    VisualAgent(ctx).run(_storyboard())
    arts = {a["path"]: a for a in db.list_artifacts("job-visual")}
    scene_imgs = [a for p, a in arts.items() if "images/scene-" in p]
    assert scene_imgs and all(a["origin"] == "template" for a in scene_imgs)
    assert all(a["provider"] == "pillow" for a in scene_imgs)
    db.close()


def test_visual_agent_force_seedream_does_not_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "seedream")
    monkeypatch.setenv("ARK_IMAGE_MODEL", "doubao-seedream-5-0-pro")
    s = Settings()
    s.output_root = tmp_path
    ctx, db = _ctx(tmp_path, s, _StubProvider("fail"))
    with pytest.raises(ProviderError):
        VisualAgent(ctx).run(_storyboard())
    db.close()


def test_visual_agent_pillow_when_no_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "auto")
    s = Settings()
    s.output_root = tmp_path
    ctx, db = _ctx(tmp_path, s, None)
    VisualAgent(ctx).run(_storyboard())
    arts = {a["path"]: a for a in db.list_artifacts("job-visual")}
    scene_imgs = [a for p, a in arts.items() if "images/scene-" in p]
    assert scene_imgs and all(a["origin"] == "template" for a in scene_imgs)
    db.close()
