# 实施计划（IMPLEMENTATION_PLAN）

> 本文件由第一阶段「环境与事实核实」产出，随后持续更新。所有外部能力均经真实请求核实，未验证的能力一律标注。

## 1. 环境核实结果（2026-10-12，本机 Windows 10）

| 项目 | 实测结果 | 结论 |
|---|---|---|
| Python | 3.14.4（另有 3.10） | 用 3.14 建独立虚拟环境 `.venv` |
| Node.js / npm | v24.14.1 / 11.11.0 | OpenClaw 运行所需 |
| FFmpeg / ffprobe | 8.1 full_build（gyan.dev），libx264/libass 等齐全 | 视频合成与检查可用 |
| Git | 2.53 | 可用 |
| OpenClaw | 2026.4.11 (c836fd2)，命令含 `gateway/agent/health/message/capability/models` | 已安装；网关/渠道需配置后才能投递通知 |
| Ruflo | 本机未安装；npm `ruflo@3.56.7` 的 repository 指向 `ruvnet/claude-flow`（MIT） | 与蓝图 URL `ruvnet/ruflo` 不一致，按同名包风险处理，默认不安装 |
| 火山方舟文本 | `POST {LLM_BASE_URL}/chat/completions`，模型 `ark-code-latest`，真实返回中文与 usage | ✅ 已验证 |
| 火山方舟标准端点 | `GET https://ark.cn-beijing.volces.com/api/v3/models` → 401 AuthenticationError | 此 Key 隶属 Coding Plan（`/api/plan/v3`），无标准方舟 Key 权限；图片/视频/TTS 不可用 |
| GitHub Token | 用户 `guosheng1530`；search 30/min、core 5000/h | ✅ 已验证 |
| edge-tts 7.2.8 | wss 握手 403（代理出口被微软风控） | 作为可选；默认不依赖 |
| pyttsx3 + SAPI5 | `Microsoft Huihui Desktop (zh-CN)` 合成 WAV 实测成功（5.5s） | ✅ 真实离线中文旁白 |
| 中文字体 | `C:/Windows/Fonts/msyh.ttc`、`simhei.ttf` | Pillow 画面可用 |
| 网络代理 | 系统代理 127.0.0.1:7890（用户可控翻墙） | httpx 透明生效 |

## 2. 能力矩阵与诚实标注原则

- 文本（研究/核验/编剧/解说）：**真实方舟 LLM**。
- 项目元数据/README：**真实 GitHub REST API**。
- 旁白：**真实语音**（SAPI 离线 Huihui；edge-tts 可选）。
- 画面：Pillow/SVG 风格程序化信息卡（origin=`template`，卡片页脚注明），不调用任何图片生成 API。
- 方舟图片/视频/TTS：Provider 代码保留接口，调用即抛 `CapabilityUnavailable`（origin 绝不伪装成 real）。
- 最终 `run_manifest.json` 与 `quality_report` 逐素材列出 `real/template/synthetic`。

## 3. 落地结构

```
videoforge/                # 主包（生产工具 + 学习样本）
  config.py                # .env 读取、路径、能力开关
  logging_utils.py         # 结构化日志 + 密钥脱敏
  schemas.py               # 全部 Pydantic 契约
  budget.py                # 调用计数/用量/软预算硬预算
  db.py                    # SQLite：6 张表 + user_version 迁移
  providers/               # ark_text / github / tts / ark_media(未开通)
  agents/                  # 10 个 Agent：base + prompts + 各角色
  media/                   # cards(Pillow) / subtitles(SRT) / ffmpeg_tools
  integrations/            # openclaw_adapter / ruflo_adapter（真实探测，不假装）
  workflow.py              # DAG 状态机、并行研究、检查点、QA 两轮返工
  api.py                   # 可选 FastAPI（127.0.0.1 + token）
  cli.py                   # check / demo / run / serve
tests/                     # pytest：契约/状态机/预算/脱敏/回退/FFmpeg smoke/端到端
scripts/*.ps1              # Windows 入口：setup/check/demo/run/tests/serve
output/<job_id>/           # 每个任务的全部产物
docs/                      # 技术说明书（随实现同步扩写）
```

## 4. 实施顺序与验收

1. 地基：config/log/schemas/budget/db + 测试 ✅
2. Provider：方舟文本（含 JSON 修复/重试/用量）、GitHub、TTS 链
3. 10 Agent + DAG 工作流 + SQLite 状态机 + QA 返工
4. Pillow 信息卡 → SAPI 旁白 → SRT → FFmpeg 分段/concat → ffprobe 质检
5. `demo`（样例数据、零 API 费用）先闭环出 MP4
6. `run` 用真实 GitHub + 方舟生成正式 5 分钟中文 MP4
7. 测试全部跑通；OpenClaw/Ruflo 适配如实报告
8. 技术说明书、README、组件清单、验收记录
