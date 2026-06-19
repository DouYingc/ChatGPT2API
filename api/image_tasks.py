from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.image_inputs import parse_image_edit_request, read_image_sources
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
from services.content_filter import check_request
from services.image_task_service import image_task_service
from services.log_service import LoggedCall
from services.public_errors import public_error_detail, should_sanitize_identity
from services.rate_limit_service import RateLimitExceeded, rate_limit_service


class ImageGenerationTaskRequest(BaseModel):
    client_task_id: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-image-2"
    size: str | None = None
    resolution: str | None = None
    quality: str = "auto"


class ImageTaskCancelRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class ResumePollRequest(BaseModel):
    extra_timeout_secs: float = Field(default=30.0, ge=5.0, le=120.0)


def _parse_task_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def filter_or_log(call: LoggedCall, text: str) -> None:
    try:
        await run_in_threadpool(check_request, text)
    except HTTPException as exc:
        call.log("调用失败", status="failed", error=str(exc.detail))
        if should_sanitize_identity(call.identity):
            raise HTTPException(status_code=exc.status_code, detail=public_error_detail(exc.detail)) from exc
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


def _image_log_metadata(payload: dict[str, object], *, size: object = None, quota_cost: int = 1) -> dict[str, object]:
    resolution = str(payload.get("resolution") or "1k").strip().lower() or "1k"
    return {
        "size": size,
        "resolution": resolution,
        "n": 1,
        "quota_cost": max(1, int(quota_cost or 1)),
        "image_route": config.image_route_for_resolution(resolution),
    }


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/image-tasks")
    async def list_image_tasks(
        ids: str = Query(default=""),
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        return await run_in_threadpool(image_task_service.list_tasks, identity, _parse_task_ids(ids))

    @router.post("/api/image-tasks/cancel")
    async def cancel_image_tasks(
        body: ImageTaskCancelRequest,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        ids = [task_id.strip() for task_id in body.ids if task_id and task_id.strip()]
        return await run_in_threadpool(image_task_service.cancel_tasks, identity, ids)

    @router.post("/api/image-tasks/generations")
    async def create_generation_task(
        body: ImageGenerationTaskRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        payload: dict[str, object] = {"model": body.model, "resolution": body.resolution}
        apply_image_account_policy(identity, payload)
        _enforce_image_ip_limit(identity, request)
        quota_cost = image_quota_cost_for_payload(payload)
        consume_user_quota(identity, quota_cost)
        try:
            await filter_or_log(
                LoggedCall(
                    identity,
                    "/api/image-tasks/generations",
                    str(payload.get("model") or body.model),
                    "文生图任务",
                    request_text=body.prompt,
                    metadata=_image_log_metadata(payload, size=body.size, quota_cost=quota_cost),
                ),
                body.prompt,
            )
            return await run_in_threadpool(
                image_task_service.submit_generation,
                identity,
                client_task_id=body.client_task_id,
                prompt=body.prompt,
                model=str(payload.get("model") or body.model),
                size=body.size,
                resolution=str(payload.get("resolution") or body.resolution or "") or None,
                plan_type=str(payload.get("plan_type") or "").strip() or None,
                allowed_plan_types=payload.get("allowed_plan_types"),
                quality=body.quality,
                base_url=resolve_image_base_url(request),
                quota_cost=quota_cost,
            )
        except ValueError as exc:
            refund_user_quota(identity, quota_cost)
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except HTTPException:
            refund_user_quota(identity, quota_cost)
            raise

    @router.post("/api/image-tasks/edits")
    async def create_edit_task(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        payload, image_sources = await parse_image_edit_request(request)
        client_task_id = str(payload.get("client_task_id") or "").strip()
        if not client_task_id:
            raise HTTPException(status_code=400, detail={"error": "client_task_id is required"})
        prompt = str(payload["prompt"])
        model = str(payload["model"])
        policy_payload: dict[str, object] = {"model": model, "resolution": payload.get("resolution")}
        apply_image_account_policy(identity, policy_payload)
        _enforce_image_ip_limit(identity, request)
        quota_cost = image_quota_cost_for_payload(policy_payload)
        consume_user_quota(identity, quota_cost)
        try:
            await filter_or_log(
                LoggedCall(
                    identity,
                    "/api/image-tasks/edits",
                    str(policy_payload.get("model") or model),
                    "图生图任务",
                    request_text=prompt,
                    metadata=_image_log_metadata(policy_payload, size=payload["size"], quota_cost=quota_cost),
                ),
                prompt,
            )
            images = await read_image_sources(image_sources)
            if not images:
                raise HTTPException(status_code=400, detail={"error": "image file is required"})
            return await run_in_threadpool(
                image_task_service.submit_edit,
                identity,
                client_task_id=client_task_id,
                prompt=prompt,
                model=str(policy_payload.get("model") or model),
                size=payload["size"],
                resolution=str(policy_payload.get("resolution") or payload.get("resolution") or "") or None,
                plan_type=str(policy_payload.get("plan_type") or "").strip() or None,
                allowed_plan_types=policy_payload.get("allowed_plan_types"),
                quality=payload["quality"],
                base_url=resolve_image_base_url(request),
                images=images,
                quota_cost=quota_cost,
            )
        except ValueError as exc:
            refund_user_quota(identity, quota_cost)
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except HTTPException:
            refund_user_quota(identity, quota_cost)
            raise

    @router.post("/api/image-tasks/{task_id}/resume-poll")
    async def resume_image_poll(
        task_id: str,
        body: ResumePollRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        try:
            return await run_in_threadpool(
                image_task_service.resume_poll,
                identity,
                task_id,
                body.extra_timeout_secs,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    return router
