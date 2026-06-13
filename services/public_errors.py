from __future__ import annotations

from typing import Any

INTERFACE_BUSY_MESSAGE = "接口繁忙，请稍后重试"
RESOURCE_BUSY_MESSAGE = "当前生成资源繁忙，请稍后重试"
CONTENT_POLICY_MESSAGE = "提示词可能不符合规则，请调整后重试"
IMAGE_QUOTA_MESSAGE = "额度不足，请兑换后继续使用"


def _lower(value: object) -> str:
    return str(value or "").strip().lower()


def should_sanitize_identity(identity: dict[str, object] | None) -> bool:
    return str((identity or {}).get("role") or "").strip().lower() != "admin"


def error_text_from_detail(detail: object) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        for key in ("error", "message", "detail"):
            value = detail.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                nested = error_text_from_detail(value)
                if nested:
                    return nested
    return str(detail or "")


def public_error_message(message: object) -> str:
    text = str(message or "").strip()
    lower = _lower(text)
    if not text:
        return "请求失败，请稍后重试"

    if "请先兑换额度后使用" in text:
        return text
    if "当前用户权限" in text or "密钥无效" in text or "重新登录" in text:
        return text
    if "额度不足" in text or "insufficient_quota" in lower:
        return IMAGE_QUOTA_MESSAGE
    if "prompt is required" in lower:
        return "请输入提示词"
    if "image file is required" in lower or "image is required" in lower:
        return "请上传参考图后重试"
    if "image file is empty" in lower:
        return "参考图读取失败，请重新上传"

    if any(
        marker in lower
        for marker in (
            "content_policy",
            "content policy",
            "policy violation",
            "safety",
            "blocked",
            "rejected",
            "sensitive",
            "ai 审核未通过",
            "检测到敏感词",
        )
    ):
        return CONTENT_POLICY_MESSAGE

    if any(
        marker in lower
        for marker in (
            "no available image quota",
            "no available codex image quota",
            "free plan limit",
            "usage_limit_reached",
            "rate_limit_exceeded",
            "too many requests",
            "账号生图额度已用完",
            "限流",
        )
    ):
        return RESOURCE_BUSY_MESSAGE

    if any(
        marker in lower
        for marker in (
            "高清中转接口调用失败",
            "中转接口调用失败",
            "duck:",
            "und_err_socket",
            "econnreset",
            "socket hang up",
            "socketerror",
            "remote disconnected",
            "remotedisconnected",
            "connection closed",
            "connection aborted",
            "connection reset",
            "fetch failed",
            "failed to fetch",
            "network error",
            "curl:",
            "timeout",
            "timed out",
            "status_code=500",
            "http 500",
            "traceid:",
            "request id:",
            "upstream image connection failed",
            "failed to perform",
        )
    ):
        return INTERFACE_BUSY_MESSAGE

    return text


def public_error_detail(detail: object) -> dict[str, str]:
    return {"error": public_error_message(error_text_from_detail(detail))}
