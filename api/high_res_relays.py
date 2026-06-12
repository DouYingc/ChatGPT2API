from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from api.support import require_admin
from services.high_res_image_relay_service import high_res_image_relay_service


class HighResRelayCreateRequest(BaseModel):
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = "gpt-image-2"
    mode: str = "images"
    enabled: bool = True


class HighResRelayUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    mode: str | None = None
    enabled: bool | None = None


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/high-res-relays")
    async def list_high_res_relays(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": high_res_image_relay_service.list_relays()}

    @router.post("/api/high-res-relays")
    async def create_high_res_relay(
        body: HighResRelayCreateRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            item = high_res_image_relay_service.add_relay(
                name=body.name,
                base_url=body.base_url,
                api_key=body.api_key,
                model=body.model,
                mode=body.mode,
                enabled=body.enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "items": high_res_image_relay_service.list_relays()}

    @router.post("/api/high-res-relays/{relay_id}")
    async def update_high_res_relay(
        relay_id: str,
        body: HighResRelayUpdateRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            item = high_res_image_relay_service.update_relay(relay_id, body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "中转接口不存在，可能已经被删除"})
        return {"item": item, "items": high_res_image_relay_service.list_relays()}

    @router.delete("/api/high-res-relays/{relay_id}")
    async def delete_high_res_relay(relay_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not high_res_image_relay_service.delete_relay(relay_id):
            raise HTTPException(status_code=404, detail={"error": "中转接口不存在，可能已经被删除"})
        return {"items": high_res_image_relay_service.list_relays()}

    @router.post("/api/high-res-relays/{relay_id}/test")
    async def test_high_res_relay(relay_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            result = await run_in_threadpool(high_res_image_relay_service.test_relay, relay_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"result": result}

    return router
