# 启动说明（Linux / macOS / Windows）

本文件集中说明 **AgentVideoForge** 的几种启动方式。三种方式最终都调用同一个 CLI
入口 `videoforge/cli.py`，区别只在于「谁负责找到虚拟环境里的 Python、并切到项目
根目录」。

> 术语：**项目根目录** = 含有 `videoforge/` 包的那一层目录（本仓库根）。所有命令
> 都在项目根目录执行。

---

## 0. 先决条件

| 依赖 | Linux | macOS | Windows |
|---|---|---|---|
| Python 3.10+ | 发行版自带或 `apt install python3` | `brew install python` | [python.org](https://www.python.org/) 或 `winget install Python.Python.3.12` |
| FFmpeg（含 ffprobe） | `sudo apt install ffmpeg` | `brew install ffmpeg` | `winget install Gyan.FFmpeg` |
| 中文字体（信息卡/字幕用） | `sudo apt install fonts-noto-cjk` | 系统自带（苹方） | 系统自带（微软雅黑） |

此外需要项目根目录有一份填好的 `.env`（首次 `setup` 会从 `.env.example` 自动生成）：
- `demo` 子命令：**不需要** LLM key；
- `run` 子命令：需要 `LLM_API_KEY`（火山方舟文本），建议再配 `GITHUB_TOKEN`。

---

## 方式一：用启动脚本（推荐）

脚本会**自动探测**虚拟环境里的 Python 并切到项目根目录，无需手动激活。
查找顺序：`.venv`（当前平台原生布局）→ 平台回退目录（Linux `.venv-linux` /
Windows `.venv-windows`）→ 系统 `python3`/`py`。

### Linux / macOS

```bash
bash scripts/setup.sh        # 初始化：建 venv + 装依赖 + 生成 .env
bash scripts/check.sh        # 环境核查（发一次最小真实 LLM 请求；加 --no-ping 跳过）
bash scripts/demo.sh         # 零 LLM 费用出片
bash scripts/run.sh          # 正式出片（方舟 + GitHub，约 5 分钟）
bash scripts/run.sh --resume --job-id <ID>   # 从中断/既有任务恢复
bash scripts/tests.sh        # 运行全部测试
bash scripts/serve.sh        # 启动本地 API → http://127.0.0.1:8765/docs
```

赋予执行权限后也可直接 `./scripts/demo.sh`：

```bash
chmod +x scripts/*.sh
./scripts/demo.sh
```

### Windows（PowerShell）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # 初始化
scripts\check.ps1            # 环境核查（加 --no-ping 跳过联网请求）
scripts\demo.ps1             # 零 LLM 费用出片
scripts\run.ps1              # 正式出片（方舟 + GitHub）
scripts\run.ps1 --resume --job-id <ID>       # 从中断/既有任务恢复
scripts\tests.ps1            # 运行全部测试
scripts\serve.ps1            # 启动本地 API → http://127.0.0.1:8765/docs
```

---

## 方式二：激活虚拟环境后调模块

适合需要连续执行多条命令、或要用 `pip`、`pytest` 等其它工具时。

### 1) 激活

**Linux / macOS**
```bash
source .venv/bin/activate            # 若 .venv 不可用，用 source .venv-linux/bin/activate
```

**Windows（PowerShell）**
```powershell
.\.venv\Scripts\Activate.ps1
```

激活成功后提示符前会出现 `(.venv)`。

### 2) 调模块（两平台命令相同）

```bash
python -m videoforge.cli check                     # 环境与能力核查
python -m videoforge.cli check --no-ping           # 仅查本地环境，不发联网请求
python -m videoforge.cli demo                      # 零 LLM 费用出片
python -m videoforge.cli demo --resume --job-id <ID>
python -m videoforge.cli run                       # 正式出片
python -m videoforge.cli run --resume --job-id <ID>  # 从中断/既有任务恢复
python -m videoforge.cli jobs                      # 列出所有任务
python -m videoforge.cli serve                     # 启动本地 FastAPI
```

退出环境：`deactivate`。

---

## 方式三：不激活，直接指定 venv 的 Python

与方式二等价，省去激活/退出，适合一次性执行或写进别的脚本。

**Linux / macOS**
```bash
.venv/bin/python -m videoforge.cli demo
# 本机实际可用的解释器是 .venv-linux：
.venv-linux/bin/python -m videoforge.cli demo
```

**Windows（PowerShell）**
```powershell
.\.venv\Scripts\python.exe -m videoforge.cli demo
```

---

## CLI 子命令速查

| 子命令 | 作用 | 可选参数 |
|---|---|---|
| `check` | 环境与能力核查（含一次最小真实 LLM 调用） | `--no-ping`（跳过联网请求） |
| `demo` | 零 LLM 费用闭环（真实 GitHub 数据 + 旁白 + FFmpeg） | `--resume`、`--job-id <ID>` |
| `run` | 完整真实流水线（方舟文本 + GitHub） | `--resume`、`--job-id <ID>` |
| `serve` | 启动本地 FastAPI（默认 `127.0.0.1:8765`，文档 `/docs`） | — |
| `jobs` | 列出 SQLite 里的所有任务 | — |

查看帮助：
```bash
python -m videoforge.cli -h              # 总帮助
python -m videoforge.cli run -h          # 某个子命令的参数
```

---

## 常见问题

- **`No such file or directory: .venv/bin/python`（Linux）**：说明 `.venv` 是从
  Windows 拷来的（只有 `Scripts/`）。启动脚本已能自动回退到 `.venv-linux`；若手动
  调模块，请改用 `.venv-linux/bin/python`，或重新运行 `bash scripts/setup.sh`。
- **`No module named videoforge`**：没有在项目根目录执行。先 `cd` 到含 `videoforge/`
  的目录再运行 `-m videoforge.cli`。
- **信息卡/字幕显示成方块**：缺中文字体。Linux 装 `fonts-noto-cjk`，或用环境变量
  `CJK_FONT_REGULAR` 指向一个中文字体文件。
- **`run` 报缺少 LLM_API_KEY**：`run` 需要火山方舟文本 key；只想免费体验用 `demo`。
- **换了机器/操作系统后脚本报错**：虚拟环境不可跨平台移植，重新运行对应的
  `setup` 脚本重建即可（venv 不会被提交，见 `.gitignore`）。

---

## 产物位置

每次出片在 `output/<job_id>/` 下，关键文件：`final_video.mp4`、`thumbnail.png`、
`subtitles.srt`、`script.md`、`quality_report.md/json`、`run_manifest.json`
（逐素材标注 real/template/synthetic 来源）。
