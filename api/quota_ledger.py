from __future__ import annotations

from fastapi import APIRouter, Header, Query

from api.support import require_admin
from services.quota_ledger_service import quota_ledger_service


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/quota-ledger")
    async def list_quota_ledger(
        user_id: str = Query(default=""),
        limit: int = Query(default=200),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return {"items": quota_ledger_service.list_entries(user_id=user_id, limit=limit)}

    return router
