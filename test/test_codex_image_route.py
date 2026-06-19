from __future__ import annotations

import base64
import time
import unittest
from io import BytesIO
from unittest import mock

from PIL import Image

from services.openai_backend_api import OpenAIBackendAPI
from services.protocol import conversation
from services.protocol.conversation import ConversationRequest, collect_image_outputs, stream_image_outputs, stream_image_outputs_with_pool
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
    def test_image_state_captures_patch_asset_pointer_after_tool_invoked(self):
        state = conversation.ConversationState(tool_invoked=True)
        payload = (
            '{"conversation_id":"cid-1","asset_pointer":'
            '"sediment://file_00000000abc123","author":{"role":"assistant"}}'
        )

        conversation.update_conversation_state(state, payload, {"o": "patch", "v": []})

        self.assertEqual(state.conversation_id, "cid-1")
        self.assertEqual(state.sediment_ids, ["file_00000000abc123"])

    def test_extract_image_records_accepts_assistant_asset_pointer(self):
        backend = object.__new__(OpenAIBackendAPI)
        data = {
            "mapping": {
                "msg-1": {
                    "message": {
                        "author": {"role": "assistant"},
                        "create_time": 1,
                        "metadata": {},
                        "content": {
                            "content_type": "multimodal_text",
                            "parts": [{
                                "content_type": "image_asset_pointer",
                                "asset_pointer": "sediment://file_00000000abc123",
                            }],
                        },
                    }
                }
            }
        }

        records = backend._extract_image_tool_records(data)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["sediment_ids"], ["file_00000000abc123"])

    def test_web_image_tool_arguments_message_enters_polling(self):
        calls = []

        class FakeBackend:
            def resolve_conversation_image_urls(self, *args, **kwargs):
                calls.append(("resolve", args, kwargs))
                return ["https://example.test/image.png"]

            def download_image_bytes(self, urls):
                calls.append(("download", list(urls), {}))
                return [base64.b64decode(tiny_png_b64())]

        def fake_conversation_events(*args, **kwargs):
            yield {
                "type": "conversation.event",
                "conversation_id": "cid-1",
                "text": '{"prompt":"cat","size":"1024x576","n":1}',
                "tool_invoked": True,
                "turn_use_case": "image",
            }

        with mock.patch.object(conversation, "conversation_events", fake_conversation_events):
            outputs = list(stream_image_outputs(
                FakeBackend(),
                ConversationRequest(
                    model="gpt-image-2",
                    prompt="cat",
                    size="16:9",
                    resolution="1k",
                ),
            ))

        self.assertEqual(outputs[-1].kind, "result")
        self.assertEqual(outputs[-1].data[0]["b64_json"], tiny_png_b64())
        self.assertEqual(calls[0][0], "resolve")
        self.assertEqual(calls[1][0], "download")

    def test_web_image_text_message_without_file_still_polls_current_conversation(self):
        calls = []

        class FakeBackend:
            def resolve_conversation_image_urls(self, *args, **kwargs):
                calls.append(("resolve", args, kwargs))
                return []

        def fake_conversation_events(*args, **kwargs):
            yield {
                "type": "conversation.event",
                "conversation_id": "cid-1",
                "text": "一座古风夜色下的别庄后院场景已生成。\n\nIf you want to try other directions, I can...",
                "tool_invoked": True,
                "turn_use_case": "image gen",
            }

        with mock.patch.object(conversation, "conversation_events", fake_conversation_events):
            outputs = list(stream_image_outputs(
                FakeBackend(),
                ConversationRequest(
                    model="gpt-image-2",
                    prompt="cat",
                    size="16:9",
                    resolution="1k",
                ),
            ))

        self.assertEqual(outputs[-1].kind, "message")
        self.assertEqual(calls[0][0], "resolve")

    def test_web_image_empty_stream_recovers_conversation_and_polls(self):
        calls = []

        class FakeBackend:
            def find_conversation_by_prompt(self, prompt, started_at, timeout_secs=5.0):
                calls.append(("find", {"prompt": prompt, "started_at": started_at, "timeout_secs": timeout_secs}))
                return "cid-recovered"

            def _poll_image_results(self, conversation_id, timeout_secs, initial_file_ids=None, initial_sediment_ids=None):
                calls.append(("poll", {"conversation_id": conversation_id, "timeout_secs": timeout_secs}))
                return ["file-1"], []

            def resolve_conversation_image_urls(self, conversation_id, file_ids, sediment_ids, poll=True, poll_timeout_secs=None):
                calls.append(("resolve", {"conversation_id": conversation_id, "file_ids": list(file_ids), "poll": poll}))
                if not conversation_id:
                    return []
                return ["https://example.test/image.png"]

            def download_image_bytes(self, urls):
                calls.append(("download", list(urls), {}))
                return [base64.b64decode(tiny_png_b64())]

        def fake_conversation_events(*args, **kwargs):
            if False:
                yield {}

        with (
            mock.patch.object(conversation, "conversation_events", fake_conversation_events),
            mock.patch.object(conversation.time, "sleep", lambda _seconds: None),
        ):
            outputs = list(stream_image_outputs(
                FakeBackend(),
                ConversationRequest(
                    model="gpt-image-2",
                    prompt="cat",
                    size="16:9",
                    resolution="1k",
                ),
            ))

        self.assertEqual(outputs[-1].kind, "result")
        self.assertEqual(outputs[-1].data[0]["b64_json"], tiny_png_b64())
        self.assertEqual([kind for kind, *_ in calls], ["resolve", "find", "poll", "resolve", "download"])

    def test_tool_arguments_json_with_trailing_text_is_image_text_reply(self):
        text = (
            '{"prompt":"cat","size":"1024x576","n":1}'
            "一幅夜色沉静的古风别庄后院场景已生成。"
        )

        self.assertTrue(conversation.is_model_text_reply_instead_of_image(text))

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
        limited_tokens = set()

        class FakeAccountService(FakeImageAccountMixin):
            def get_available_access_token(self, **kwargs):
                calls.append(("token", kwargs))
                if "codex-token-1" not in limited_tokens:
                    return "codex-token-1"
                if "codex-token-2" not in limited_tokens:
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
                limited_tokens.add(token)
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

    def test_non_stream_web_image_no_result_after_progress_does_not_retry_account(self):
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

        def fake_stream_image_outputs(backend, request, index=1, total=1, poll_timeout_secs=None):
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
            with self.assertRaises(conversation.ImageGenerationError) as context:
                collect_image_outputs(stream_image_outputs_with_pool(
                    ConversationRequest(
                        model="gpt-image-2",
                        prompt="cat",
                        response_format="b64_json",
                        retry_after_progress=True,
                    )
                ))

        streamed_tokens = [payload["token"] for kind, payload in calls if kind == "stream"]
        self.assertEqual(streamed_tokens, ["web-token-1"])
        self.assertIn(("mark", {"token": "web-token-1", "success": False}), calls)
        self.assertIn("without generating images", str(context.exception))

    def test_non_stream_web_image_attempt_poll_uses_default_timeout(self):
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

        def fake_stream_image_outputs(backend, request, index=1, total=1, poll_timeout_secs=None):
            calls.append(("stream", {"token": backend.access_token, "poll_timeout_secs": poll_timeout_secs}))
            yield conversation.ImageOutput(
                kind="result",
                model=request.model,
                index=index,
                total=total,
                data=[{"b64_json": tiny_png_b64()}],
            )

        with (
            mock.patch.object(type(conversation.config), "image_poll_timeout_secs", new_callable=mock.PropertyMock) as timeout_mock,
            mock.patch.object(conversation, "account_service", FakeAccountService()),
            mock.patch.object(conversation, "OpenAIBackendAPI", FakeBackend),
            mock.patch.object(conversation, "stream_image_outputs", fake_stream_image_outputs),
        ):
            timeout_mock.return_value = 120
            result = collect_image_outputs(stream_image_outputs_with_pool(
                ConversationRequest(
                    model="gpt-image-2",
                    prompt="cat",
                    response_format="b64_json",
                    retry_after_progress=True,
                )
            ))

        stream_calls = [payload for kind, payload in calls if kind == "stream"]
        self.assertEqual([item["token"] for item in stream_calls], ["web-token-1"])
        self.assertIsNone(stream_calls[0]["poll_timeout_secs"])
        self.assertEqual(result["data"][0]["b64_json"], tiny_png_b64())

    def test_non_stream_web_image_tool_arguments_message_does_not_retry_next_account(self):
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

        def fake_stream_image_outputs(backend, request, index=1, total=1, poll_timeout_secs=None):
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
            with self.assertRaises(conversation.ImageGenerationError) as context:
                collect_image_outputs(stream_image_outputs_with_pool(
                    ConversationRequest(
                        model="gpt-image-2",
                        prompt="cat",
                        response_format="b64_json",
                        retry_after_progress=True,
                        message_as_error=True,
                    )
                ))

        streamed_tokens = [payload["token"] for kind, payload in calls if kind == "stream"]
        self.assertEqual(streamed_tokens, ["web-token-1"])
        self.assertIn(("mark", {"token": "web-token-1", "success": False}), calls)
        self.assertIn('"size":"1792x1024"', str(context.exception))

    def test_non_stream_web_image_retry_stops_after_deadline(self):
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

        def fake_stream_image_outputs(backend, request, index=1, total=1, poll_timeout_secs=None):
            calls.append(("stream", {"token": backend.access_token}))
            time.sleep(0.02)
            yield conversation.ImageOutput(
                kind="progress",
                model=request.model,
                index=index,
                total=total,
                text="waiting",
            )

        with (
            mock.patch.object(conversation, "account_service", FakeAccountService()),
            mock.patch.object(conversation, "OpenAIBackendAPI", FakeBackend),
            mock.patch.object(conversation, "stream_image_outputs", fake_stream_image_outputs),
        ):
            with self.assertRaises(conversation.ImageGenerationError) as context:
                collect_image_outputs(stream_image_outputs_with_pool(
                    ConversationRequest(
                        model="gpt-image-2",
                        prompt="cat",
                        response_format="b64_json",
                        retry_after_progress=True,
                        deadline_at=time.monotonic() + 0.01,
                    )
                ))

        streamed_tokens = [payload["token"] for kind, payload in calls if kind == "stream"]
        self.assertEqual(streamed_tokens, ["web-token-1"])
        self.assertIn("超过", str(context.exception))
        self.assertIn(("mark", {"token": "web-token-1", "success": False}), calls)


if __name__ == "__main__":
    unittest.main()
