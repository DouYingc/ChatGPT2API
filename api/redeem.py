from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from api.support import require_admin, require_identity
from services.auth_service import auth_service
from services.quota_ledger_service import quota_ledger_service
from services.redeem_code_service import REDEEM_CODE_AMOUNTS, redeem_code_service


class RedeemCodeCreateRequest(BaseModel):
    amount: int = 100
    quantity: int = 1


class RedeemCodeUseRequest(BaseModel):
    code: str = ""


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/redeem-codes")
    async def list_redeem_codes(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": redeem_code_service.list_codes(), "amounts": list(REDEEM_CODE_AMOUNTS)}

    @router.post("/api/redeem-codes")
    async def create_redeem_codes(body: RedeemCodeCreateRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        try:
            created = redeem_code_service.create_codes(
                amount=body.amount,
                quantity=body.quantity,
                created_by=str(admin.get("id") or ""),
                created_by_name=str(admin.get("name") or ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"created": created, "items": redeem_code_service.list_codes(), "amounts": list(REDEEM_CODE_AMOUNTS)}

    @router.delete("/api/redeem-codes/{code_id}")
    async def delete_redeem_code(code_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not redeem_code_service.delete_code(code_id):
            raise HTTPException(status_code=404, detail={"error": "兑换码不存在，可能已经被删除"})
        return {"items": redeem_code_service.list_codes(), "amounts": list(REDEEM_CODE_AMOUNTS)}

    @router.post("/api/redeem")
    async def redeem_code(body: RedeemCodeUseRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "只有普通用户可以兑换额度"})
        user_id = str(identity.get("id") or "").strip()
        user_name = str(identity.get("name") or "").strip()
        try:
            item, next_identity = redeem_code_service.redeem(
                code=body.code,
                user_id=user_id,
                user_name=user_name,
                apply_amount=lambda amount: auth_service.add_image_total_quota(user_id, amount),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        amount = int(item.get("amount") or 0)
        if amount > 0:
            quota_ledger_service.record(
                user_id=user_id,
                user_name=user_name,
                role="user",
                kind="image",
                action="redeem",
                amount=amount,
                source="兑换码",
                note=f"兑换码 {item.get('code')} +{amount}",
                remaining={
                    "image_total": next_identity.get("image_total_remaining"),
                    "image_daily": next_identity.get("image_daily_remaining"),
                    "image_monthly": next_identity.get("image_monthly_remaining"),
                },
                meta={"code_id": item.get("id"), "code": item.get("code")},
            )
        return {
            "ok": True,
            "amount": item.get("amount"),
            "code": item,
            "identity": next_identity,
        }

    return router
