# 组件选型与实测清单

核实日期：2026-10-12（Windows 10 19045，Python 3.14.4，Node v24.14.1）。
版本均为本机实际安装版本；“接入状态”描述本项目代码真实做到的程度。

| 组件 | 版本 | 许可证 | 项目职责 | 接入状态 |
|---|---|---|---|---|
| Python | 3.14.4 | PSF | 业务主语言（虚拟环境 `.venv`） | ✅ 全部业务代码 |
| FFmpeg / ffprobe | 8.1 full_build（gyan.dev） | LGPL/GPL 视构建选项 | 分段、concat、编码、响度/轨道检查 | ✅ subprocess 参数数组真实调用 |
| Pydantic | 2.14.1 | MIT | 全部 Agent I/O 契约与状态枚举 | ✅ |
| httpx | 0.28.1 | BSD-3-Clause | 方舟/GitHub HTTP 客户端（MockTransport 测试） | ✅ |
| Tenacity | 见 requirements.txt | Apache-2.0 | 仅对 transient（429/5xx/网络）指数退避 | ✅ |
| Pillow | 12.3.0 | HPND（类 MIT） | 5 类信息卡、封面、字幕烧录 | ✅ |
| pytest | 9.1.1 | MIT | 21 个测试（含 FFmpeg/SAPI/端到端 smoke） | ✅ |
| pyttsx3 + SAPI5 | 2.99（系统语音 Huihui） | BSD-3-Clause；语音属系统组件 | 离线中文旁白（真实发音人，origin=real） | ✅ |
| edge-tts | 7.2.8 | GPL-3.0（注意许可证） | 在线神经 TTS（本机被微软 403，默认不启用） | ⚠️ 可选，失败自动降级 |
| FastAPI | 0.143.0 | MIT | 本地任务 API（/jobs、/health、/artifacts） | ✅ |
| Uvicorn | 0.54.0 | BSD-3-Clause | ASGI 运行时 | ✅ |
| 火山方舟 | Coding Plan `/api/plan/v3`，模型 `ark-code-latest` | 商业服务 | 研究/核验/点评/编剧文本 | ✅ 实测返回中文与 usage |
| GitHub REST API | v2022-11-28 | 服务条款 | 搜索/仓库元数据/README | ✅ Token 用户 guosheng1530 |
| OpenClaw | 2026.4.11 (c836fd2) | 开源（见其仓库） | 入口/通知 | ⚠️ 已安装；健康探测真实，通知默认关 |
| Ruflo | npm 3.56.7（未安装） | MIT | Agent swarm（候选） | ⚠️ npm 包实测归属 ruvnet/claude-flow，拒绝猜测式接入 |
| 中文字体 | msyh.ttc / msyhbd.ttc（雅黑） | 微软字体许可（随 Windows） | 信息卡与烧录字幕 | ✅ 仅本机渲染，不随项目分发 |
| SQLite | 3.x（标准库 sqlite3） | Public Domain | 任务/事件/调用/产物/QA 六张表 | ✅ |

## 许可证注意事项

- **edge-tts 为 GPL-3.0**：作为独立 CLI/库通过进程/标准接口调用时影响较小，
  但若你计划分发合并后的作品，需自行评估合规；默认引擎是系统 SAPI5，不依赖它。
- **FFmpeg full_build**：gyan.dev full 构建包含 GPL 组件（如 x264）。本项目在本机
  调用其可执行文件、不随仓库分发二进制；若未来分发软件，需按 LGPL/GPL 履行义务。
- **微软雅黑字体**不随项目打包，程序只引用用户 Windows 系统自带字体。
- 开源项目的 README、模型权重、素材不等于可任意商用；视频文案只引用事实信息。
- 每个 GitHub 依赖都应像本表一样记录“仓库/版本/许可证/核实日期”。

## 同名包风险实录（蓝图预警成真）

- 蓝图写的 Ruflo 仓库是 `github.com/ruvnet/ruflo`；
- `npm view ruflo repository.url` 实测返回 `git+https://github.com/ruvnet/claude-flow.git`。
- 因此安装前必须核实包归属；本项目默认不安装，集成代码只做探测与文档化。
