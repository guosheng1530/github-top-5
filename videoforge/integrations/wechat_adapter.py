"""企业微信群机器人通知适配器。

为什么选「群机器人 Webhook」而不是公众号/应用消息？
----------------------------------------------------
* 零认证门槛：企业微信群 → 添加群机器人 → 复制 Webhook URL 即可，无需
  走公众号认证或配置 agentid/secret 的 OAuth 流程；
* 不经第三方：消息直达企业微信官方端点，不像 Server酱/PushPlus 需过中转服务器；
* 协议极简：对 Webhook URL 发一个 JSON POST（text/markdown），同步返回
  ``{"errcode":0}`` 即成功。

与 OpenClaw 适配器一致的边界约定
--------------------------------
* **核心视频流水线不依赖本模块**；
* 默认关闭，必须显式 opt-in（``WECHAT_NOTIFY=1`` 且配置了 Webhook URL）；
* 未配置/发送失败都如实返回状态，绝不"假装已通知"；
* 不做 shell 拼接，纯 HTTP（httpx），URL 作为密钥由日志层脱敏。

官方协议参考（企业微信群机器人）：
  POST <webhook_url>
  Content-Type: application/json
  body: {"msgtype":"text","text":{"content":"..."}}
  成功响应：{"errcode":0,"errmsg":"ok"}
"""

from __future__ import annotations

import httpx

from videoforge.logging_utils import get_logger

logger = get_logger("videoforge.wechat")


class WeChatAdapter:
    """企业微信群机器人通知。

    :param webhook_url: 群机器人 Webhook 完整地址（含 ``?key=...``）；
    :param notify_enabled: 显式开关，默认 False（不发送）；
    :param timeout: HTTP 超时（秒）。
    """

    def __init__(self, webhook_url: str = "", *, notify_enabled: bool = False,
                 timeout: float = 15.0):
        self.webhook_url = (webhook_url or "").strip()
        self.notify_enabled = notify_enabled
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        """是否已配置可用的 Webhook（基础格式校验，不发网络请求）。"""
        return self.webhook_url.startswith("https://qyapi.weixin.qq.com/")

    def _post(self, payload: dict) -> dict:
        """向 Webhook 发送一条消息，返回 ``{"sent": bool, "detail": str}``。"""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            # 不把 webhook_url（含 key）写进日志/返回，避免密钥泄露
            return {"sent": False, "detail": f"HTTP 失败: {type(exc).__name__}: {exc}"[:300]}
        except ValueError:  # 非 JSON 响应
            return {"sent": False, "detail": f"响应非 JSON: {resp.text[:200]}"}
        errcode = data.get("errcode")
        if errcode == 0:
            return {"sent": True, "detail": "ok"}
        return {"sent": False,
                "detail": f"企业微信返回 errcode={errcode}, errmsg={data.get('errmsg')}"[:300]}

    def notify_completion(self, job_id: str, video_path: str, passed: bool,
                          *, duration_sec: float | None = None) -> dict:
        """任务完成后推送一条文本通知。

        与 :meth:`OpenClawAdapter.notify_completion` 对齐的返回语义：
        未开启/未配置时返回 ``{"sent": False, "reason": ...}``，不抛异常。
        """
        if not self.notify_enabled:
            return {"sent": False,
                    "reason": "未设置 WECHAT_NOTIFY=1，默认不发送企业微信通知"}
        if not self.configured:
            return {"sent": False,
                    "reason": "WECHAT_WEBHOOK_URL 未配置或不是合法的企业微信 Webhook"}
        dur = f"，时长约 {duration_sec:.0f} 秒" if duration_sec else ""
        content = (f"[AgentVideoForge] 任务 {job_id} 已完成\n"
                   f"质检：{'✅ 通过' if passed else '❌ 有未决问题'}{dur}\n"
                   f"成片：{video_path}")
        result = self._post({"msgtype": "text", "text": {"content": content}})
        logger.info("企业微信通知结果：sent=%s", result.get("sent"))
        return result

    def send_text(self, text: str) -> dict:
        """发送任意文本（便于在流水线其它阶段复用，如失败告警）。"""
        if not self.notify_enabled:
            return {"sent": False, "reason": "未设置 WECHAT_NOTIFY=1"}
        if not self.configured:
            return {"sent": False, "reason": "WECHAT_WEBHOOK_URL 未配置"}
        return self._post({"msgtype": "text", "text": {"content": text}})
