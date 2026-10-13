"""AgentVideoForge —— 多 Agent 中文技术视频自动生成流水线。

模块导航（也是建议的学习顺序）：

1. :mod:`videoforge.config`         环境变量与能力开关
2. :mod:`videoforge.schemas`        全部 Pydantic 数据契约
3. :mod:`videoforge.db`             SQLite 状态机与产物索引
4. :mod:`videoforge.budget`         调用计数 / 用量 / 预算
5. :mod:`videoforge.providers`      外部能力适配器（方舟 / GitHub / TTS）
6. :mod:`videoforge.agents`         10 个专业 Agent
7. :mod:`videoforge.media`          Pillow 画面、SRT、FFmpeg 合成
8. :mod:`videoforge.workflow`       DAG 控制器（编排上面所有东西）
"""

__version__ = "1.3.0"
