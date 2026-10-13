# 开始使用

1. 解压此 ZIP，在 Claude Code 中打开该目录。
2. 先发送 `prompts/MASTER_PROMPT.md` 的完整内容，让 Claude Code 在当前目录直接实现代码。
3. 如果需要分阶段细化，再发送 `prompts/01_architecture_and_docs.md` 到 `06_tests_security_learning.md`。
4. 将火山方舟 Key 只放在本机 `.env` 或环境变量中；不要粘贴到聊天，也不要提交 Git。
5. 要求 Claude Code 先完成 demo 闭环（模板画面 + FFmpeg + 测试），再逐一启用已开通的火山方舟模型。
6. 让它每次改动后更新 `docs/TECHNICAL_MANUAL.md`，并运行测试。

## 说明
这是一套实现蓝图和技术教材模板，不是已经运行完成的软件。真实的 Ruflo/OpenClaw/火山方舟媒体接口必须按当前环境核实。README 与技术说明书应记录哪些功能真实验证过，哪些尚未配置。
