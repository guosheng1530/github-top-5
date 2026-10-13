# 夜间交付说明（明早验收从这里开始）

> 生成时间：2026-10-13 凌晨。任务：按蓝图无人值守落地“生产工具 + 学习项目”。

## 一、先看什么（5 分钟验收路径）

1. **正式成片**：`output/<REAL_JOB_ID>/final_video.mp4`（1080p，方舟研究+编剧，真实 GitHub 数据）
2. **零费用 demo 成片**：`output/20261013-090037-f0a518/final_video.mp4`（286 秒，QA 全过）
3. **质检报告**：对应任务目录的 `quality_report.md`（ffprobe 实测：编码/分辨率/帧率/响度/SRT）
4. **素材溯源**：`run_manifest.json` —— 每条素材标 `real/template/synthetic`
5. **教材**：[docs/TECHNICAL_MANUAL.md](docs/TECHNICAL_MANUAL.md)（18 章，含练习与答案预期）

任务列表随时可查：`.venv/Scripts/python -m videoforge.cli jobs`

## 二、这次真正做到了什么

- 完整 10 Agent DAG：发现→并行研究→事实核验门禁→程序评分排名→中文编剧→分镜
  →Pillow 信息卡→SAPI 中文旁白→SRT→FFmpeg 分段/concat→ffprobe 质检→最多两轮定向返工。
- 火山方舟文本（`/api/plan/v3`，`ark-code-latest`）真实接通并用于研究/核验/点评/编剧。
- GitHub REST API 真实取数（搜索+逐条复核+README）。
- 旁白是 Windows SAPI5「Huihui」**真实离线语音**（非假音轨）。
- 21 个自动化测试全部通过（含真实 FFmpeg/SAPI/端到端）。
- FastAPI 本地任务 API、PowerShell 入口、`.env`/`.gitignore`、预算/脱敏/注入防护齐备。

## 三、诚实标注：哪些没做以及为什么

- **方舟图片/视频/TTS 未接通**：本 Key 属 Coding Plan，标准 `/api/v3` 返回 401。
  代码保留适配器，调用即 `CapabilityUnavailable`，画面为程序化信息卡（已在视频与 manifest 标明）。
- **OpenClaw**：已装 2026.4.11，探测/健康检查真实可用；网关当前未启动，完成通知默认关闭
  （`OPENCLAW_NOTIFY=1` 且网关在线才发送）。
- **Ruflo**：未安装；npm 同名包实测归属 `ruvnet/claude-flow`，适配器拒绝猜测式调用。
- **edge-tts**：本机代理出口被微软 403，作为可选项保留，默认 SAPI。
- 成本估算默认 0（Coding Plan 为套餐制），真实 token 用量在 `api_calls` 表/manifest 可查。

## 四、常用命令

```powershell
scripts\check.ps1                 # 环境核查 + 方舟最小真实请求
scripts\demo.ps1                  # 零 LLM 费用出片
scripts\run.ps1                   # 正式出片（方舟 + GitHub）
scripts\run.ps1 --resume --job-id <ID>   # 从中断/既有任务恢复，不重复花 LLM 费用
scripts\tests.ps1                 # 21 个测试
scripts\serve.ps1                 # http://127.0.0.1:8765/docs
```

## 五、下一步建议（按优先级）

1. 若需要 AI 生成画面/云端神经配音：在方舟控制台确认开通对应模型，把模型 ID 填入
   `.env` 的 `ARK_IMAGE_MODEL/ARK_VIDEO_MODEL/ARK_TTS_MODEL`，再实现 `providers/ark_media.py`
   的三个方法（签名与 job_id 持久化已预留），Agent 层无需改动。
2. 想让 OpenClaw 真正当入口：`openclaw gateway` 启动网关并 `openclaw configure` 配好模型。
3. 学习入口：技术说明书第 17 章的 4 周练习路线。
4. 安全：聊天中出现过的 Key/Token 建议在控制台轮换（新值只放 `.env`）。
