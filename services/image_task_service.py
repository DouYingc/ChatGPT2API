from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config
from services.content_filter import request_text
from services.image_owners_service import record_owner_for_result
from services.image_prompts_service import record_prompt_for_result
from services.log_service import LOG_TYPE_CALL, log_service
from services.public_errors import public_error_message
from services.protocol import openai_v1_image_edit, openai_v1_image_generations

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_ERROR = "error"
TASK_STATUS_CANCELED = "canceled"
TERMINAL_STATUSES = {TASK_STATUS_SUCCESS, TASK_STATUS_ERROR, TASK_STATUS_CANCELED}
UNFINISHED_STATUSES = {TASK_STATUS_QUEUED, TASK_STATUS_RUNNING}
RUNNING_TIMEOUT_BUFFER_SECS = 60
VALID_STATUSES = {
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCESS,
    TASK_STATUS_ERROR,
    TASK_STATUS_CANCELED,
}


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _timestamp(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:26], fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _clean(value: object, default: str = "") -> str:
    return str(value or default).strip()


def _quota_cost(value: object) -> int:
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def _is_high_resolution(value: object) -> bool:
    normalized = _clean(value).lower().replace(" ", "").replace("-", "")
    return normalized in {"2k", "4k"}


def _owner_id(identity: dict[str, object]) -> str:
    return _clean(identity.get("id")) or "anonymous"


def _task_key(owner_id: str, task_id: str) -> str:
    return f"{owner_id}:{task_id}"


def _collect_image_urls(data: list[Any]) -> list[str]:
    urls: list[str] = []
    for item in data:
        if isinstance(item, dict):
            url = item.get("url")
            if isinstance(url, str) and url:
                urls.append(url)
    return urls


def _public_error(task: dict[str, Any], *, sanitize_errors: bool) -> str:
    message = _clean(task.get("error"))
    if not sanitize_errors or not message:
        return message
    return public_error_message(message)


def _public_task(task: dict[str, Any], *, sanitize_errors: bool = False) -> dict[str, Any]:
    item = {
        "id": task.get("id"),
        "status": task.get("status"),
        "mode": task.get("mode"),
        "model": task.get("model"),
        "size": task.get("size"),
        "resolution": task.get("resolution"),
        "quality": task.get("quality"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }
    if task.get("conversation_id"):
        item["conversation_id"] = task.get("conversation_id")
    if task.get("data") is not None:
        item["data"] = task.get("data")
    if task.get("usage") is not None:
        item["usage"] = task.get("usage")
    error = _public_error(task, sanitize_errors=sanitize_errors)
    if error:
        item["error"] = error
    if task.get("progress"):
        item["progress"] = task.get("progress")
    if task.get("duration_ms") is not None:
        item["duration_ms"] = task.get("duration_ms")
    if task.get("status") in (TASK_STATUS_RUNNING, TASK_STATUS_QUEUED):
        if task.get("status") == TASK_STATUS_RUNNING:
            # RUNNING 状态仅在 started_ts 被设置后（image_stream_resolve_start）才计时
            base_ts = task.get("started_ts")
        else:
            # QUEUED 状态从 created_ts 开始计时（排队等待中）
            base_ts = task.get("created_ts") or task.get("updated_ts")
        if base_ts:
            item["elapsed_secs"] = round(time.time() - base_ts, 1)
    return item


class ConfigurableLimiter:
    def __init__(self, limit_getter: Callable[[], int]):
        self.limit_getter = limit_getter
        self._condition = threading.Condition()
        self._active = 0

    def acquire(self) -> None:
        with self._condition:
            while self._active >= self.limit:
                self._condition.wait(timeout=1)
            self._active += 1

    def release(self) -> None:
        with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    @property
    def limit(self) -> int:
        try:
            return max(1, int(self.limit_getter()))
        except Exception:
            return 3

    @property
    def active(self) -> int:
        with self._condition:
            return self._active


class ImageTaskService:
    def __init__(
        self,
        path: Path,
        *,
        generation_handler: Callable[[dict[str, Any]], dict[str, Any]] = openai_v1_image_generations.handle,
        edit_handler: Callable[[dict[str, Any]], dict[str, Any]] = openai_v1_image_edit.handle,
        retention_days_getter: Callable[[], int] | None = None,
        running_timeout_getter: Callable[[], float] | None = None,
    ):
        self.path = path
        self.generation_handler = generation_handler
        self.edit_handler = edit_handler
        self.retention_days_getter = retention_days_getter or (lambda: config.image_retention_days)
        self.running_timeout_getter = running_timeout_getter or (
            lambda: config.image_poll_timeout_secs + RUNNING_TIMEOUT_BUFFER_SECS
        )
        self._high_res_limiter = ConfigurableLimiter(lambda: config.high_res_image_concurrency)
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._tasks = self._load_locked()
            changed = self._recover_unfinished_locked()
            changed = self._cleanup_locked() or changed
            if changed:
                self._save_locked()

    def submit_generation(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        prompt: str,
        model: str,
        size: str | None,
        resolution: str | None = None,
        plan_type: str | None = None,
        allowed_plan_types: object = None,
        quality: str = "auto",
        base_url: str = "",
        quota_cost: int = 1,
    ) -> dict[str, Any]:
        payload = {
            "prompt": prompt,
            "model": model,
            "n": 1,
            "size": size,
            "resolution": resolution,
            "plan_type": plan_type,
            "allowed_plan_types": allowed_plan_types,
            "quality": quality,
            "response_format": "url",
            "base_url": base_url,
            "quota_cost": _quota_cost(quota_cost),
        }
        return self._submit(identity, client_task_id=client_task_id, mode="generate", payload=payload)

    def submit_edit(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        prompt: str,
        model: str,
        size: str | None,
        resolution: str | None = None,
        plan_type: str | None = None,
        allowed_plan_types: object = None,
        quality: str = "auto",
        base_url: str = "",
        images: list[tuple[bytes, str, str]] | None = None,
        quota_cost: int = 1,
    ) -> dict[str, Any]:
        payload = {
            "prompt": prompt,
            "images": images or [],
            "model": model,
            "n": 1,
            "size": size,
            "resolution": resolution,
            "plan_type": plan_type,
            "allowed_plan_types": allowed_plan_types,
            "quality": quality,
            "response_format": "url",
            "base_url": base_url,
            "quota_cost": _quota_cost(quota_cost),
        }
        return self._submit(identity, client_task_id=client_task_id, mode="edit", payload=payload)

    def list_tasks(self, identity: dict[str, object], task_ids: list[str]) -> dict[str, Any]:
        owner = _owner_id(identity)
        sanitize_errors = str(identity.get("role") or "").strip().lower() != "admin"
        requested_ids = [_clean(task_id) for task_id in task_ids if _clean(task_id)]
        refunds: list[tuple[str, int]] = []
        with self._lock:
            refunds = self._expire_stale_running_locked()
            cleaned = self._cleanup_locked()
            if refunds or cleaned:
                self._save_locked()
            items = []
            missing_ids = []
            for task_id in requested_ids:
                task = self._tasks.get(_task_key(owner, task_id))
                if task is None:
                    missing_ids.append(task_id)
                else:
                    items.append(_public_task(task, sanitize_errors=sanitize_errors))
            if not requested_ids:
                items = [
                    _public_task(task, sanitize_errors=sanitize_errors)
                    for task in self._tasks.values()
                    if task.get("owner_id") == owner
                ]
                items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
                missing_ids = []
        for owner_id, amount in refunds:
            self._refund_owner_id(owner_id, amount)
        return {"items": items, "missing_ids": missing_ids}

    def cancel_tasks(self, identity: dict[str, object], task_ids: list[str]) -> dict[str, Any]:
        owner = _owner_id(identity)
        requested_ids = [_clean(task_id) for task_id in task_ids if _clean(task_id)]
        canceled: list[str] = []
        refund_amounts: list[int] = []
        skipped: list[str] = []
        missing_ids: list[str] = []
        with self._lock:
            for task_id in requested_ids:
                task = self._tasks.get(_task_key(owner, task_id))
                if task is None:
                    missing_ids.append(task_id)
                    continue
                status = task.get("status")
                if status in TERMINAL_STATUSES:
                    skipped.append(task_id)
                    continue
                task["status"] = TASK_STATUS_CANCELED
                task["error"] = "已取消"
                task["updated_at"] = _now_iso()
                task["updated_ts"] = time.time()
                canceled.append(task_id)
                refund_amounts.append(_quota_cost(task.get("quota_cost")))
            if canceled:
                self._save_locked()
        for amount in refund_amounts:
            self._refund_one(identity, amount)
        return {"canceled": canceled, "skipped": skipped, "missing_ids": missing_ids}

    def _refund_one(self, identity: dict[str, object], amount: int = 1) -> None:
        role = str(identity.get("role") or "").strip().lower()
        item_id = str(identity.get("id") or "").strip()
        if role == "admin":
            return
        self._refund_owner_id(item_id, amount)

    def _refund_owner_id(self, owner_id: str, amount: int = 1) -> None:
        item_id = _clean(owner_id)
        if not item_id or item_id == "admin":
            return
        try:
            from services.auth_service import auth_service
            auth_service.refund_image_quota(item_id, _quota_cost(amount))
        except Exception:
            pass

    def _submit(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        mode: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = _clean(client_task_id)
        if not task_id:
            raise ValueError("client_task_id is required")
        owner = _owner_id(identity)
        sanitize_errors = str(identity.get("role") or "").strip().lower() != "admin"
        key = _task_key(owner, task_id)
        now = _now_iso()
        should_start = False
        refunds: list[tuple[str, int]] = []
        existing_task_response: dict[str, Any] | None = None
        with self._lock:
            refunds = self._expire_stale_running_locked()
            cleaned = self._cleanup_locked()
            task = self._tasks.get(key)
            if task is not None:
                if refunds or cleaned:
                    self._save_locked()
                existing_task_response = _public_task(task, sanitize_errors=sanitize_errors)
            else:
                task = {
                    "id": task_id,
                    "owner_id": owner,
                    "status": TASK_STATUS_QUEUED,
                    "mode": mode,
                    "model": _clean(payload.get("model"), "gpt-image-2"),
                    "size": _clean(payload.get("size")),
                    "resolution": _clean(payload.get("resolution")),
                    "quality": _clean(payload.get("quality"), "auto"),
                    "quota_cost": _quota_cost(payload.get("quota_cost")),
                    "created_at": now,
                    "updated_at": now,
                    "created_ts": time.time(),
                }
                self._tasks[key] = task
                self._save_locked()
                should_start = True
        for owner_id, amount in refunds:
            self._refund_owner_id(owner_id, amount)
        if existing_task_response is not None:
            return existing_task_response

        if should_start:
            thread = threading.Thread(
                target=self._run_task,
                args=(key, mode, payload, dict(identity), _clean(payload.get("model"), "gpt-image-2")),
                name=f"image-task-{task_id[:16]}",
                daemon=True,
            )
            thread.start()
        return _public_task(task, sanitize_errors=sanitize_errors)

    def _run_task(
        self,
        key: str,
        mode: str,
        payload: dict[str, Any],
        identity: dict[str, object],
        model: str,
    ) -> None:
        acquired_high_res_slot = False
        started = time.time()
        try:
            with self._lock:
                task = self._tasks.get(key)
                if task is None or task.get("status") == TASK_STATUS_CANCELED:
                    return

            if _is_high_resolution(payload.get("resolution")):
                self._high_res_limiter.acquire()
                acquired_high_res_slot = True
                with self._lock:
                    task = self._tasks.get(key)
                    if task is None or task.get("status") == TASK_STATUS_CANCELED:
                        return

            self._update_task(key, status=TASK_STATUS_RUNNING, error="")

            def progress_callback(step: str) -> None:
                with self._lock:
                    task = self._tasks.get(key)
                    if task is None or task.get("status") == TASK_STATUS_CANCELED:
                        return
                if step == "image_stream_resolve_start":
                    self._update_task(key, started_ts=time.time())
                self._update_task(key, progress=step)

            payload_with_progress = {**payload, "progress_callback": progress_callback}
            handler = self.edit_handler if mode == "edit" else self.generation_handler
            result = handler(payload_with_progress)
            with self._lock:
                task = self._tasks.get(key)
                if task is None or task.get("status") != TASK_STATUS_RUNNING:
                    return
            if not isinstance(result, dict):
                raise RuntimeError("image task returned streaming result unexpectedly")
            data = result.get("data")
            account_email = _clean(result.get("_account_email") or result.get("account_email"))
            if not isinstance(data, list) or not data:
                upstream = _clean(result.get("message"))
                if upstream:
                    message = upstream
                else:
                    message = "号池中没有可用账号或所有账号均被限流，请检查号池状态（账号额度、是否被封禁、是否到达生图上限）"
                error = RuntimeError(message)
                if account_email:
                    setattr(error, "account_email", account_email)
                raise error
            usage = result.get("usage")
            duration_ms = int((time.time() - started) * 1000)
            self._update_task(key, status=TASK_STATUS_SUCCESS, data=data, usage=usage, error="", duration_ms=duration_ms)
            record_owner_for_result(identity, data)
            record_prompt_for_result(payload.get("prompt"), data, is_edit=(mode == "edit"))
            self._log_call(
                identity,
                mode,
                model,
                started,
                "调用完成",
                request_preview=request_text(payload.get("prompt")),
                size=_clean(payload.get("size")),
                resolution=_clean(payload.get("resolution")),
                quota_cost=_quota_cost(payload.get("quota_cost")),
                urls=_collect_image_urls(data),
                account_email=account_email,
            )
        except Exception as exc:
            with self._lock:
                task = self._tasks.get(key)
                if task is None or task.get("status") != TASK_STATUS_RUNNING:
                    return
            error_message = str(exc) or "image task failed"
            account_email = _clean(getattr(exc, "account_email", ""))
            conversation_id = _clean(getattr(exc, "conversation_id", ""))
            duration_ms = int((time.time() - started) * 1000)
            self._update_task(key, status=TASK_STATUS_ERROR, error=error_message, data=[],
                              duration_ms=duration_ms,
                              **({"conversation_id": conversation_id} if conversation_id else {}))
            self._refund_one(identity, _quota_cost(payload.get("quota_cost")))
            self._log_call(
                identity,
                mode,
                model,
                started,
                "调用失败",
                request_preview=request_text(payload.get("prompt")),
                size=_clean(payload.get("size")),
                resolution=_clean(payload.get("resolution")),
                quota_cost=_quota_cost(payload.get("quota_cost")),
                status="failed",
                error=error_message,
                account_email=account_email,
            )
        finally:
            if acquired_high_res_slot:
                self._high_res_limiter.release()

    def summary(self) -> dict[str, object]:
        refunds: list[tuple[str, int]] = []
        with self._lock:
            refunds = self._expire_stale_running_locked()
            cleaned = self._cleanup_locked()
            if refunds or cleaned:
                self._save_locked()
            counts = {status: 0 for status in VALID_STATUSES}
            high_res_counts = {"queued": 0, "running": 0}
            for task in self._tasks.values():
                status = _clean(task.get("status"))
                if status in counts:
                    counts[status] += 1
                if _is_high_resolution(task.get("resolution")) and status in high_res_counts:
                    high_res_counts[status] += 1
            result = {
                "total": len(self._tasks),
                "queued": counts[TASK_STATUS_QUEUED],
                "running": counts[TASK_STATUS_RUNNING],
                "success": counts[TASK_STATUS_SUCCESS],
                "error": counts[TASK_STATUS_ERROR],
                "canceled": counts[TASK_STATUS_CANCELED],
                "high_res": {
                    **high_res_counts,
                    "active": self._high_res_limiter.active,
                    "limit": self._high_res_limiter.limit,
                },
            }
        for owner_id, amount in refunds:
            self._refund_owner_id(owner_id, amount)
        return result

    def _log_call(
        self,
        identity: dict[str, object],
        mode: str,
        model: str,
        started: float,
        suffix: str,
        *,
        request_preview: str = "",
        size: str = "",
        resolution: str = "",
        quota_cost: int = 1,
        status: str = "success",
        error: str = "",
        urls: list[str] | None = None,
        account_email: str = "",
    ) -> None:
        endpoint = "/v1/images/edits" if mode == "edit" else "/v1/images/generations"
        summary_prefix = "图生图" if mode == "edit" else "文生图"
        detail = {
            "key_id": identity.get("id"),
            "key_name": identity.get("name"),
            "role": identity.get("role"),
            "endpoint": endpoint,
            "model": model,
            "started_at": datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": _now_iso(),
            "duration_ms": int((time.time() - started) * 1000),
            "status": status,
        }
        if request_preview:
            detail["request_text"] = request_preview
        if size:
            detail["size"] = size
        if resolution:
            detail["resolution"] = resolution
        detail["quota_cost"] = _quota_cost(quota_cost)
        detail["image_route"] = config.image_route_for_resolution(resolution or "1k")
        if error:
            detail["error"] = error
        if account_email:
            detail["account_email"] = account_email
        if urls:
            detail["urls"] = list(dict.fromkeys(urls))
        try:
            log_service.add(LOG_TYPE_CALL, f"{summary_prefix}{suffix}", detail)
        except Exception:
            pass

    def _update_task(self, key: str, **updates: Any) -> None:
        with self._lock:
            task = self._tasks.get(key)
            if task is None:
                return
            task.update(updates)
            task["updated_at"] = _now_iso()
            task["updated_ts"] = time.time()
            self._save_locked()

    def _load_locked(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        raw_items = raw.get("tasks") if isinstance(raw, dict) else raw
        if not isinstance(raw_items, list):
            return {}
        tasks: dict[str, dict[str, Any]] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            task_id = _clean(item.get("id"))
            owner = _clean(item.get("owner_id"))
            if not task_id or not owner:
                continue
            status = _clean(item.get("status"))
            if status not in VALID_STATUSES:
                status = TASK_STATUS_ERROR
            task = {
                "id": task_id,
                "owner_id": owner,
                "status": status,
                "mode": "edit" if item.get("mode") == "edit" else "generate",
                "model": _clean(item.get("model"), "gpt-image-2"),
                "size": _clean(item.get("size")),
                "resolution": _clean(item.get("resolution")),
                "quality": _clean(item.get("quality"), "auto"),
                "quota_cost": _quota_cost(item.get("quota_cost")),
                "created_at": _clean(item.get("created_at"), _now_iso()),
                "updated_at": _clean(item.get("updated_at"), _clean(item.get("created_at"), _now_iso())),
                "created_ts": item.get("created_ts"),
                "updated_ts": item.get("updated_ts"),
                "started_ts": item.get("started_ts"),
                "duration_ms": item.get("duration_ms"),
            }
            data = item.get("data")
            if isinstance(data, list):
                task["data"] = data
            usage = item.get("usage")
            if isinstance(usage, dict):
                task["usage"] = usage
            error = _clean(item.get("error"))
            if error:
                task["error"] = error
            progress = _clean(item.get("progress"))
            if progress:
                task["progress"] = progress
            conversation_id = _clean(item.get("conversation_id"))
            if conversation_id:
                task["conversation_id"] = conversation_id
            tasks[_task_key(owner, task_id)] = task
        return tasks

    def _save_locked(self) -> None:
        items = sorted(self._tasks.values(), key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps({"tasks": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    def _recover_unfinished_locked(self) -> bool:
        changed = False
        for task in self._tasks.values():
            if task.get("status") in UNFINISHED_STATUSES:
                task["status"] = TASK_STATUS_ERROR
                task["error"] = "服务已重启，未完成的图片任务已中断"
                task["updated_at"] = _now_iso()
                task["updated_ts"] = time.time()
                changed = True
        return changed

    def _running_timeout_secs(self) -> float:
        try:
            return max(0.01, float(self.running_timeout_getter()))
        except Exception:
            return float(config.image_poll_timeout_secs + RUNNING_TIMEOUT_BUFFER_SECS)

    def _expire_stale_running_locked(self) -> list[tuple[str, int]]:
        timeout_secs = self._running_timeout_secs()
        now = time.time()
        refunds: list[tuple[str, int]] = []
        for task in self._tasks.values():
            if task.get("status") != TASK_STATUS_RUNNING:
                continue
            updated_at = _timestamp(task.get("updated_at")) or _timestamp(task.get("created_at"))
            if not updated_at or now - updated_at <= timeout_secs:
                continue
            task["status"] = TASK_STATUS_ERROR
            task["error"] = f"任务运行超过 {int(timeout_secs)} 秒未返回结果，请重试"
            task["data"] = []
            task["updated_at"] = _now_iso()
            task["updated_ts"] = time.time()
            refunds.append((_clean(task.get("owner_id")), _quota_cost(task.get("quota_cost"))))
        return refunds

    def _cleanup_locked(self) -> bool:
        try:
            retention_days = max(1, int(self.retention_days_getter()))
        except Exception:
            retention_days = 30
        cutoff = time.time() - retention_days * 86400
        removed_keys = [
            key
            for key, task in self._tasks.items()
            if task.get("status") in TERMINAL_STATUSES and _timestamp(task.get("updated_at")) < cutoff
        ]
        for key in removed_keys:
            self._tasks.pop(key, None)
        return bool(removed_keys)

    def resume_poll(
        self,
        identity: dict[str, object],
        task_id: str,
        extra_timeout_secs: float = 30.0,
    ) -> dict[str, Any]:
        """恢复对已超时任务的轮询，额外等待 extra_timeout_secs 秒。"""
        owner = _owner_id(identity)
        key = _task_key(owner, _clean(task_id))
        with self._lock:
            task = self._tasks.get(key)
            if task is None:
                raise ValueError("task not found")
            if task.get("status") != TASK_STATUS_ERROR:
                raise ValueError("task is not in error state")
            error_msg = _clean(task.get("error"))
            if "超时" not in error_msg:
                raise ValueError("task error is not a timeout error")
            conversation_id = _clean(task.get("conversation_id"))
            if not conversation_id:
                raise ValueError("task has no conversation_id")
            mode = task.get("mode", "generate")
            model = task.get("model", "gpt-image-2")
            # 将任务状态重置为 running
            self._update_task(key, status=TASK_STATUS_RUNNING, error="")

        # 启动新线程继续轮询
        thread = threading.Thread(
            target=self._run_resume_poll,
            args=(key, conversation_id, extra_timeout_secs, dict(identity), mode, model),
            name=f"image-resume-{_clean(task_id)[:16]}",
            daemon=True,
        )
        thread.start()
        return _public_task(task)

    def _run_resume_poll(
        self,
        key: str,
        conversation_id: str,
        extra_timeout_secs: float,
        identity: dict[str, object],
        mode: str,
        model: str,
    ) -> None:
        """后台线程：继续轮询已有 conversation_id 的图片结果。"""
        started = time.time()
        try:
            from services.openai_backend_api import OpenAIBackendAPI
            from services.protocol.conversation import format_image_result

            backend = OpenAIBackendAPI()
            file_ids, sediment_ids = backend._poll_image_results(
                conversation_id,
                extra_timeout_secs,
            )
            if not file_ids and not sediment_ids:
                raise RuntimeError(
                    f"继续等待 {extra_timeout_secs} 秒后仍未找到图片结果。"
                )

            image_urls = backend.resolve_conversation_image_urls(
                conversation_id, file_ids, sediment_ids, poll=False,
            )
            if not image_urls:
                raise RuntimeError("图片 URL 解析失败")

            image_items = [
                {"b64_json": __import__("base64").b64encode(image_data).decode("ascii")}
                for image_data in backend.download_image_bytes(image_urls)
            ]
            # 获取 task 的原始 prompt（从 _public_task 的 mode 判断）
            with self._lock:
                task = self._tasks.get(key)
                quality = _clean(task.get("quality"), "auto") if task else "auto"
                size = _clean(task.get("size")) if task else None
            data = format_image_result(
                image_items,
                "",  # prompt 已不重要，结果已经拿到了
                "b64_json",
                "",
                int(time.time()),
            )["data"]
            self._update_task(key, status=TASK_STATUS_SUCCESS, data=data, error="", duration_ms=int((time.time() - started) * 1000))
            self._log_call(
                identity,
                mode,
                model,
                started,
                "调用完成（续轮询）",
                status="success",
                urls=_collect_image_urls(data),
            )
        except Exception as exc:
            error_message = str(exc) or "resume poll failed"
            duration_ms = int((time.time() - started) * 1000)
            self._update_task(key, status=TASK_STATUS_ERROR, error=error_message, data=[], duration_ms=duration_ms)
            self._log_call(
                identity,
                mode,
                model,
                started,
                "调用失败（续轮询）",
                status="failed",
                error=error_message,
            )


image_task_service = ImageTaskService(DATA_DIR / "image_tasks.json")
