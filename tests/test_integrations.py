"""集成适配器测试：只验证真实探测行为，不伪造平台调用。"""

from videoforge.integrations.openclaw_adapter import OpenClawAdapter
from videoforge.integrations.ruflo_adapter import RufloAdapter


def test_openclaw_detect_returns_bool_dict():
    info = OpenClawAdapter().detect()
    assert set(info) >= {"installed", "version", "path"}
    # CI/无 openclaw 机器上 installed=False 也算通过；本机应为 True
    if info["installed"]:
        assert "2026" in (info["version"] or "") or info["version"]


def test_openclaw_notify_default_off():
    r = OpenClawAdapter(notify_enabled=False).notify_completion("j", "x.mp4", True)
    assert r["sent"] is False


def test_ruflo_reports_uninstalled_or_real_path():
    info = RufloAdapter().detect()
    assert info["npm_package"] == "ruflo"
    assert "claude-flow" in info["repository"]  # npm view 实测结论
    if not info["installed"]:
        assert info["path"] is None
        # 未安装时拒绝触发，绝不猜测命令
        r = RufloAdapter().trigger("swarm")
        assert r["triggered"] is False
