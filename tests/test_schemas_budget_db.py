"""数据契约、预算、SQLite 状态机的单元测试（无网络、无 FFmpeg）。"""

import pytest

from videoforge.budget import BudgetExceeded, BudgetTracker
from videoforge.db import Database
from videoforge.schemas import JobStatus, LEGAL_TRANSITIONS, ProjectRecord
from pydantic import ValidationError


def test_project_record_requires_url_and_positive_facts():
    rec = ProjectRecord(
        full_name="o/r", repo_url="https://github.com/o/r",
        created_at="2024-01-01T00:00:00Z", pushed_at="2024-02-01T00:00:00Z",
        collected_at="2024-03-01T00:00:00Z")
    assert rec.stars == 0
    with pytest.raises(ValidationError):
        ProjectRecord(full_name="x", repo_url="not-a-url",
                      created_at="t", pushed_at="t", collected_at="t")


def test_budget_records_usage_and_cost():
    b = BudgetTracker(hard_calls=10, hard_tokens=10_000,
                      price_input_per_1k=0.001, price_output_per_1k=0.002)
    b.check_before_call()
    b.record(provider="ark", kind="chat", prompt_tokens=1000, completion_tokens=500)
    assert b.calls == 1 and b.total_tokens == 1500
    assert b.estimated_cost_cny == pytest.approx(0.002)


def test_budget_hard_limits_raise():
    b = BudgetTracker(hard_calls=1, hard_tokens=10_000)
    b.record(provider="x", kind="chat", prompt_tokens=10)
    with pytest.raises(BudgetExceeded):
        b.check_before_call()
    b2 = BudgetTracker(hard_calls=99, hard_tokens=100)
    b2.record(provider="x", kind="chat", prompt_tokens=100)
    with pytest.raises(BudgetExceeded):
        b2.check_before_call()


def test_db_state_machine_happy_path(tmp_path):
    db = Database(tmp_path / "s.db")
    db.set_job_context("j1")
    db.create_job("j1", "demo", "t", {"a": 1})
    assert db.get_status("j1") == JobStatus.CREATED
    db.transition("j1", JobStatus.DISCOVERING)
    db.transition("j1", JobStatus.RESEARCHING)
    events = db.list_events("j1")
    assert [e["to_status"] for e in events] == ["discovering", "researching"]
    db.close()


def test_db_rejects_illegal_transition(tmp_path):
    db = Database(tmp_path / "s.db")
    db.create_job("j", "demo", "t", {})
    with pytest.raises(ValueError, match="非法状态迁移"):
        db.transition("j", JobStatus.COMPLETED)  # created -> completed 不合法
    db.close()


def test_db_persistence_and_artifacts(tmp_path):
    db = Database(tmp_path / "s.db")
    db.set_job_context("j")
    db.create_job("j", "real", "topic", {})
    db.record_api_call(provider="ark", kind="chat", prompt_tokens=10,
                       completion_tokens=20, estimate_cost_cny=0.01, ok=True)
    db.register_artifact("j", path="a.mp4", type="video", origin="real", sha256="x")
    db.close()

    db2 = Database(tmp_path / "s.db")  # 重开：迁移幂等、数据还在
    assert db2.get_status("j") == JobStatus.CREATED
    totals = db2.usage_totals("j")
    assert totals["calls"] == 1 and totals["prompt_tokens"] == 10
    arts = db2.list_artifacts("j")
    assert arts[0]["path"] == "a.mp4"
    db2.register_artifact("j", path="a.mp4", type="video", origin="template", sha256="y")
    assert db2.list_artifacts("j")[0]["origin"] == "template"  # upsert
    db2.close()


def test_full_lifecycle_transitions_legal():
    """合法主路径上的每一跳都必须在迁移表里。"""
    chain = [JobStatus.CREATED, JobStatus.DISCOVERING, JobStatus.RESEARCHING,
             JobStatus.VERIFYING, JobStatus.RANKING, JobStatus.SCRIPTING,
             JobStatus.STORYBOARDING, JobStatus.GENERATING_ASSETS, JobStatus.RENDERING,
             JobStatus.QUALITY_REVIEW, JobStatus.COMPLETED]
    for a, b in zip(chain, chain[1:]):
        assert b in LEGAL_TRANSITIONS[a]
