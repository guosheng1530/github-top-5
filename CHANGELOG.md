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

[未发布]: https://example.invalid/compare/v1.1.0...HEAD
[1.1.0]: https://example.invalid/compare/v1.0.0...v1.1.0
[1.0.0]: https://example.invalid/releases/tag/v1.0.0
