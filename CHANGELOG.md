# 更新日志（Changelog）

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)（SemVer）与
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 约定。

版本号规则（`MAJOR.MINOR.PATCH`）：
- **MAJOR**：不兼容的行为/接口变更（如 CLI 子命令删除、产物格式破坏性调整）；
- **MINOR**：向后兼容的功能新增（如新增平台支持、新子命令、新能力开关）；
- **PATCH**：向后兼容的缺陷修复、文档与内部重构。

类别：`新增` / `变更` / `修复` / `移除` / `安全`。

---

## [未发布]

（下一版改动先记录在此，发布时移动到带版本号的小节并打 tag。）

### 文档
- README 新增「换机/新检出后启用 Seedream 生图」小节：因 `.env` 不入库，说明拉取 tag 到
  新机器后如何重新配置 `ARK_IMAGE_MODEL` 启用真实生图，以及 check/manifest 的核验方法。

---

## [1.3.0] - 2026-10-13

把火山方舟 Agent Plan 的 Seedream 生图从「可选可接入」正式**启用为 VisualAgent 默认画面
来源**，并完成端到端实测。

### 变更
- **启用 Seedream 生图为 VisualAgent 默认画面来源**：`.env` 填入
  `ARK_IMAGE_MODEL=doubao-seedream-5-0-pro`（`ARK_IMAGE_BASE_URL` 用 Agent Plan 专属
  `…/api/plan/v3`，`ARK_IMAGE_API_KEY` 留空回退 `LLM_API_KEY`），`IMAGE_PROVIDER=auto`
  下分镜画面首选真实生图，失败回退 Pillow 信息卡。
- README 能力表「画面 / 方舟图片」由「可选可接入」更新为「✅ 已实测启用」。
- `videoforge/__init__.py` 版本号 → 1.3.0。

### 文档
- `docs/TECHNICAL_MANUAL.md` 6.5 节标注「已启用并端到端实测」，并新增 6.5.1（一次真实
  请求/响应长什么样）、6.5.2（分镜→prompt 数据流）、6.5.3（如何验证它确实工作：
  check/manifest/api_calls/日志/强制模式五法）；9.1 节同步更新为“已启用”。

### 验证
- 本机 2026-10-13 实测：对 `doubao-seedream-5-0-pro` 的
  `POST /api/plan/v3/images/generations` 返回 **HTTP 200** 并产出真实图片。
- 以 `IMAGE_PROVIDER=seedream`（强制、不回退）跑完整 `run`：8 个分镜画面**全部**
  `origin=real` / `provider=volcengine_ark_seedream`，`api_calls` 记 8 次 `kind=image`
  成功；`capabilities.ark_image=verified (Agent Plan plan/v3, doubao-seedream-5-0-pro,`
  `size=2K)`、`settings.image_provider=seedream:doubao-seedream-5-0-pro`；最终输出
  H.264/AAC、1920×1080、约 439s 的 `final_video.mp4`（约 29MB），QA 零高优先级问题；
  缩略图仍 `template/pillow`。
- 诚实标注：本次运行在 Linux 上 edge-tts 403、无 SAPI，配音按既有降级链落到
  `ffmpeg_synthetic`（真实语音 0/8，标 `synthetic`），与生图改动无关，`run_manifest`
  如实记录。
- `pytest -q` → 40 passed（改动不破坏现有测试）。

---

## [1.2.0] - 2026-10-13

接入火山方舟 Agent Plan 的 Seedream 生图 API，作为 VisualAgent 的首选画面来源，
Pillow 程序化信息卡降级兜底；严格保持「诚实标注」原则。

### 新增
- `providers/ark_media.py` 的 `ArkImageProvider` 从占位改为**真实实现**：调用
  `POST {ARK_IMAGE_BASE_URL}/images/generations`（OpenAI 兼容），解析
  `data[0].url`（临时签名 URL，立即下载落盘）或 `data[0].b64_json`，tenacity 仅对
  transient（429/5xx/网络）重试，401/403 为 permanent 不重试，成功一张计一次预算
  （`kind=image`），错误文本经日志脱敏。`doubao-seedream-5-0-pro` / `-flash` 不下发
  `sequential_image_generation` / `stream`（传了会 400）。
- `config.py` 新增 Agent Plan 生图配置：`ARK_IMAGE_BASE_URL`（默认 Agent Plan 专属
  `…/api/plan/v3`）、`ARK_IMAGE_API_KEY`（留空回退 `LLM_API_KEY`）、`ARK_IMAGE_SIZE`、
  `ARK_IMAGE_OUTPUT_FORMAT`、`ARK_IMAGE_WATERMARK`、`ARK_IMAGE_TIMEOUT`、
  `IMAGE_PROVIDER`（auto/pillow/seedream）、`IMAGE_FALLBACK_TO_TEMPLATE`。
- `VisualAgent` 优先用 Seedream 为每个分镜生成画面（`origin=real`、
  `provider=volcengine_ark_seedream`、记录 `model`）；未配置或调用失败时回退 Pillow
  信息卡（`origin=template`）；`IMAGE_PROVIDER=seedream` 为强制模式，失败即报错不回退。
  封面缩略图始终用 Pillow（保证标题文字准确）。
- `cli.py`：`run` 子命令按配置接入 Seedream 并计量到工作流预算；`check` 子命令显示
  生图能力（模型 / 尺寸 / 水印 / 专属 Base URL）或未配置提示。
- 新增测试 `tests/test_image_seedream.py`：用 `httpx.MockTransport` 验证真实请求的
  URL（Agent Plan `/api/plan/v3/images/generations`）与 payload、url/b64 两条落盘路径、
  401 不重试、未配置抛 `CapabilityUnavailable`；并覆盖 VisualAgent 的
  优先/回退/强制不回退/无 provider 四种分支与诚实的 origin 标注。

### 变更
- `AgentContext` 新增 `image_provider` 字段；`Workflow` 构造函数新增 `image_provider`
  参数并在 `close()` 中一并释放；`run_manifest.json` 的 `settings.image_provider`
  如实记录实际画面来源（`seedream:<model>` 或 `pillow`）；`capabilities.ark_image`
  按配置动态显示 `verified (Agent Plan …)` 或 `not_configured`。

### 安全 / 诚实标注
- **Agent Plan 专属性**：Agent Plan 必须用专属 API Key + 专属 Base URL（路径含
  `/plan`）；Coding Plan 的 Key 无法在 Agent Plan 调用（401）。文档与 `check` 均明确提示。
- 系统**绝不**把 Pillow 回退画面标成 AI 生成：Seedream 成功才标 `real`，回退一律标
  `template`，逐素材记录于 `run_manifest.json`。

### 验证
- Linux 实测：`pytest -q` → 40 passed（31 基线 + 9 新增；含 Seedream MockTransport
  与 VisualAgent 回退用例）。

---

## [1.1.0] - 2026-10-13

跨平台发布：同一份代码可在 Linux、macOS、Windows 上运行。

### 新增
- Linux/macOS 启动脚本：`scripts/{setup,check,demo,run,serve,tests}.sh`。
- 共享虚拟环境探测辅助 `scripts/_venv.sh` 与 `scripts/_venv.ps1`：按
  `.venv` → 平台回退目录（Linux `.venv-linux` / Windows `.venv-windows`）→
  系统 `python3`/`py` 的顺序自动定位解释器。
- 跨平台中文字体发现：`videoforge/config.py` 的 `resolve_cjk_font()` 按发行版
  候选表探测，并用 `fc-match` 作兜底；支持 `CJK_FONT_REGULAR/BOLD` 覆盖。
- 平台自适应 TTS：Linux/macOS 默认 `auto`（edge-tts → 合成兜底），Windows 默认
  `sapi`；合成兜底音轨改用音频滤镜链，保证在无 SAPI 的 Linux 上也能通过 QA。
- 启动说明文档 `docs/STARTUP.md`，覆盖三种启动方式与常见问题。
- README 增加「快速开始（Linux / macOS）」章节；HANDOFF 增加 bash 等价命令。

### 变更
- 全部 `.sh`/`.ps1` 启动脚本改用共享辅助自动探测 venv，不再写死
  `.venv/bin/python` / `.venv\Scripts\python.exe`。
- `setup.sh`/`setup.ps1` 增加鲁棒性：当 `.venv` 是异平台 venv 时自动改建
  `.venv-linux` / `.venv-windows`。
- `requirements.txt`：`pyttsx3` / `pywin32` 加 `sys_platform == "win32"` 环境标记，
  Linux/macOS 自动跳过；补充三平台 FFmpeg/字体系统依赖说明。
- libass 字幕路径转义按平台区分：仅 Windows 盘符冒号需转义。

### 修复
- Linux 上运行 `.sh` 脚本报 `.venv/bin/python: No such file or directory`
  （根因：仓库里的 `.venv` 是 Windows 布局，真正的 Linux venv 在 `.venv-linux`）。
- 无 SAPI 的 Linux 上 TTS 降级链因误用视频 overlay 滤镜而崩溃（改为 adelay/amix
  音频滤镜）；并修复兜底音轨平均响度过低导致 QA 永不通过的问题。

### 安全
- `.gitignore` 明确忽略 `.venv/`、`.venv-linux/`、`.venv-windows/`，防止不可跨平台
  移植的虚拟环境被提交。

### 验证
- Linux 实测：`scripts/tests.sh` → 31 passed；`scripts/demo.sh` 跑通完整流水线，
  产出有效 `final_video.mp4`（H.264/AAC，1920x1080，30fps，约 318s），QA 零高优先级问题。

---

## [1.0.0] - 2026-10-12

Windows 原始实现基线。

### 新增
- 完整 10 Agent DAG：发现 → 并行研究 → 事实核验 → 评分排名 → 中文编剧 → 分镜
  → Pillow 信息卡 → SAPI 中文旁白 → SRT 字幕 → FFmpeg 分段/拼接 → ffprobe 质检
  → 最多两轮定向返工。
- 火山方舟文本 provider（OpenAI 兼容协议）；GitHub REST 取数。
- SQLite 状态机、预算/幂等、脱敏审计日志、FastAPI 本地任务 API。
- 技术说明书 `docs/TECHNICAL_MANUAL.md` 与自动化测试套件。

[未发布]: https://example.invalid/compare/v1.3.0...HEAD
[1.3.0]: https://example.invalid/compare/v1.2.0...v1.3.0
[1.2.0]: https://example.invalid/compare/v1.1.0...v1.2.0
[1.1.0]: https://example.invalid/compare/v1.0.0...v1.1.0
[1.0.0]: https://example.invalid/releases/tag/v1.0.0
