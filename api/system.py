from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from api.support import can_use_high_resolution, can_use_paid_image_accounts, client_ip_from_request, require_admin, require_identity, resolve_image_base_url
from services.account_service import account_service
from services.auth_service import AuthAccountDisabledError, auth_service
from services.backup_service import BackupError, backup_service
from services.config import config
from services.high_res_image_relay_service import high_res_image_relay_service
from services.image_owners_service import get_owner, owner_counts
from services.image_service import cleanup_expired_images, count_total_images, delete_images, download_images_zip, get_image_download_response, get_thumbnail_response, image_storage_summary, list_images
from services.image_task_service import image_task_service
from services.image_tags_service import delete_tag, get_all_tags, set_tags
from services.log_service import log_service
from services.proxy_service import test_proxy
from services.quota_ledger_service import quota_ledger_service
from services.rate_limit_service import RateLimitExceeded, rate_limit_service


def _admin_owner_ids() -> set[str]:
    """收集所有可能落在 image_owners.json 里的 admin id：
    - "admin"：旧 auth_key（CHATGPT2API_AUTH_KEY / config.json.auth-key）的固定 id
    - 其余：通过 auth_service 创建的 admin 角色密钥
    用来把"管理员生成"和"真孤儿"两个桶区分开，别再混在一起。
    """
    ids: set[str] = {"admin"}
    for item in auth_service.list_keys(role="admin"):
        uid = str(item.get("id") or "").strip()
        if uid:
            ids.add(uid)
    return ids


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProxyTestRequest(BaseModel):
    url: str = ""


class ImageDeleteRequest(BaseModel):
    paths: list[str] = []
    start_date: str = ""
    end_date: str = ""
    owner: str = ""
    all_matching: bool = False

class ImageDownloadRequest(BaseModel):
    paths: list[str]

class ImageTagsRequest(BaseModel):
    path: str
    tags: list[str]

class LogDeleteRequest(BaseModel):
    ids: list[str] = []
class BackupDeleteRequest(BaseModel):
    key: str = ""


class PasswordAuthRequest(BaseModel):
    username: str = ""
    password: str = ""


def _local_day_key(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        return text[:10]


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _log_detail(item: dict[str, Any]) -> dict[str, Any]:
    detail = item.get("detail")
    return detail if isinstance(detail, dict) else {}


def _is_image_call_log(item: dict[str, Any]) -> bool:
    detail = _log_detail(item)
    endpoint = str(detail.get("endpoint") or "").lower()
    summary = str(item.get("summary") or "")
    return "/images/" in endpoint or "/image-tasks/" in endpoint or "生图" in summary


def _overview_log_item(item: dict[str, Any]) -> dict[str, object]:
    detail = _log_detail(item)
    return {
        "id": item.get("id"),
        "time": item.get("time"),
        "summary": item.get("summary") or "",
        "key_name": detail.get("key_name") or "",
        "status": detail.get("status") or "",
        "duration_ms": _safe_int(detail.get("duration_ms")),
        "resolution": detail.get("resolution") or "",
        "image_route": detail.get("image_route") or detail.get("route") or "",
        "quota_cost": _safe_int(detail.get("quota_cost")),
        "error": detail.get("error") or "",
    }


def _account_pool_summary() -> dict[str, int]:
    items = account_service.list_accounts()
    return {
        "total": len(items),
        "available": sum(1 for item in items if item.get("status") == "正常"),
        "limited": sum(1 for item in items if item.get("status") == "限流"),
        "abnormal": sum(1 for item in items if item.get("status") == "异常"),
        "disabled": sum(1 for item in items if item.get("status") == "禁用"),
    }


def _relay_overview() -> dict[str, object]:
    relays = high_res_image_relay_service.list_relays()
    today_success = sum(_safe_int(item.get("today_success")) for item in relays)
    today_fail = sum(_safe_int(item.get("today_fail")) for item in relays)
    today_total = today_success + today_fail
    weighted_duration = sum(
        _safe_int(item.get("today_avg_duration_ms"))
        * (_safe_int(item.get("today_success")) + _safe_int(item.get("today_fail")))
        for item in relays
    )
    recent_errors = [
        {
            "id": item.get("id"),
            "name": item.get("name") or item.get("base_url"),
            "error": item.get("last_error") or "",
            "last_used_at": item.get("last_used_at"),
        }
        for item in relays
        if item.get("last_error")
    ][:5]
    return {
        "today_success": today_success,
        "today_fail": today_fail,
        "today_success_rate": round(today_success * 100 / today_total, 1) if today_total else 100.0,
        "today_avg_duration_ms": round(weighted_duration / today_total) if today_total else 0,
        "enabled": sum(1 for item in relays if item.get("enabled")),
        "paused": sum(1 for item in relays if item.get("temporarily_paused")),
        "items": relays,
        "recent_errors": recent_errors,
    }


def _login_payload(identity: dict[str, object], app_version: str, *, key: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": True,
        "version": app_version,
        "role": identity.get("role"),
        "subject_id": identity.get("id"),
        "name": identity.get("name"),
        "account_tier": "premium" if can_use_paid_image_accounts(identity) else "free",
        "can_use_paid_image_accounts": can_use_paid_image_accounts(identity),
        "can_use_high_resolution": can_use_high_resolution(identity),
    }
    if key is not None:
        payload["key"] = key
    return payload


def create_router(app_version: str) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login")
    async def login(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        return _login_payload(identity, app_version)

    @router.post("/auth/password/login")
    async def password_login(body: PasswordAuthRequest):
        try:
            result = auth_service.authenticate_password(body.username, body.password)
        except AuthAccountDisabledError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if result is None:
            raise HTTPException(status_code=401, detail={"error": "用户名或密码错误"})
        identity, raw_key = result
        return _login_payload(identity, app_version, key=raw_key)

    @router.post("/auth/register")
    async def register_user(body: PasswordAuthRequest, request: Request):
        try:
            rate_limit_service.check_register(client_ip_from_request(request), limit=config.register_ip_daily_limit)
        except RateLimitExceeded as exc:
            raise HTTPException(status_code=429, detail={"error": str(exc)}) from exc
        try:
            identity, raw_key = auth_service.register_user(username=body.username, password=body.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        register_quota = int(identity.get("image_total_quota") or 0)
        if register_quota > 0 and not bool(identity.get("image_total_unlimited")):
            quota_ledger_service.record(
                user_id=str(identity.get("id") or ""),
                user_name=str(identity.get("name") or ""),
                role="user",
                kind="image",
                action="register_grant",
                amount=register_quota,
                source="注册赠送",
                note=f"新用户默认画图额度 +{register_quota}",
                remaining={
                    "image_total": identity.get("image_total_remaining"),
                    "image_daily": identity.get("image_daily_remaining"),
                    "image_monthly": identity.get("image_monthly_remaining"),
                },
            )
        return _login_payload(identity, app_version, key=raw_key)

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/settings")
    async def get_settings(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"config": config.get()}

    @router.get("/api/admin/overview")
    async def get_admin_overview(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        today = datetime.now().strftime("%Y-%m-%d")
        call_logs = log_service.list(type="call", start_date=today, end_date=today, limit=1000)
        image_logs = [item for item in call_logs if _is_image_call_log(item)]
        success_logs = [item for item in image_logs if _log_detail(item).get("status") == "success"]
        failed_logs = [item for item in image_logs if _log_detail(item).get("status") == "failed"]
        finished_logs = [item for item in image_logs if _safe_int(_log_detail(item).get("duration_ms")) > 0]
        avg_duration_ms = (
            round(sum(_safe_float(_log_detail(item).get("duration_ms")) for item in finished_logs) / len(finished_logs))
            if finished_logs else 0
        )
        success_rate = round((len(success_logs) / len(image_logs)) * 100, 1) if image_logs else 100.0

        users = auth_service.list_keys(role="user")
        new_users = [item for item in users if _local_day_key(item.get("created_at")) == today]
        ledger_items = [
            item for item in quota_ledger_service.list_entries(limit=1000)
            if _local_day_key(item.get("created_at")) == today
        ]
        redeemed_quota = sum(
            max(0, _safe_int(item.get("amount")))
            for item in ledger_items
            if str(item.get("action") or "") == "redeem"
        )
        consumed_quota = sum(
            abs(_safe_int(item.get("amount")))
            for item in ledger_items
            if str(item.get("action") or "").endswith("_consume") and _safe_int(item.get("amount")) < 0
        )
        refunded_quota = sum(
            max(0, _safe_int(item.get("amount")))
            for item in ledger_items
            if str(item.get("action") or "").endswith("_refund")
        )

        return {
            "date": today,
            "image": {
                "total": len(image_logs),
                "success": len(success_logs),
                "failed": len(failed_logs),
                "success_rate": success_rate,
                "avg_duration_ms": avg_duration_ms,
            },
            "users": {
                "total": len(users),
                "new": len(new_users),
            },
            "quota": {
                "redeemed": redeemed_quota,
                "consumed": consumed_quota,
                "refunded": refunded_quota,
            },
            "relay": _relay_overview(),
            "account_pool": _account_pool_summary(),
            "image_tasks": image_task_service.summary(),
            "recent_failures": [_overview_log_item(item) for item in failed_logs[:8]],
        }

    @router.post("/api/settings")
    async def save_settings(body: SettingsUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"config": config.update(body.model_dump(mode="python"))}

    @router.get("/api/images")
    async def get_images(
        request: Request,
        start_date: str = "",
        end_date: str = "",
        owner: str = "",
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return list_images(
            resolve_image_base_url(request),
            start_date=start_date.strip(),
            end_date=end_date.strip(),
            owner=owner.strip(),
            admin_ids=_admin_owner_ids(),
        )

    @router.get("/api/me/images")
    async def get_my_images(
        request: Request,
        start_date: str = "",
        end_date: str = "",
        authorization: str | None = Header(default=None),
    ):
        """登录用户视角的"我的图片"。

        鉴权用 require_identity，普通 user 密钥也能调；按 identity.id 自动过滤
        image_owners.json 里挂在自己名下的图。Admin 调时退化为 owner=__admin__,
        把所有 admin 生成的图聚合返回（语义上"我"= 管理员这个角色）。

        - Android / 未来其他客户端启动时 fetch 这个端点把云端历史合并进本地 Room
        - 不开放 owner 参数，避免用户冒名查别人的图
        """
        identity = require_identity(authorization)
        admin_ids = _admin_owner_ids()
        role = str(identity.get("role") or "").strip()
        identity_id = str(identity.get("id") or "").strip()
        if role == "admin" or identity_id in admin_ids:
            owner_filter = "__admin__"
        else:
            owner_filter = identity_id
        return list_images(
            resolve_image_base_url(request),
            start_date=start_date.strip(),
            end_date=end_date.strip(),
            owner=owner_filter,
            admin_ids=admin_ids,
        )

    @router.get("/api/images/owners")
    async def get_image_owners(authorization: str | None = Header(default=None)):
        """图片管理页用户筛选下拉的数据源。
        三类语义，互不混淆：
        1. 普通用户：列出所有用户密钥（即便 count=0），admin 期望"我建过的密钥都能筛"
        2. 管理员（__admin__）：所有 admin 角色（含旧 auth_key 的 "admin" id）生成的图聚合
        3. 未归属（__unowned__）：image_owners.json 里没记录的真孤儿，多半是老数据
        孤儿 user id（用户密钥已被删但归属表还留着）单列出来，标记 deleted=true。
        """
        require_admin(authorization)
        counts = owner_counts()
        admin_ids = _admin_owner_ids()
        users = auth_service.list_keys(role="user")
        items: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for user in users:
            uid = str(user.get("id") or "").strip()
            if not uid:
                continue
            seen_ids.add(uid)
            items.append({
                "id": uid,
                "name": user.get("name") or uid,
                "deleted": False,
                "count": int(counts.get(uid, 0)),
            })
        # admin 集合本身已经独立成一桶，所以 seen_ids 里要带上 admin_ids 防止重复
        seen_ids |= admin_ids
        admin_count = sum(int(c) for k, c in counts.items() if k in admin_ids)
        for owner_id, count in counts.items():
            if not owner_id or owner_id in seen_ids:
                continue
            items.append({
                "id": owner_id,
                "name": owner_id,
                "deleted": True,
                "count": int(count),
            })
        items.sort(key=lambda x: (-int(x.get("count") or 0), str(x.get("name") or "")))
        # 真孤儿 = 总图片数 − 已挂归属的所有图（含 admin / 用户 / 已删用户）
        owned_total = sum(int(v) for v in counts.values())
        unowned_count = max(0, count_total_images() - owned_total)
        # 两个固定桶；前端会把它们置顶到列表最上方。
        items.append({"id": "__admin__", "name": "管理员", "deleted": False, "count": admin_count})
        items.append({"id": "__unowned__", "name": "未归属", "deleted": False, "count": unowned_count})
        return {"items": items}

    @router.get("/api/images/storage")
    async def get_image_storage(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await run_in_threadpool(image_storage_summary)

    @router.post("/api/images/cleanup")
    async def cleanup_images_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await run_in_threadpool(cleanup_expired_images)

    @router.get("/image-thumbnails/{image_path:path}", include_in_schema=False)
    async def get_image_thumbnail(image_path: str):
        return get_thumbnail_response(image_path)

    @router.post("/api/images/delete")
    async def delete_images_endpoint(body: ImageDeleteRequest, authorization: str | None = Header(default=None)):
        """图片删除：
          - admin：全权，可按路径 / 按 owner / all_matching 任意筛选删
          - user：只能按路径删自己的图（image_owners.json 里 owner == identity.id）
            其余筛选参数 (start_date / end_date / owner / all_matching) 一律忽略，
            避免误把 all_matching=true 当成"清空所有"操作。
        """
        identity = require_identity(authorization)
        role = str(identity.get("role") or "").lower()
        if role == "admin":
            return delete_images(
                body.paths,
                start_date=body.start_date.strip(),
                end_date=body.end_date.strip(),
                owner=body.owner.strip(),
                all_matching=body.all_matching,
                admin_ids=_admin_owner_ids(),
            )
        # 普通用户路径：只允许按 paths 删自己拥有的图
        user_id = str(identity.get("id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=403, detail={"error": "无权删除"})
        requested = [p.strip().lstrip("/") for p in (body.paths or []) if p and p.strip()]
        # owner 校验：每条 path 都必须 owner == 自己；不是的直接丢弃
        # 这样客户端误传别人的图也只是不删，不会泄露归属
        owned = [rel for rel in requested if get_owner(rel) == user_id]
        if not owned:
            return {"removed": 0}
        return delete_images(owned)

    @router.post("/api/images/download")
    async def download_images_endpoint(body: ImageDownloadRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        buf = download_images_zip(body.paths)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="images.zip"'},
        )

    @router.get("/api/images/download/{image_path:path}")
    async def download_single_image_endpoint(image_path: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return get_image_download_response(image_path)

    @router.get("/api/logs")
    async def get_logs(type: str = "", start_date: str = "", end_date: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": log_service.list(type=type.strip(), start_date=start_date.strip(), end_date=end_date.strip())}

    @router.post("/api/logs/delete")
    async def delete_logs(body: LogDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return log_service.delete(body.ids)

    @router.post("/api/proxy/test")
    async def test_proxy_endpoint(body: ProxyTestRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        candidate = (body.url or "").strip() or config.get_proxy_settings()
        if not candidate:
            raise HTTPException(status_code=400, detail={"error": "proxy url is required"})
        return {"result": await run_in_threadpool(test_proxy, candidate)}

    @router.get("/api/storage/info")
    async def get_storage_info(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        storage = config.get_storage_backend()
        return {
            "backend": storage.get_backend_info(),
            "health": storage.health_check(),
        }

    @router.post("/api/backup/test")
    async def test_backup_connection(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(backup_service.test_connection)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups")
    async def get_backups(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {
                "items": await run_in_threadpool(backup_service.list_backups),
                "state": backup_service.get_status(),
                "settings": backup_service.get_settings(),
            }
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/backups/run")
    async def run_backup_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(backup_service.run_backup)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/backups/delete")
    async def delete_backup_endpoint(body: BackupDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            await run_in_threadpool(backup_service.delete_backup, body.key)
            return {"ok": True}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups/detail")
    async def get_backup_detail(key: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"item": await run_in_threadpool(backup_service.get_backup_detail, key)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups/download")
    async def download_backup_endpoint(key: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item = await run_in_threadpool(backup_service.download_backup, key)
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        filename = str(item.get("name") or "backup.bin")
        quoted = quote(filename)
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "Content-Length": str(int(item.get("size") or 0)),
        }
        return Response(
            content=bytes(item.get("payload") or b""),
            media_type=str(item.get("content_type") or "application/octet-stream"),
            headers=headers,
        )


    @router.get("/api/images/tags")
    async def list_image_tags(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"tags": get_all_tags()}

    @router.post("/api/images/tags")
    async def update_image_tags(body: ImageTagsRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        rel = body.path.strip().lstrip("/")
        if not rel:
            raise HTTPException(status_code=400, detail={"error": "path is required"})
        tags = set_tags(rel, body.tags)
        return {"ok": True, "tags": tags}

    @router.delete("/api/images/tags/{tag}")
    async def delete_image_tag(tag: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        count = delete_tag(tag)
        return {"ok": True, "removed_from": count}

    return router
