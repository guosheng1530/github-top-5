# AgentVideoForge —— 多 Agent 中文技术视频自动生成流水线

输入一句主题（默认：近期热门的 GitHub AI Agent 项目 Top 5），系统自动完成
**发现 → 并行研究 → 事实核验 → 排名 → 中文编剧 → 分镜 → 信息卡画面 → 中文配音 →
字幕 → FFmpeg 合成 → 自动质检（最多两轮返工）**，产出可播放的 1080p MP4。

本仓库同时是两样东西：

1. **生产工具**：真的能跑出视频；
2. **学习项目**：[docs/TECHNICAL_MANUAL.md](docs/TECHNICAL_MANUAL.md) 逐模块解释
   Agent、Pydantic 契约、SQLite 状态机、API 适配器、预算幂等、FFmpeg、自动化测试。

## 快速开始（Windows）

```powershell
# 1) 初始化（建虚拟环境、装依赖、生成 .env）
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 2) 编辑 .env 填入 LLM_API_KEY / GITHUB_TOKEN（已自带 .env 可跳过）

# 3) 环境核查（会发一次最小真实 LLM 请求）
scripts\check.ps1

# 4) 零费用先跑通 demo（真实 GitHub 数据 + SAPI 离线中文旁白 + FFmpeg 成片）
scripts\demo.ps1

# 5) 正式生成（火山方舟文本研究/编剧，约 5 分钟成片）
scripts\run.ps1

# 6) 运行全部测试
scripts\tests.ps1
```

## 快速开始（Linux / macOS）

```bash
# 0) 系统依赖（一次性）
#    Linux : sudo apt install ffmpeg fonts-noto-cjk     # 中文字体必装，否则信息卡/字幕是方块
#    macOS : brew install ffmpeg                         # 中文字体系统自带

# 1) 初始化（建 .venv、装依赖、生成 .env）
bash scripts/setup.sh

# 2) 编辑 .env 填入 LLM_API_KEY / GITHUB_TOKEN（已自带 .env 可跳过）

# 3) 环境核查（会发一次最小真实 LLM 请求；加 --no-ping 跳过）
bash scripts/check.sh            # 或 ./scripts/check.sh

# 4) 零费用先跑通 demo（真实 GitHub 数据 + 旁白 + FFmpeg 成片）
bash scripts/demo.sh

# 5) 正式生成（火山方舟文本研究/编剧，约 5 分钟成片）
bash scripts/run.sh

# 6) 运行全部测试
bash scripts/tests.sh
```

> **跨平台说明**：所有脚本都会**自动探测**虚拟环境里的 Python，无需手动指定。
> 查找顺序：`.venv`（当前平台原生布局）→ 平台回退目录（Linux 用 `.venv-linux`，
> Windows 用 `.venv-windows`）→ 系统 `python3`/`py`。因此同一份代码在 Linux、
> macOS、Windows 上都能直接用对应的 `.sh` / `.ps1` 启动。
> **虚拟环境不可跨平台移植，也不会被提交**（见 `.gitignore`）；换机器后请重新
> 运行 `setup`。配音在 Windows 默认走系统 SAPI5 离线语音，Linux/macOS 默认
> `auto`（edge-tts → 合成兜底）。

产物在 `output/<job_id>/`：

| 文件 | 说明 |
|---|---|
| `final_video.mp4` | 1920x1080 / 30fps / H.264 + AAC 中文成片 |
| `thumbnail.png` | 封面 |
| `subtitles.srt` | 中文字幕（按实测音频时长对齐） |
| `script.md` | 口播脚本 |
| `top5_projects.json` | Top5 与可复现评分 |
| `storyboard.json` | 分镜（含每镜实测时长） |
| `quality_report.md/json` | ffprobe 质检报告与问题单 |
| `run_manifest.json` | 每个素材的 real/template/synthetic 来源清单 |
| `research/`、`assets/` | 候选、资料卡、核验结果、画面、配音、分段 |
| `run.log.jsonl` | 脱敏审计日志 |

## 能力与诚实标注（2026-10-12 实测）

| 能力 | 状态 | 说明 |
|---|---|---|
| 火山方舟文本 | ✅ 已验证 | Key 属 Coding Plan：`/api/plan/v3`，模型 `ark-code-latest` |
| GitHub 数据 | ✅ 已验证 | Search/Repository/README 接口，Token 用户 guosheng1530 |
| 中文配音 | ✅ 真实语音 | Windows SAPI5「Microsoft Huihui」离线合成；edge-tts 因代理风控 403 作可选 |
| 画面 | 程序化信息卡 | Pillow 生成，全部标 `origin=template`；不调用图片生成 API |
| 方舟图片/视频/TTS | ⛔ 未开通 | 此 Key 对标准 `/api/v3` 为 401；适配器调用即抛 `CapabilityUnavailable` |
| OpenClaw 2026.4.11 | 已安装 | 健康探测可用；网关默认 18789，通知需 `OPENCLAW_NOTIFY=1` 显式开启 |
| Ruflo | 未安装 | npm `ruflo` 实测归属 `ruvnet/claude-flow`，适配器拒绝猜测式调用 |

系统**绝不**把模板画面或合成音轨伪装成 AI 生成内容；`run_manifest.json`
逐素材标注来源。

## 常用配置（.env）

`LLM_API_KEY / LLM_BASE_URL / LLM_MODEL`、`GITHUB_TOKEN`、
`VIDEO_WIDTH/HEIGHT/VIDEO_FPS/TARGET_DURATION_SEC`、
`CANDIDATE_POOL/MIN_STARS/PUSHED_WITHIN_DAYS/RESEARCH_PARALLEL`、
`TTS_ENGINE`（`sapi` 默认 / `edge` / `auto` / `synthetic`）、
`HARD_BUDGET_CALLS/HARD_BUDGET_TOKENS`、
`LOCAL_API_HOST/PORT/TOKEN`。详见 [.env.example](.env.example)。

## 本地 API（可选）

```powershell
scripts\serve.ps1          # http://127.0.0.1:8765/docs
```

`POST /jobs?mode=demo|real`、`GET /jobs`、`GET /jobs/{id}`、
`GET /jobs/{id}/artifacts`；默认只绑本机，设置 `LOCAL_API_TOKEN` 后需带 `X-API-TOKEN`。

## 架构一句话

SQLite 是业务最终状态的唯一权威；工作流控制器管 DAG/预算/返工；
10 个 Agent 各自有独立 system prompt、Pydantic 契约、工具白名单和失败策略；
Provider 可替换；FFmpeg 是确定性工具（参数数组调用，禁止 shell 拼接）。

深入学习请从 [docs/TECHNICAL_MANUAL.md](docs/TECHNICAL_MANUAL.md) 开始。
