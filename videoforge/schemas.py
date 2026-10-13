"""全部 Pydantic 数据契约。

为什么几乎每个阶段都定义 schema？
---------------------------------
大模型输出是非确定的自由文本。把它约束成 *字段固定、类型可校验* 的模型后，
程序才能安全地把上一阶段结果交给下一阶段；校验失败必须被捕获、修复或中止，
绝不能把脏数据静默带进视频。

学习顺序：ProjectRecord -> ProjectProfile -> RankedProject -> Script ->
Storyboard -> SubtitleFile -> ArtifactRef -> QualityReport -> RunManifest。
"""

from __future__ import annotations

import enum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


# --------------------------------------------------------------------------- #
# 任务与状态
# --------------------------------------------------------------------------- #
class JobStatus(str, enum.Enum):
    """业务状态机的全部状态。异常分支也显式建模。"""

    CREATED = "created"
    DISCOVERING = "discovering"
    RESEARCHING = "researching"
    VERIFYING = "verifying"
    RANKING = "ranking"
    SCRIPTING = "scripting"
    STORYBOARDING = "storyboarding"
    GENERATING_ASSETS = "generating_assets"
    RENDERING = "rendering"
    QUALITY_REVIEW = "quality_review"
    WAITING_FOR_CONFIG = "waiting_for_config"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 允许的状态迁移（工作流控制器据此拒绝非法跳转）
LEGAL_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.CREATED: {JobStatus.DISCOVERING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.DISCOVERING: {JobStatus.RESEARCHING, JobStatus.WAITING_FOR_CONFIG, JobStatus.FAILED},
    JobStatus.RESEARCHING: {JobStatus.VERIFYING, JobStatus.RETRYING, JobStatus.FAILED},
    JobStatus.VERIFYING: {JobStatus.RANKING, JobStatus.RETRYING, JobStatus.FAILED},
    JobStatus.RANKING: {JobStatus.SCRIPTING, JobStatus.RETRYING, JobStatus.FAILED},
    JobStatus.SCRIPTING: {JobStatus.STORYBOARDING, JobStatus.RETRYING, JobStatus.FAILED},
    JobStatus.STORYBOARDING: {JobStatus.GENERATING_ASSETS, JobStatus.RETRYING, JobStatus.FAILED},
    JobStatus.GENERATING_ASSETS: {JobStatus.RENDERING, JobStatus.RETRYING, JobStatus.FAILED},
    JobStatus.RENDERING: {JobStatus.QUALITY_REVIEW, JobStatus.RETRYING, JobStatus.FAILED},
    JobStatus.QUALITY_REVIEW: {
        JobStatus.COMPLETED, JobStatus.RETRYING, JobStatus.RENDERING,
        JobStatus.GENERATING_ASSETS, JobStatus.FAILED,
    },
    JobStatus.RETRYING: {
        JobStatus.VERIFYING, JobStatus.SCRIPTING, JobStatus.STORYBOARDING,
        JobStatus.GENERATING_ASSETS, JobStatus.RENDERING, JobStatus.QUALITY_REVIEW, JobStatus.FAILED,
    },
    JobStatus.WAITING_FOR_CONFIG: {JobStatus.DISCOVERING, JobStatus.CANCELLED},
}


class StageName(str, enum.Enum):
    DISCOVERY = "discovery"
    RESEARCH = "research"
    FACT_CHECK = "fact_check"
    RANKING = "ranking"
    SCRIPT = "script"
    STORYBOARD = "storyboard"
    VISUAL = "visual"
    VOICE = "voice"
    RENDER = "render"
    QA = "qa"


# --------------------------------------------------------------------------- #
# 发现 / 研究 / 核验
# --------------------------------------------------------------------------- #
class ProjectRecord(BaseModel):
    """GitHub 仓库的“事实卡”。所有数字都来自 GitHub REST API 并带采集时间。"""

    full_name: str
    repo_url: HttpUrl
    description: str = ""
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    open_issues: int = 0
    language: str | None = None
    license: str | None = None
    topics: list[str] = Field(default_factory=list)
    created_at: str
    pushed_at: str
    archived: bool = False
    collected_at: str
    evidence_urls: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    """一条待核验声明。"""

    text: str
    status: Literal["verified", "uncertain", "false"] = "uncertain"
    evidence: str = ""
    source_url: str | None = None


class ProjectProfile(BaseModel):
    """Research Agent 的产物：README + API 事实 → 结构化资料卡。"""

    record: ProjectRecord
    one_liner: str = ""
    features: list[str] = Field(default_factory=list)
    architecture: str = ""
    install_hint: str = ""
    limitations: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    readme_fetched: bool = False
    evidence_urls: list[str] = Field(default_factory=list)


class RankedProject(BaseModel):
    """Ranking Agent 的产物：可复现的启发式评分 + 中文点评。"""

    profile: ProjectProfile
    rank: int
    score_stars: float
    score_recency: float
    score_fit: float
    score_license: float
    total_score: float
    rationale: str = ""


# --------------------------------------------------------------------------- #
# 编剧 / 分镜
# --------------------------------------------------------------------------- #
class ScriptSection(BaseModel):
    kind: Literal["intro", "overview", "project", "outro"] = "project"
    project_full_name: str | None = None
    title: str
    narration: str = Field(description="逐字口播稿，中文普通话")
    on_screen_bullets: list[str] = Field(default_factory=list)


class Script(BaseModel):
    title: str
    sections: list[ScriptSection]

    @property
    def narration_chars(self) -> int:
        return sum(len(s.narration) for s in self.sections)


class StoryboardScene(BaseModel):
    scene_id: str
    section_index: int
    duration_sec: float = Field(default=0.0, description="初估时长；配音后以实测音频时长回填")
    voiceover: str
    visual_type: Literal[
        "title_card", "ranking_card", "project_card", "section_card", "end_card"
    ]
    card_data: dict[str, Any] = Field(default_factory=dict)
    on_screen_text: str = ""
    transition: Literal["fade", "none"] = "fade"
    source_assets: list[str] = Field(default_factory=list)
    generation_required: bool = False  # 本项目全部使用程序化画面，恒为 False


class Storyboard(BaseModel):
    scenes: list[StoryboardScene]


# --------------------------------------------------------------------------- #
# 字幕 / 素材 / 质检 / 清单
# --------------------------------------------------------------------------- #
class SubtitleCue(BaseModel):
    index: int
    start_sec: float
    end_sec: float
    text: str


class SubtitleFile(BaseModel):
    cues: list[SubtitleCue]


class ArtifactRef(BaseModel):
    """任何产物（图/音/视频/JSON）的可追溯记录。"""

    path: str
    type: Literal["image", "audio", "video", "data", "subtitle", "log", "thumbnail"]
    origin: Literal["real", "template", "synthetic"]
    sha256: str
    provider: str = ""
    model: str = ""
    job_id: str | None = None
    created_at: str
    note: str = ""


class QAIssue(BaseModel):
    issue_id: str
    severity: Literal["high", "medium", "low"]
    scene_id: str | None = None
    owner_agent: str
    repair_instruction: str
    evidence: str
    retry_count: int = 0
    status: Literal["open", "fixed", "wontfix"] = "open"


class QualityReport(BaseModel):
    passed: bool
    duration_sec: float = 0
    video_codec: str = ""
    audio_codec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0
    audio_mean_volume_db: float | None = None
    issues: list[QAIssue] = Field(default_factory=list)
    asset_origins: dict[str, int] = Field(default_factory=dict)
    checks: dict[str, bool] = Field(default_factory=dict)
    rework_round: int = 0


class RunManifest(BaseModel):
    """最终交付清单：逐条说明素材是真实 API 还是模板/合成。"""

    job_id: str
    mode: Literal["real", "demo"]
    created_at: str
    completed_at: str | None = None
    topic: str
    settings: dict[str, Any]
    capabilities: dict[str, str]
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    llm_calls: int = 0
    llm_tokens: int = 0
    estimated_cost_cny: float = 0
    cost_disclaimer: str = "估算仅供参考，不代表火山方舟真实账单（Coding Plan 通常为套餐制）"
    final_video: str = ""
    subtitles: str = ""
    quality_passed: bool = False
