"""外部能力适配器（Provider Adapter）。

设计意图见技术说明书「5. API Provider 设计」：Agent 只依赖稳定接口，
不知道某家厂商的 HTTP 细节。将来账号开通了方舟图片/视频/TTS，
只需在对应适配器里补真实实现，10 个 Agent 一行都不用改。
"""
