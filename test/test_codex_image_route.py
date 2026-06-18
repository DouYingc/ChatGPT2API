from __future__ import annotations

import base64
import unittest
from io import BytesIO
from unittest import mock

from PIL import Image

from services.protocol import conversation
from services.protocol.conversation import ConversationRequest, collect_image_outputs, stream_image_outputs_with_pool
from utils.helper import UpstreamHTTPError


def tiny_png_b64() -> str:
    buffer = BytesIO()
    Image.new("RGB", (16, 9), "white").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class FakeImageAccountMixin:
    def _is_rate_limit_error(self, exc):
        text = str(exc).lower()
        return "status=429" in text or "rate_limit" in text

    def _is_free_plan_image_limit_text(self, text):
        return False


class CodexImageRouteTests(unittest.TestCase):
    def test_high_resolution_uses_codex_responses_size(self):
        calls = []

        class FakeAccountService(FakeImageAccountMixin):
            def get_available_access_token(self, **kwargs):
                calls.append(("token", kwargs))
                return "codex-token"

            def get_account(self, token):
                return {
                    "access_token": token,
                    "type": "Plus",
                    "status": "正常",
                    "source_type": "codex",
                    "quota": 1,
                    "image_quota_unknown": True,
                }

            def refresh_oauth_access_token(self, token):
                calls.append(("refresh", {"token": token}))
                return ""

            def mark_image_result(self, token, success):
                calls.append(("mark", {"token": token, "success": success}))

        class FakeBackend:
            def __init__(self, access_token):
                self.access_token = access_token

            def generate_codex_image(self, **kwargs):
                calls.append(("generate", kwargs))
                return [{"type": "image_generation_call", "result": tiny_png_b64()}]

        with (
            mock.patch.object(conversation, "account_service", FakeAccountService()),
            mock.patch.object(conversation, "OpenAIBackendAPI", FakeBackend),
            mock.patch.object(conversation.config, "image_route_for_resolution", lambda _resolution: "pool"),
        ):
            result = collect_image_outputs(stream_image_outputs_with_pool(
                ConversationRequest(
                    model="gpt-image-2",
                    prompt="cat",
                    resolution="4k",
                    size="16:9",
                    response_format="b64_json",
                )
            ))

        generate_call = next(payload for kind, payload in calls if kind == "generate")
        self.assertEqual(generate_call["image_size"], "3840x2160")
        self.assertEqual(generate_call["model"], "gpt-image-2")
        self.assertEqual(result["data"][0]["b64_json"], tiny_png_b64())
        self.assertIn(("mark", {"token": "codex-token", "success": True}), calls)

    def test_high_resolution_codex_failure_does_not_fallback_to_picture_v2(self):
        calls = []

        class FakeAccountService(FakeImageAccountMixin):
            def get_available_access_token(self, **kwargs):
                calls.append(("token", kwargs))
                return "codex-token"

            def get_account(self, token):
                return {
                    "access_token": token,
                    "type": "Plus",
                    "status": "正常",
                    "source_type": "codex",
                    "quota": 1,
                    "image_quota_unknown": True,
                }

            def refresh_oauth_access_token(self, token):
                return ""

            def mark_image_result(self, token, success):
                calls.append(("mark", {"token": token, "success": success}))

        class FakeBackend:
            def __init__(self, access_token):
                self.access_token = access_token

            def generate_codex_image(self, **kwargs):
                calls.append(("generate", kwargs))
                raise RuntimeError("codex upstream rejected size")

        with (
            mock.patch.object(conversation, "account_service", FakeAccountService()),
            mock.patch.object(conversation, "OpenAIBackendAPI", FakeBackend),
            mock.patch.object(conversation.config, "image_route_for_resolution", lambda _resolution: "pool"),
        ):
            with self.assertRaises(conversation.ImageGenerationError) as context:
                collect_image_outputs(stream_image_outputs_with_pool(
                    ConversationRequest(
                        model="gpt-image-2",
                        prompt="cat",
                        resolution="4k",
                        size="9:16",
                        response_format="b64_json",
                    )
                ))

        self.assertIn("4K 高清生成失败", str(context.exception))
        generate_call = next(payload for kind, payload in calls if kind == "generate")
        self.assertEqual(generate_call["image_size"], "2160x3840")
        self.assertIn(("mark", {"token": "codex-token", "success": False}), calls)

    def test_high_resolution_429_marks_account_and_retries_next_codex_account(self):
        calls = []

        class FakeAccountService(FakeImageAccountMixin):
            def get_available_access_token(self, **kwargs):
                calls.append(("token", kwargs))
                excluded = kwargs.get("excluded_tokens") or set()
                if "codex-token-1" not in excluded:
                    return "codex-token-1"
                if "codex-token-2" not in excluded:
                    return "codex-token-2"
                raise RuntimeError("no available codex image quota")

            def get_account(self, token):
                return {
                    "access_token": token,
                    "type": "Plus",
                    "status": "正常",
                    "source_type": "codex",
                    "quota": 1,
                    "image_quota_unknown": True,
                }

            def refresh_oauth_access_token(self, token):
                return ""

            def mark_image_rate_limited(self, token, **kwargs):
                calls.append(("limited", {"token": token, "error": kwargs.get("error", "")}))

            def mark_image_result(self, token, success):
                calls.append(("mark", {"token": token, "success": success}))

        class FakeBackend:
            def __init__(self, access_token):
                self.access_token = access_token

            def generate_codex_image(self, **kwargs):
                calls.append(("generate", {"token": self.access_token, **kwargs}))
                if self.access_token == "codex-token-1":
                    raise UpstreamHTTPError(
                        "/backend-api/codex/responses",
                        429,
                        {"error": {"type": "rate_limit_exceeded"}},
                        {"x-codex-primary-used-percent": "100", "x-codex-primary-reset-after-seconds": "60", "x-codex-primary-window-minutes": "300"},
                    )
                return [{"type": "image_generation_call", "result": tiny_png_b64()}]

        with (
            mock.patch.object(conversation, "account_service", FakeAccountService()),
            mock.patch.object(conversation, "OpenAIBackendAPI", FakeBackend),
            mock.patch.object(conversation.config, "image_route_for_resolution", lambda _resolution: "pool"),
        ):
            result = collect_image_outputs(stream_image_outputs_with_pool(
                ConversationRequest(
                    model="gpt-image-2",
                    prompt="cat",
                    resolution="4k",
                    size="9:16",
                    response_format="b64_json",
                )
            ))

        generated_tokens = [payload["token"] for kind, payload in calls if kind == "generate"]
        self.assertEqual(generated_tokens, ["codex-token-1", "codex-token-2"])
        self.assertIn(("limited", {"token": "codex-token-1", "error": "/backend-api/codex/responses failed: status=429, body={'error': {'type': 'rate_limit_exceeded'}}"}), calls)
        self.assertIn(("mark", {"token": "codex-token-2", "success": True}), calls)
        self.assertEqual(result["data"][0]["b64_json"], tiny_png_b64())

    def test_non_stream_web_image_no_result_retries_next_account(self):
        calls = []

        class FakeAccountService(FakeImageAccountMixin):
            def get_available_access_token(self, **kwargs):
                calls.append(("token", kwargs))
                excluded = kwargs.get("excluded_tokens") or set()
                if "web-token-1" not in excluded:
                    return "web-token-1"
                if "web-token-2" not in excluded:
                    return "web-token-2"
                raise RuntimeError("no available image quota")

            def get_account(self, token):
                return {
                    "access_token": token,
                    "type": "free",
                    "status": "正常",
                    "source_type": "web",
                    "quota": 1,
                    "image_quota_unknown": False,
                }

            def mark_image_result(self, token, success):
                calls.append(("mark", {"token": token, "success": success}))

            def mark_image_rate_limited(self, token, **kwargs):
                calls.append(("limited", {"token": token}))

        class FakeBackend:
            def __init__(self, access_token):
                self.access_token = access_token

        def fake_stream_image_outputs(backend, request, index=1, total=1):
            calls.append(("stream", {"token": backend.access_token}))
            if backend.access_token == "web-token-1":
                yield conversation.ImageOutput(
                    kind="progress",
                    model=request.model,
                    index=index,
                    total=total,
                    text="waiting",
                )
                return
            yield conversation.ImageOutput(
                kind="result",
                model=request.model,
                index=index,
                total=total,
                data=[{"b64_json": tiny_png_b64()}],
            )

        with (
            mock.patch.object(conversation, "account_service", FakeAccountService()),
            mock.patch.object(conversation, "OpenAIBackendAPI", FakeBackend),
            mock.patch.object(conversation, "stream_image_outputs", fake_stream_image_outputs),
        ):
            result = collect_image_outputs(stream_image_outputs_with_pool(
                ConversationRequest(
                    model="gpt-image-2",
                    prompt="cat",
                    response_format="b64_json",
                    retry_after_progress=True,
                )
            ))

        streamed_tokens = [payload["token"] for kind, payload in calls if kind == "stream"]
        self.assertEqual(streamed_tokens, ["web-token-1", "web-token-2"])
        self.assertIn(("mark", {"token": "web-token-1", "success": False}), calls)
        self.assertIn(("mark", {"token": "web-token-2", "success": True}), calls)
        self.assertEqual(result["data"][0]["b64_json"], tiny_png_b64())

    def test_non_stream_web_image_tool_arguments_message_retries_next_account(self):
        calls = []

        class FakeAccountService(FakeImageAccountMixin):
            def get_available_access_token(self, **kwargs):
                calls.append(("token", kwargs))
                excluded = kwargs.get("excluded_tokens") or set()
                if "web-token-1" not in excluded:
                    return "web-token-1"
                if "web-token-2" not in excluded:
                    return "web-token-2"
                raise RuntimeError("no available image quota")

            def get_account(self, token):
                return {
                    "access_token": token,
                    "type": "free",
                    "status": "正常",
                    "source_type": "web",
                    "quota": 1,
                    "image_quota_unknown": False,
                }

            def mark_image_result(self, token, success):
                calls.append(("mark", {"token": token, "success": success}))

            def mark_image_rate_limited(self, token, **kwargs):
                calls.append(("limited", {"token": token}))

        class FakeBackend:
            def __init__(self, access_token):
                self.access_token = access_token

        def fake_stream_image_outputs(backend, request, index=1, total=1):
            calls.append(("stream", {"token": backend.access_token}))
            if backend.access_token == "web-token-1":
                yield conversation.ImageOutput(
                    kind="message",
                    model=request.model,
                    index=index,
                    total=total,
                    text='{"prompt":null,"size":"1792x1024","n":1,"transparent_background":false}',
                )
                return
            yield conversation.ImageOutput(
                kind="result",
                model=request.model,
                index=index,
                total=total,
                data=[{"b64_json": tiny_png_b64()}],
            )

        with (
            mock.patch.object(conversation, "account_service", FakeAccountService()),
            mock.patch.object(conversation, "OpenAIBackendAPI", FakeBackend),
            mock.patch.object(conversation, "stream_image_outputs", fake_stream_image_outputs),
        ):
            result = collect_image_outputs(stream_image_outputs_with_pool(
                ConversationRequest(
                    model="gpt-image-2",
                    prompt="cat",
                    response_format="b64_json",
                    retry_after_progress=True,
                    message_as_error=True,
                )
            ))

        streamed_tokens = [payload["token"] for kind, payload in calls if kind == "stream"]
        self.assertEqual(streamed_tokens, ["web-token-1", "web-token-2"])
        self.assertIn(("mark", {"token": "web-token-1", "success": False}), calls)
        self.assertIn(("mark", {"token": "web-token-2", "success": True}), calls)
        self.assertEqual(result["data"][0]["b64_json"], tiny_png_b64())


if __name__ == "__main__":
    unittest.main()
