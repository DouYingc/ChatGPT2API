from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from services.config import DATA_DIR

QUOTA_LEDGER_FILE = DATA_DIR / "quota_ledger.json"
MAX_LEDGER_ITEMS = 5000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object) -> str:
    return str(value or "").strip()


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class QuotaLedgerService:
    def __init__(self, path: Path = QUOTA_LEDGER_FILE):
        self.path = path
        self._lock = Lock()

    def _load_locked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        normalized: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            item_id = _clean(raw.get("id")) or uuid.uuid4().hex[:12]
            created_at = _clean(raw.get("created_at")) or _now_iso()
            normalized.append({
                "id": item_id,
                "created_at": created_at,
                "user_id": _clean(raw.get("user_id")),
                "user_name": _clean(raw.get("user_name")),
                "role": _clean(raw.get("role")) or "user",
                "kind": _clean(raw.get("kind")) or "image",
                "action": _clean(raw.get("action")),
                "amount": _coerce_int(raw.get("amount")),
                "source": _clean(raw.get("source")),
                "note": _clean(raw.get("note")),
                "remaining": raw.get("remaining") if isinstance(raw.get("remaining"), dict) else {},
                "meta": raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
            })
        return normalized

    def _save_locked(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        next_items = sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:MAX_LEDGER_ITEMS]
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps({"items": next_items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    @staticmethod
    def _public_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "created_at": item.get("created_at"),
            "user_id": item.get("user_id") or "",
            "user_name": item.get("user_name") or "",
            "role": item.get("role") or "user",
            "kind": item.get("kind") or "image",
            "action": item.get("action") or "",
            "amount": _coerce_int(item.get("amount")),
            "source": item.get("source") or "",
            "note": item.get("note") or "",
            "remaining": item.get("remaining") if isinstance(item.get("remaining"), dict) else {},
            "meta": item.get("meta") if isinstance(item.get("meta"), dict) else {},
        }

    def record(
        self,
        *,
        user_id: str,
        user_name: str = "",
        role: str = "user",
        kind: str = "image",
        action: str,
        amount: int,
        source: str = "",
        note: str = "",
        remaining: dict[str, object] | None = None,
        meta: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex[:12],
            "created_at": _now_iso(),
            "user_id": _clean(user_id),
            "user_name": _clean(user_name),
            "role": _clean(role) or "user",
            "kind": _clean(kind) or "image",
            "action": _clean(action),
            "amount": int(amount or 0),
            "source": _clean(source),
            "note": _clean(note),
            "remaining": remaining if isinstance(remaining, dict) else {},
            "meta": meta if isinstance(meta, dict) else {},
        }
        if not item["user_id"] or not item["action"] or item["amount"] == 0:
            return self._public_item(item)
        with self._lock:
            items = self._load_locked()
            items.insert(0, item)
            self._save_locked(items)
        return self._public_item(item)

    def list_entries(self, *, user_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        normalized_user_id = _clean(user_id)
        normalized_limit = max(1, min(1000, _coerce_int(limit, 200)))
        with self._lock:
            items = self._load_locked()
        if normalized_user_id:
            items = [item for item in items if _clean(item.get("user_id")) == normalized_user_id]
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return [self._public_item(item) for item in items[:normalized_limit]]


quota_ledger_service = QuotaLedgerService()
