from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Callable

from services.config import DATA_DIR

REDEEM_CODE_AMOUNTS = (100, 500, 1000)
REDEEM_CODES_FILE = DATA_DIR / "redeem_codes.json"
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object) -> str:
    return str(value or "").strip()


def _normalize_code(value: object) -> str:
    return "".join(ch for ch in _clean(value).upper() if ch.isalnum())


def _format_code(value: str) -> str:
    compact = _normalize_code(value)
    if compact.startswith("RC"):
        compact = compact[2:]
    groups = [compact[index:index + 4] for index in range(0, len(compact), 4)]
    return "RC-" + "-".join(group for group in groups if group)


def _new_code() -> str:
    compact = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
    return _format_code(compact)


class RedeemCodeService:
    def __init__(self, path: Path = REDEEM_CODES_FILE):
        self.path = path
        self._lock = Lock()

    @staticmethod
    def _public_item(item: dict[str, object]) -> dict[str, object]:
        return {
            "id": item.get("id"),
            "code": item.get("code"),
            "amount": int(item.get("amount") or 0),
            "enabled": bool(item.get("enabled", True)),
            "used": bool(item.get("used_at")),
            "used_by": item.get("used_by") or "",
            "used_by_name": item.get("used_by_name") or "",
            "used_at": item.get("used_at") or None,
            "created_by": item.get("created_by") or "",
            "created_by_name": item.get("created_by_name") or "",
            "created_at": item.get("created_at") or None,
        }

    def _load_locked(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(data, dict):
            data = data.get("items")
        if not isinstance(data, list):
            return []
        items: list[dict[str, object]] = []
        for raw in data:
            if not isinstance(raw, dict):
                continue
            code = _clean(raw.get("code"))
            amount = int(raw.get("amount") or 0)
            if not code or amount not in REDEEM_CODE_AMOUNTS:
                continue
            items.append({
                "id": _clean(raw.get("id")) or uuid.uuid4().hex[:12],
                "code": _format_code(code),
                "amount": amount,
                "enabled": bool(raw.get("enabled", True)),
                "used_by": _clean(raw.get("used_by")),
                "used_by_name": _clean(raw.get("used_by_name")),
                "used_at": _clean(raw.get("used_at")) or None,
                "created_by": _clean(raw.get("created_by")),
                "created_by_name": _clean(raw.get("created_by_name")),
                "created_at": _clean(raw.get("created_at")) or _now_iso(),
            })
        return items

    def _save_locked(self, items: list[dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def list_codes(self) -> list[dict[str, object]]:
        with self._lock:
            items = self._load_locked()
            items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
            return [self._public_item(item) for item in items]

    def create_codes(
        self,
        *,
        amount: int,
        quantity: int,
        created_by: str = "",
        created_by_name: str = "",
    ) -> list[dict[str, object]]:
        normalized_amount = int(amount or 0)
        if normalized_amount not in REDEEM_CODE_AMOUNTS:
            raise ValueError("兑换码额度只能是 100、500 或 1000")
        normalized_quantity = max(1, min(100, int(quantity or 1)))
        with self._lock:
            items = self._load_locked()
            existing = {_normalize_code(item.get("code")) for item in items}
            created: list[dict[str, object]] = []
            for _ in range(normalized_quantity):
                while True:
                    code = _new_code()
                    if _normalize_code(code) not in existing:
                        existing.add(_normalize_code(code))
                        break
                item = {
                    "id": uuid.uuid4().hex[:12],
                    "code": code,
                    "amount": normalized_amount,
                    "enabled": True,
                    "used_by": "",
                    "used_by_name": "",
                    "used_at": None,
                    "created_by": created_by,
                    "created_by_name": created_by_name,
                    "created_at": _now_iso(),
                }
                items.append(item)
                created.append(item)
            self._save_locked(items)
            return [self._public_item(item) for item in created]

    def delete_code(self, code_id: str) -> bool:
        normalized_id = _clean(code_id)
        if not normalized_id:
            return False
        with self._lock:
            items = self._load_locked()
            before = len(items)
            items = [item for item in items if item.get("id") != normalized_id]
            if len(items) == before:
                return False
            self._save_locked(items)
            return True

    def redeem(
        self,
        *,
        code: str,
        user_id: str,
        user_name: str,
        apply_amount: Callable[[int], dict[str, object]],
    ) -> tuple[dict[str, object], dict[str, object]]:
        normalized_code = _normalize_code(code)
        if not normalized_code:
            raise ValueError("请输入兑换码")
        with self._lock:
            items = self._load_locked()
            for index, item in enumerate(items):
                if _normalize_code(item.get("code")) != normalized_code:
                    continue
                if not bool(item.get("enabled", True)):
                    raise ValueError("兑换码已被禁用")
                if item.get("used_at"):
                    raise ValueError("兑换码已被使用")
                amount = int(item.get("amount") or 0)
                if amount not in REDEEM_CODE_AMOUNTS:
                    raise ValueError("兑换码额度异常，请联系管理员")
                identity = apply_amount(amount)
                next_item = dict(item)
                next_item["used_by"] = user_id
                next_item["used_by_name"] = user_name
                next_item["used_at"] = _now_iso()
                items[index] = next_item
                self._save_locked(items)
                return self._public_item(next_item), identity
        raise ValueError("兑换码不存在或已失效")


redeem_code_service = RedeemCodeService()
