from __future__ import annotations

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from api.support import (
    apply_image_account_policy,
    client_ip_from_request,
    consume_user_quota,
    image_quota_cost_for_payload,
    refund_user_quota,
    require_identity,
    resolve_image_base_url,
)
from services.config import config
from services.content_filter import check_request, request_text
from services.image_owners_service import record_owner_for_result
from services.image_prompts_service import record_prompt_for_result
from services.log_service import LoggedCall
from services.rate_limit_service import RateLimitExceeded, rate_limit_service
from services.protocol import (
    anthropic_v1_messages,
    openai_v1_chat_complete,
    openai_v1_image_edit,
    openai_v1_image_generations,
    openai_v1_models,
    openai_v1_response,
)


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-image-2"
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = None
    resolution: str | None = None
    response_format: str = "b64_json"
    history_disabled: bool = True
    stream: bool | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    prompt: str | None = None
    n: int | None = None
    stream: bool | None = None
    modalities: list[str] | None = None
    messages: list[dict[str, object]] | None = None


class ResponseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    input: object | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: object | None = None
    stream: bool | None = None


class AnthropicMessageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    messages: list[dict[str, object]] | None = None
    system: object | None = None
    stream: bool | None = None


async def filter_or_log(call: LoggedCall, text: str) -> None:
    try:
        await run_in_threadpool(check_request, text)
    except HTTPException as exc:
        call.log("调用失败", status="failed", error=str(exc.detail))
        raise


def _enforce_image_ip_limit(identity: dict[str, object], request: Request) -> None:
    if str(identity.get("role") or "").strip().lower() == "admin":
        return
    try:
        rate_limit_service.check_image(
            client_ip_from_request(request),
            limit=config.image_ip_minute_limit,
            window_seconds=60,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail={"error": str(exc)}) from exc


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v1/models")
    async def list_models(authorization: str | None = Header(default=None)):
        require_identity(authorization)
        try:
            return await run_in_threadpool(openai_v1_models.list_models)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

    @router.post("/v1/images/generations")
    async def generate_images(
            body: ImageGenerationRequest,
            request: Request,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        apply_image_account_policy(identity, payload)
        _enforce_image_ip_limit(identity, request)
        # /v1 入口按 n * 分辨率倍率扣：1K/默认=1，2K=2，4K=3。
        n = max(1, int(body.n or 1))
        quota_cost = image_quota_cost_for_payload(payload, count=n)
        payload["base_url"] = resolve_image_base_url(request)
        # 上游真失败时把入口扣的额度退回去——LoggedCall.run / stream 内部失败分支会自动回调。
        # 这里 capture identity，failure_refund_amount 跟入口扣的金额一致。
        call = LoggedCall(
            identity, "/v1/images/generations", body.model, "文生图",
            request_text=body.prompt,
            on_failure=lambda amount: refund_user_quota(identity, amount),
            failure_refund_amount=quota_cost,
        )
        await filter_or_log(call, body.prompt)
        consume_user_quota(identity, quota_cost)
        result = await call.run(openai_v1_image_generations.handle, payload)
        # 对接 dict 返回时把图片归属也写一下；StreamingResponse 不动。
        if isinstance(result, dict):
            record_owner_for_result(identity, result.get("data"))
            record_prompt_for_result(body.prompt, result.get("data"))
        return result

    @router.post("/v1/images/edits")
    async def edit_images(
            request: Request,
            authorization: str | None = Header(default=None),
            image: list[UploadFile] | None = File(default=None),
            image_list: list[UploadFile] | None = File(default=None, alias="image[]"),
            prompt: str = Form(...),
            model: str = Form(default="gpt-image-2"),
            n: int = Form(default=1),
            size: str | None = Form(default=None),
            resolution: str | None = Form(default=None),
            response_format: str = Form(default="b64_json"),
            stream: bool | None = Form(default=None),
    ):
        identity = require_identity(authorization)
        if n < 1 or n > 4:
            raise HTTPException(status_code=400, detail={"error": "n must be between 1 and 4"})
        payload = {
            "prompt": prompt,
            "model": model,
            "n": n,
            "size": size,
            "resolution": resolution,
            "response_format": response_format,
            "stream": stream,
        }
        apply_image_account_policy(identity, payload)
        _enforce_image_ip_limit(identity, request)
        # 同样按 n * 分辨率倍率扣，校验过 n 范围之后再扣，避免无效请求也被记账。
        effective_n = max(1, int(n))
        quota_cost = image_quota_cost_for_payload(payload, count=effective_n)
        call = LoggedCall(
            identity, "/v1/images/edits", model, "图生图",
            request_text=prompt,
            on_failure=lambda amount: refund_user_quota(identity, amount),
            failure_refund_amount=quota_cost,
        )
        await filter_or_log(call, prompt)
        consume_user_quota(identity, quota_cost)
        uploads = [*(image or []), *(image_list or [])]
        if not uploads:
            # 已扣的退掉——参数错误本质是 fail-fast，不该让用户白扣
            refund_user_quota(identity, quota_cost)
            raise HTTPException(status_code=400, detail={"error": "image file is required"})
        images: list[tuple[bytes, str, str]] = []
        for upload in uploads:
            image_data = await upload.read()
            if not image_data:
                refund_user_quota(identity, quota_cost)
                raise HTTPException(status_code=400, detail={"error": "image file is empty"})
            images.append((image_data, upload.filename or "image.png", upload.content_type or "image/png"))
        payload["images"] = images
        payload["base_url"] = resolve_image_base_url(request)
        result = await call.run(openai_v1_image_edit.handle, payload)
        if isinstance(result, dict):
            record_owner_for_result(identity, result.get("data"))
            # 图生图：标 is_edit=True，画廊发布时会把 prompt 强制落空，
            # 因为离开参考图后这段修改指令对其它用户毫无复用价值。
            record_prompt_for_result(prompt, result.get("data"), is_edit=True)
        return result

    @router.post("/v1/chat/completions")
    async def create_chat_completion(body: ChatCompletionRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        model = str(payload.get("model") or "auto")
        request_preview = request_text(payload.get("prompt"), payload.get("messages"))
        call = LoggedCall(identity, "/v1/chat/completions", model, "文本生成", request_text=request_preview)
        await filter_or_log(call, request_preview)
        return await call.run(openai_v1_chat_complete.handle, payload)

    @router.post("/v1/responses")
    async def create_response(body: ResponseCreateRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        model = str(payload.get("model") or "auto")
        request_preview = request_text(payload.get("input"), payload.get("instructions"))
        call = LoggedCall(identity, "/v1/responses", model, "Responses", request_text=request_preview)
        await filter_or_log(call, request_preview)
        return await call.run(openai_v1_response.handle, payload)

    @router.post("/v1/messages")
    async def create_message(
            body: AnthropicMessageRequest,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            anthropic_version: str | None = Header(default=None, alias="anthropic-version"),
    ):
        identity = require_identity(authorization or (f"Bearer {x_api_key}" if x_api_key else None))
        payload = body.model_dump(mode="python")
        model = str(payload.get("model") or "auto")
        request_preview = request_text(payload.get("system"), payload.get("messages"), payload.get("tools"))
        call = LoggedCall(identity, "/v1/messages", model, "Messages", request_text=request_preview)
        await filter_or_log(call, request_preview)
        return await call.run(anthropic_v1_messages.handle, payload, sse="anthropic")

    return router
