# Claude Code 主提示词：按开源优先原则实现系统，并写出完整技术教材

你是高级 Agent 系统架构师、Python 工程师、视频自动化工程师和技术文档作者。请在当前目录**直接创建并实现可运行的项目**，不要只回复方案。先阅读：
- `docs/TECHNICAL_MANUAL.md`
- `docs/COMPONENTS.md`
- `docs/architecture.mmd`

## 用户的硬性要求
1. 商业 AI 模型 API 优先只使用用户已有的火山方舟；只有当某个媒体能力未开通且用户明确同意时，才提出额外商业 API。
2. 除火山方舟外，尽可能选择 GitHub 上成熟的开源组件。
3. 项目最终要自动生成可播放的中文 MP4，不是只生成脚本或图片。
4. 必须交付一套真正详细的中文技术说明书。读者希望通过说明书学会全部技术细节，因此每个组件不止写“是什么”，还要说明为什么选、原理、在本项目里的数据流、核心配置、常用命令、故障排查、关键术语和学习练习。
5. 项目是 Windows 优先；用户设备显卡约 4GB VRAM，不要要求在本地运行大型视频扩散模型。
6. 不要声称未经验证的 OpenClaw、Ruflo、火山方舟图片/视频/TTS API 已接通。

## 第一阶段：环境与事实核实
- 检查当前目录，保留用户已有文件。
- 检查 Windows/PowerShell、Python、Node/npm/npx、FFmpeg/ffprobe、OpenClaw、Ruflo 版本。
- 每个命令先查 `--help`，每个外部接口优先读当前官方文档。
- 核对 Ruflo 的仓库 owner、真实包名、版本、许可证；避免误装同名包。
- 核实火山方舟文本、图片、视频、TTS 各能力的实际模型 ID/Endpoint、接口、权限、地域、异步任务方式和计费单位。
- 写 `IMPLEMENTATION_PLAN.md`，随后继续实施，不要停在计划阶段。

## 开源优先组件
按实际兼容性采用并锁定依赖：
- Python：业务实现；
- OpenClaw：自然语言入口与通知；
- Ruflo：Agent harness/swarm 协作；
- FastAPI：可选的本地任务 API；
- Pydantic：结构化数据与校验；
- SQLite：任务状态、事件、产物索引；
- HTTPX：HTTP API 客户端；
- FFmpeg/ffprobe：视频合成与检查；
- Pillow：封面、信息卡、缩略图；
- pytest：自动化测试；
- Tenacity：可选网络重试，但不能替代媒体 API 幂等逻辑；
- GitHub REST API：仓库元数据。
不要默认再引入 LangGraph 当第三个主编排器；如果你认为 Ruflo 无法承担预期职责，先写出技术决策记录说明原因和替代方案，不要静默叠加两套 orchestration。
组件清单和许可证记录到 `docs/COMPONENTS.md`，锁定版本并说明许可证。FFmpeg 的实际构建选项与许可证要检查。

## 架构要求
实现 10 个专业 Agent：趋势发现、项目研究、事实核验、排名、中文编剧、分镜、视觉素材、配音字幕、视频制作、质量审核。每个 Agent 有：
- 独立 system prompt；
- Pydantic 输入/输出 schema；
- 工具白名单；
- 超时、错误分类和失败策略；
- 结构化日志。
研究可并行；事实核验必须先于排名与编剧；图片/配音可在分镜冻结后并行；渲染等待素材就绪；QA 失败触发定向返工，最多两轮。

工作流控制器负责视频业务 DAG、预算、重试、恢复和最终任务状态；Ruflo 负责其实际支持的 Agent 协作。SQLite 是业务最终状态的唯一权威来源，避免双重状态。

## 火山方舟 Provider
实现可替换的 Provider Adapter：
- 文本：按已核实的官方接口实现。
- 图像/视频/TTS：只有官方文档与用户账号权限都确认后才能实现真实调用。
- 媒体异步任务必须持久化 job ID，支持轮询、下载、超时、取消、恢复和防重复扣费。
- 通过 `.env` 读取密钥与模型配置；提供 `.env.example`，将 `.env` 放进 `.gitignore`。
- 绝不打印 Key、Authorization、Token。
- 未开通时返回清楚的 `CapabilityUnavailable`，用 Pillow/SVG 模板画面和可识别的 demo 音轨完成端到端测试；报告中明确标出哪些素材是模板或模拟的。
- 实现预算上限、调用计数、可获得的 token/用量、估算成本，并明确估算不等于真实账单。

## 视频输出
默认中文普通话、16:9、1080p（允许 720p 配置）、30fps、约 5 分钟。技术信息优先用真实项目数据、官方截图/链接、Pillow 信息卡、SVG/图表、字幕和转场；只为必要镜头调用视频生成 API。输出：
- `final_video.mp4`
- `thumbnail.png`
- `subtitles.srt`
- `script.md`
- `top5_projects.json`
- `storyboard.json`
- `quality_report.md/json`
- `run_manifest.json`
- `research/`、`assets/`、脱敏日志
使用 FFmpeg/ffprobe 检查轨道、时长、分辨率、帧率、音频存在性和字幕时间轴。Windows 下通过 subprocess 参数数组调用 FFmpeg，禁止 shell 字符串拼接。

## OpenClaw / Ruflo 集成
必须基于真实安装版本和文档实现 Adapter，不得猜命令、MCP 工具名、配置字段或 HTTP 路径。OpenClaw 至少能创建任务、查询状态、获取产物路径；Ruflo 必须真实触发/管理其支持的 Agent 执行。若本机没有安装或无法验证，核心系统仍需在独立模式运行，README 必须如实标记接入状态与后续步骤。

## 完整中文技术说明书：必须写，不可省略
完善 `docs/TECHNICAL_MANUAL.md`，至少包含：
1. 全局架构图、组件关系、每条数据流；
2. 每个组件的定位、选择理由、内部原理、输入输出、关键配置、依赖和许可证；
3. Agent/harness/model/tool/workflow/state machine/API adapter/JSON schema/idempotency/checkpoint 等概念的教学解释；
4. 10 个 Agent 的职责边界、提示词、schema、工具权限、交接数据和失败场景；
5. SQLite 表结构和状态迁移说明；
6. 火山方舟 API 请求链路、同步/异步调用、错误码、限流、预算和重试；
7. FFmpeg 合成流程、编码/容器、视频/音频轨道、字幕同步和 ffprobe 检查；
8. OpenClaw 与 Ruflo 的真实集成方式与安全边界；
9. Windows 安装、配置、运行、测试、更新和卸载步骤；
10. 至少 10 个常见故障的定位流程；
11. 安全、许可证、提示注入、密钥管理、媒体版权；
12. 术语表、循序渐进的学习路线、每章练习题及预期结果；
13. 技术决策记录：为什么选这些组件，哪些组件是可选，何时应替换。
写给希望从入门理解到能维护系统的读者，解释“为什么”和“如何验证”，不要只堆术语。

## 测试与交付
- 编写单元测试、API mock 测试、工作流状态迁移测试、媒体回退测试、FFmpeg smoke test。
- 运行测试与静态检查并修复错误；报告真实执行结果，不要虚构。
- 提供 PowerShell 入口：安装依赖、检查配置、跑 demo、真实生成、运行测试。
- 最后总结项目树、组件和许可证、测试结果、哪些 API 真正验证成功、哪些媒体能力未配置、如何生成第一条视频，以及技术说明书学习顺序。
- 不要在最终回复只贴代码片段；直接在当前工作目录写出项目文件。
现在开始实施。
