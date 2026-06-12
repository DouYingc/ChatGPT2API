from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import date, datetime, timezone
from threading import Lock
from typing import Literal

from services.config import DATA_DIR, config
from services.storage.base import StorageBackend

AuthRole = Literal["admin", "user"]
AccountTier = Literal["free", "premium"]
QuotaKind = Literal[
    "image_daily",
    "image_monthly",
    "image_total",
    "chat_daily",
    "chat_monthly",
    "chat_total",
]

# 画图 / 对话各自三档：日、月、总。一次扣费会同时落到这三档；任一档用完都拒绝。
# 总档不参与跨周期重置，日 / 月 在跨自然日 / 月时把 used 清零。
_IMAGE_KINDS: tuple[QuotaKind, ...] = ("image_daily", "image_monthly", "image_total")
_CHAT_KINDS: tuple[QuotaKind, ...] = ("chat_daily", "chat_monthly", "chat_total")
_PERIODIC_KINDS: tuple[QuotaKind, ...] = (
    "image_daily",
    "image_monthly",
    "chat_daily",
    "chat_monthly",
)
_PASSWORD_ALGORITHM = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 260_000
_USERNAME_ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-@")
DEFAULT_REGISTER_QUOTAS = {
    "image_daily_quota": 0,
    "image_daily_unlimited": True,
    "image_monthly_quota": 0,
    "image_monthly_unlimited": True,
    "image_total_quota": 100,
    "image_total_unlimited": False,
    "chat_daily_quota": 0,
    "chat_daily_unlimited": True,
    "chat_monthly_quota": 0,
    "chat_monthly_unlimited": True,
    "chat_total_quota": 0,
    "chat_total_unlimited": True,
}


class AuthAccountDisabledError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_password(value: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        salt.encode("ascii"),
        _PASSWORD_ITERATIONS,
    ).hex()
    return f"{_PASSWORD_ALGORITHM}${_PASSWORD_ITERATIONS}${salt}${digest}"


def _verify_password(value: str, encoded: str) -> bool:
    try:
        algorithm, iterations_raw, salt, digest = str(encoded or "").split("$", 3)
        iterations = int(iterations_raw)
    except (TypeError, ValueError):
        return False
    if algorithm != _PASSWORD_ALGORITHM or iterations <= 0 or not salt or not digest:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        salt.encode("ascii"),
        iterations,
    ).hex()
    return hmac.compare_digest(candidate, digest)


def _today_key() -> str:
    """服务器本地时区自然日，用于日额度跨天判断。"""
    return date.today().isoformat()


def _this_month_key() -> str:
    """服务器本地时区自然月，用于月额度跨月判断。"""
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def _is_daily_kind(kind: QuotaKind) -> bool:
    return kind.endswith("_daily")


def _is_monthly_kind(kind: QuotaKind) -> bool:
    return kind.endswith("_monthly")


class AuthService:
    def __init__(self, storage: StorageBackend):
        self.storage = storage
        self._lock = Lock()
        self._items = self._load()
        self._last_used_flush_at: dict[str, datetime] = {}

    @staticmethod
    def _clean(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _default_name(role: object) -> str:
        return "管理员密钥" if str(role or "").strip().lower() == "admin" else "普通用户"

    @staticmethod
    def _coerce_int(value: object, default: int = 0) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_bool(value: object, default: bool = False) -> bool:
        if value is None:
            return default
        return bool(value)

    @classmethod
    def _has_redeemed_code(cls, user_id: object) -> bool:
        normalized_id = cls._clean(user_id)
        if not normalized_id:
            return False
        path = DATA_DIR / "redeem_codes.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict):
                continue
            if cls._clean(item.get("used_by")) == normalized_id and cls._clean(item.get("used_at")):
                return True
        return False

    @classmethod
    def _normalize_account_tier(cls, value: object, *, role: object = "user") -> AccountTier:
        if str(role or "").strip().lower() == "admin":
            return "premium"
        raw = cls._clean(value).lower().replace("-", "_").replace(" ", "_")
        compact = raw.replace("_", "")
        if compact in {"premium", "advanced", "paid", "plus", "pro", "team", "enterprise", "vip", "high"}:
            return "premium"
        return "free"

    @classmethod
    def _can_use_paid_image_accounts(cls, item: dict[str, object]) -> bool:
        role = cls._clean(item.get("role")).lower()
        return role == "admin" or cls._normalize_account_tier(item.get("account_tier"), role=role) == "premium"

    @classmethod
    def _can_use_high_resolution(cls, item: dict[str, object]) -> bool:
        role = cls._clean(item.get("role")).lower()
        return role == "admin" or cls._can_use_paid_image_accounts(item) or bool(item.get("high_resolution_enabled"))

    def _normalize_item(self, raw: object) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        role = self._clean(raw.get("role")).lower()
        if role not in {"admin", "user"}:
            return None
        key_hash = self._clean(raw.get("key_hash"))
        if not key_hash:
            return None
        item_id = self._clean(raw.get("id")) or uuid.uuid4().hex[:12]
        name = self._clean(raw.get("name")) or self._default_name(role)
        username = self._clean(raw.get("username")) if role == "user" else ""
        password_hash = self._clean(raw.get("password_hash")) if role == "user" else ""
        created_at = self._clean(raw.get("created_at")) or _now_iso()
        last_used_at = self._clean(raw.get("last_used_at")) or None
        # 仅 user 角色保留明文，给 admin 后台"查看 / 复制密钥"用；admin 角色靠 config.auth_key 鉴权，
        # 不应再额外落明文，统一过滤掉。
        key_plain = self._clean(raw.get("key")) if role == "user" else ""
        account_tier = self._normalize_account_tier(
            raw.get("account_tier", raw.get("image_account_tier")),
            role=role,
        )
        if role == "user":
            high_resolution_enabled = (
                self._coerce_bool(raw.get("high_resolution_enabled"), False)
                if "high_resolution_enabled" in raw
                else self._has_redeemed_code(item_id)
            )
        else:
            high_resolution_enabled = True

        # 画图三档迁移规则：
        #   - 已经有 image_total_quota 字段：当前格式，原样读取。
        #   - 否则 image_quota / quota（旧一次性总额度）→ image_total_quota，日 / 月默认不限额。
        #   - 三档默认不限的存量用户继续保持对话能力（同对话三档迁移逻辑）。
        legacy_total = raw.get("image_total_quota") is None
        if legacy_total:
            legacy_image_quota = self._coerce_int(raw.get("image_quota", raw.get("quota")), 0)
            legacy_image_used = self._coerce_int(raw.get("image_used", raw.get("used")), 0)
            legacy_image_unlimited = self._coerce_bool(
                raw.get("image_unlimited", raw.get("unlimited")), False
            )
            image_total_quota = legacy_image_quota
            image_total_used = legacy_image_used
            image_total_unlimited = legacy_image_unlimited
        else:
            image_total_quota = self._coerce_int(raw.get("image_total_quota"), 0)
            image_total_used = self._coerce_int(raw.get("image_total_used"), 0)
            image_total_unlimited = self._coerce_bool(raw.get("image_total_unlimited"), False)

        image_daily_quota = self._coerce_int(raw.get("image_daily_quota"), 0)
        image_daily_used = self._coerce_int(raw.get("image_daily_used"), 0)
        image_daily_unlimited = self._coerce_bool(
            raw.get("image_daily_unlimited"), default="image_daily_quota" not in raw
        )
        image_daily_reset_at = self._clean(raw.get("image_daily_reset_at")) or _today_key()
        image_monthly_quota = self._coerce_int(raw.get("image_monthly_quota"), 0)
        image_monthly_used = self._coerce_int(raw.get("image_monthly_used"), 0)
        image_monthly_unlimited = self._coerce_bool(
            raw.get("image_monthly_unlimited"), default="image_monthly_quota" not in raw
        )
        image_monthly_reset_at = self._clean(raw.get("image_monthly_reset_at")) or _this_month_key()

        chat_daily_quota = self._coerce_int(raw.get("chat_daily_quota"), 0)
        chat_daily_used = self._coerce_int(raw.get("chat_daily_used"), 0)
        chat_daily_unlimited = self._coerce_bool(
            raw.get("chat_daily_unlimited"), default="chat_daily_quota" not in raw
        )
        chat_daily_reset_at = self._clean(raw.get("chat_daily_reset_at")) or _today_key()
        chat_monthly_quota = self._coerce_int(raw.get("chat_monthly_quota"), 0)
        chat_monthly_used = self._coerce_int(raw.get("chat_monthly_used"), 0)
        chat_monthly_unlimited = self._coerce_bool(
            raw.get("chat_monthly_unlimited"), default="chat_monthly_quota" not in raw
        )
        chat_monthly_reset_at = self._clean(raw.get("chat_monthly_reset_at")) or _this_month_key()
        chat_total_quota = self._coerce_int(raw.get("chat_total_quota"), 0)
        chat_total_used = self._coerce_int(raw.get("chat_total_used"), 0)
        chat_total_unlimited = self._coerce_bool(
            raw.get("chat_total_unlimited"), default="chat_total_quota" not in raw
        )

        # admin 永远六档全开，所有计数清零，挡掉脏数据。
        if role == "admin":
            image_daily_quota = image_daily_used = 0
            image_monthly_quota = image_monthly_used = 0
            image_total_quota = image_total_used = 0
            chat_daily_quota = chat_daily_used = 0
            chat_monthly_quota = chat_monthly_used = 0
            chat_total_quota = chat_total_used = 0
            image_daily_unlimited = True
            image_monthly_unlimited = True
            image_total_unlimited = True
            chat_daily_unlimited = True
            chat_monthly_unlimited = True
            chat_total_unlimited = True
            high_resolution_enabled = True

        return {
            "id": item_id,
            "name": name,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "key_hash": key_hash,
            "key": key_plain,
            "account_tier": account_tier,
            "high_resolution_enabled": high_resolution_enabled,
            "enabled": bool(raw.get("enabled", True)),
            "created_at": created_at,
            "last_used_at": last_used_at,
            "image_daily_quota": image_daily_quota,
            "image_daily_used": image_daily_used,
            "image_daily_unlimited": image_daily_unlimited,
            "image_daily_reset_at": image_daily_reset_at,
            "image_monthly_quota": image_monthly_quota,
            "image_monthly_used": image_monthly_used,
            "image_monthly_unlimited": image_monthly_unlimited,
            "image_monthly_reset_at": image_monthly_reset_at,
            "image_total_quota": image_total_quota,
            "image_total_used": image_total_used,
            "image_total_unlimited": image_total_unlimited,
            "chat_daily_quota": chat_daily_quota,
            "chat_daily_used": chat_daily_used,
            "chat_daily_unlimited": chat_daily_unlimited,
            "chat_daily_reset_at": chat_daily_reset_at,
            "chat_monthly_quota": chat_monthly_quota,
            "chat_monthly_used": chat_monthly_used,
            "chat_monthly_unlimited": chat_monthly_unlimited,
            "chat_monthly_reset_at": chat_monthly_reset_at,
            "chat_total_quota": chat_total_quota,
            "chat_total_used": chat_total_used,
            "chat_total_unlimited": chat_total_unlimited,
        }

    @staticmethod
    def _apply_period_reset(item: dict[str, object]) -> bool:
        """跨过自然日/月就把对应 used 清零；返回是否改动了 item。
        总额度不重置。同时覆盖画图与对话两侧的日 / 月。"""
        changed = False
        today_key = _today_key()
        month_key = _this_month_key()
        for kind in _PERIODIC_KINDS:
            target_key = today_key if _is_daily_kind(kind) else month_key
            if item.get(f"{kind}_reset_at") != target_key:
                item[f"{kind}_used"] = 0
                item[f"{kind}_reset_at"] = target_key
                changed = True
        return changed

    def _load(self) -> list[dict[str, object]]:
        try:
            items = self.storage.load_auth_keys()
        except Exception:
            return []
        if not isinstance(items, list):
            return []
        return [normalized for item in items if (normalized := self._normalize_item(item)) is not None]

    def _save(self) -> None:
        self.storage.save_auth_keys(self._items)

    def _reload_locked(self) -> None:
        self._items = self._load()

    @staticmethod
    def _remaining(quota: int, used: int, unlimited: bool) -> int | None:
        if unlimited:
            return None
        return max(0, quota - used)

    @classmethod
    def _public_item(cls, item: dict[str, object]) -> dict[str, object]:
        result: dict[str, object] = {
            "id": item.get("id"),
            "name": item.get("name"),
            "username": item.get("username") or "",
            "has_password": bool(cls._clean(item.get("password_hash"))),
            "role": item.get("role"),
            "enabled": bool(item.get("enabled", True)),
            "created_at": item.get("created_at"),
            "last_used_at": item.get("last_used_at"),
            "account_tier": cls._normalize_account_tier(item.get("account_tier"), role=item.get("role")),
            "can_use_paid_image_accounts": cls._can_use_paid_image_accounts(item),
            "can_use_high_resolution": cls._can_use_high_resolution(item),
            # 仅暴露"是否可被 admin 回显"，原文要走专门的 get_raw_key 单独取。
            "key_visible": bool(item.get("role") == "user" and cls._clean(item.get("key"))),
        }
        for kind in (*_IMAGE_KINDS, *_CHAT_KINDS):
            quota = cls._coerce_int(item.get(f"{kind}_quota"), 0)
            used = cls._coerce_int(item.get(f"{kind}_used"), 0)
            unlimited = bool(item.get(f"{kind}_unlimited", False))
            result[f"{kind}_quota"] = quota
            result[f"{kind}_used"] = used
            result[f"{kind}_unlimited"] = unlimited
            result[f"{kind}_remaining"] = cls._remaining(quota, used, unlimited)
        return result

    @staticmethod
    def _record_quota_ledger(
        item: dict[str, object],
        *,
        kind: str,
        action: str,
        amount: int,
        source: str,
        note: str = "",
        remaining: dict[str, object] | None = None,
    ) -> None:
        try:
            from services.quota_ledger_service import quota_ledger_service
            quota_ledger_service.record(
                user_id=str(item.get("id") or ""),
                user_name=str(item.get("name") or item.get("username") or ""),
                role=str(item.get("role") or "user"),
                kind=kind,
                action=action,
                amount=amount,
                source=source,
                note=note,
                remaining=remaining or {},
            )
        except Exception:
            pass

    def list_keys(self, role: AuthRole | None = None) -> list[dict[str, object]]:
        with self._lock:
            self._reload_locked()
            # 列表读取时也跑一次跨周期清零，避免前端展示陈旧的 daily_used。
            dirty = False
            for item in self._items:
                if str(item.get("role") or "").strip().lower() == "admin":
                    continue
                if self._apply_period_reset(item):
                    dirty = True
            if dirty:
                try:
                    self._save()
                except Exception:
                    pass
            items = [item for item in self._items if role is None or item.get("role") == role]
            return [self._public_item(item) for item in items]

    def _has_key_hash_locked(self, key_hash: str, *, exclude_id: str = "") -> bool:
        for item in self._items:
            item_id = self._clean(item.get("id"))
            if exclude_id and item_id == exclude_id:
                continue
            stored_hash = self._clean(item.get("key_hash"))
            if stored_hash and hmac.compare_digest(stored_hash, key_hash):
                return True
        return False

    def _build_key_hash_locked(self, raw_key: str, *, exclude_id: str = "") -> str:
        candidate = self._clean(raw_key)
        if not candidate:
            raise ValueError("请输入新的专用密钥")
        admin_key = self._clean(config.auth_key)
        if admin_key and hmac.compare_digest(candidate, admin_key):
            raise ValueError("这个密钥和管理员密钥冲突了，请换一个新的密钥")
        key_hash = _hash_key(candidate)
        if self._has_key_hash_locked(key_hash, exclude_id=exclude_id):
            raise ValueError("这个专用密钥已经存在，请换一个新的密钥")
        return key_hash

    def _has_name_locked(self, name: str, *, role: AuthRole | None = None, exclude_id: str = "") -> bool:
        candidate = self._clean(name)
        if not candidate:
            return False
        for item in self._items:
            item_id = self._clean(item.get("id"))
            if exclude_id and item_id == exclude_id:
                continue
            if role is not None and item.get("role") != role:
                continue
            if self._clean(item.get("name")) == candidate:
                return True
        return False

    @classmethod
    def _normalize_username_value(cls, username: str) -> str:
        return cls._clean(username).lower()

    @classmethod
    def _validate_username(cls, username: str, *, required: bool = False) -> str:
        candidate = cls._clean(username)
        if not candidate:
            if required:
                raise ValueError("请输入用户名")
            return ""
        if len(candidate) < 3 or len(candidate) > 64:
            raise ValueError("用户名长度需要在 3 到 64 个字符之间")
        if any(ch not in _USERNAME_ALLOWED_CHARS for ch in candidate):
            raise ValueError("用户名只能包含字母、数字、点、下划线、短横线和 @")
        return candidate

    @classmethod
    def _validate_password(cls, password: str) -> str:
        candidate = str(password or "")
        if len(candidate) < 6:
            raise ValueError("密码至少需要 6 个字符")
        if len(candidate) > 128:
            raise ValueError("密码不能超过 128 个字符")
        return candidate

    def _has_username_locked(self, username: str, *, exclude_id: str = "") -> bool:
        candidate = self._normalize_username_value(username)
        if not candidate:
            return False
        for item in self._items:
            item_id = self._clean(item.get("id"))
            if exclude_id and item_id == exclude_id:
                continue
            if self._normalize_username_value(str(item.get("username") or "")) == candidate:
                return True
        return False

    def _build_username_locked(self, username: str, *, exclude_id: str = "", required: bool = False) -> str:
        candidate = self._validate_username(username, required=required)
        if not candidate:
            return ""
        if self._has_username_locked(candidate, exclude_id=exclude_id):
            raise ValueError("这个用户名已经被注册了，请换一个")
        return candidate

    def _build_default_name_locked(self, role: AuthRole, *, exclude_id: str = "") -> str:
        base_name = self._default_name(role)
        if not self._has_name_locked(base_name, role=role, exclude_id=exclude_id):
            return base_name
        suffix = 2
        while True:
            candidate = f"{base_name} {suffix}"
            if not self._has_name_locked(candidate, role=role, exclude_id=exclude_id):
                return candidate
            suffix += 1

    def _build_name_locked(self, name: str, *, role: AuthRole, exclude_id: str = "") -> str:
        candidate = self._clean(name)
        if not candidate:
            return self._build_default_name_locked(role, exclude_id=exclude_id)
        if self._has_name_locked(candidate, role=role, exclude_id=exclude_id):
            raise ValueError("这个名称已经在使用中了，换一个更容易区分的名称吧")
        return candidate

    @classmethod
    def _validate_quota_hierarchy(cls, item: dict[str, object]) -> None:
        """同一业务内，短周期限额不能大于长周期限额。

        unlimited 表示该档不参与上限约束；例如总额度不限时，月额度可以任意设置。
        但如果月和总都有限，月额度大于总额度没有意义，也会让前端/用户理解混乱。
        """

        def check(
            smaller_kind: QuotaKind,
            larger_kind: QuotaKind,
            smaller_label: str,
            larger_label: str,
        ) -> None:
            if bool(item.get(f"{smaller_kind}_unlimited", False)):
                return
            if bool(item.get(f"{larger_kind}_unlimited", False)):
                return
            smaller_quota = cls._coerce_int(item.get(f"{smaller_kind}_quota"), 0)
            larger_quota = cls._coerce_int(item.get(f"{larger_kind}_quota"), 0)
            if smaller_quota > larger_quota:
                raise ValueError(f"{smaller_label}不能大于{larger_label}")

        check("image_daily", "image_monthly", "画图日限额", "画图月限额")
        check("image_daily", "image_total", "画图日限额", "画图总额度")
        check("image_monthly", "image_total", "画图月限额", "画图总额度")
        check("chat_daily", "chat_monthly", "对话日限额", "对话月限额")
        check("chat_daily", "chat_total", "对话日限额", "对话总额度")
        check("chat_monthly", "chat_total", "对话月限额", "对话总额度")

    def create_key(
        self,
        *,
        role: AuthRole,
        name: str = "",
        key: str = "",
        image_daily_quota: int = 0,
        image_daily_unlimited: bool = True,
        image_monthly_quota: int = 0,
        image_monthly_unlimited: bool = True,
        image_total_quota: int = 0,
        image_total_unlimited: bool = False,
        chat_daily_quota: int = 0,
        chat_daily_unlimited: bool = True,
        chat_monthly_quota: int = 0,
        chat_monthly_unlimited: bool = True,
        chat_total_quota: int = 0,
        chat_total_unlimited: bool = True,
        account_tier: AccountTier | str = "free",
        username: str = "",
        password: str = "",
    ) -> tuple[dict[str, object], str]:
        with self._lock:
            self._reload_locked()
            normalized_name = self._build_name_locked(name, role=role)
            normalized_username = self._build_username_locked(username) if role == "user" else ""
            password_hash = ""
            if password:
                if not normalized_username:
                    raise ValueError("设置密码前需要先填写用户名")
                password_hash = _hash_password(self._validate_password(password))
            custom_key = self._clean(key)
            if custom_key:
                # 自定义密钥走和"编辑里换 key"同一套校验：非空、不与管理员密钥冲突、不与其他用户重复。
                key_hash = self._build_key_hash_locked(custom_key)
                raw_key = custom_key
            else:
                while True:
                    raw_key = f"sk-{secrets.token_urlsafe(24)}"
                    try:
                        key_hash = self._build_key_hash_locked(raw_key)
                        break
                    except ValueError:
                        continue
            is_admin = role == "admin"
            item = {
                "id": uuid.uuid4().hex[:12],
                "name": normalized_name,
                "username": normalized_username,
                "password_hash": password_hash,
                "role": role,
                "key_hash": key_hash,
                # admin 不落明文：admin 鉴权走 config.auth_key，不通过 auth_keys.json。
                "key": "" if is_admin else raw_key,
                "account_tier": self._normalize_account_tier(account_tier, role=role),
                "high_resolution_enabled": True if is_admin else False,
                "enabled": True,
                "created_at": _now_iso(),
                "last_used_at": None,
                "image_daily_quota": 0 if is_admin else self._coerce_int(image_daily_quota, 0),
                "image_daily_used": 0,
                "image_daily_unlimited": True if is_admin else bool(image_daily_unlimited),
                "image_daily_reset_at": _today_key(),
                "image_monthly_quota": 0 if is_admin else self._coerce_int(image_monthly_quota, 0),
                "image_monthly_used": 0,
                "image_monthly_unlimited": True if is_admin else bool(image_monthly_unlimited),
                "image_monthly_reset_at": _this_month_key(),
                "image_total_quota": 0 if is_admin else self._coerce_int(image_total_quota, 0),
                "image_total_used": 0,
                "image_total_unlimited": True if is_admin else bool(image_total_unlimited),
                "chat_daily_quota": 0 if is_admin else self._coerce_int(chat_daily_quota, 0),
                "chat_daily_used": 0,
                "chat_daily_unlimited": True if is_admin else bool(chat_daily_unlimited),
                "chat_daily_reset_at": _today_key(),
                "chat_monthly_quota": 0 if is_admin else self._coerce_int(chat_monthly_quota, 0),
                "chat_monthly_used": 0,
                "chat_monthly_unlimited": True if is_admin else bool(chat_monthly_unlimited),
                "chat_monthly_reset_at": _this_month_key(),
                "chat_total_quota": 0 if is_admin else self._coerce_int(chat_total_quota, 0),
                "chat_total_used": 0,
                "chat_total_unlimited": True if is_admin else bool(chat_total_unlimited),
            }
            if not is_admin:
                self._validate_quota_hierarchy(item)
            self._items.append(item)
            self._save()
            return self._public_item(item), raw_key

    def update_key(
        self,
        key_id: str,
        updates: dict[str, object],
        *,
        role: AuthRole | None = None,
    ) -> dict[str, object] | None:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                if role is not None and item.get("role") != role:
                    return None
                next_item = dict(item)
                next_role = "admin" if str(next_item.get("role") or "").strip().lower() == "admin" else "user"
                if "name" in updates and updates.get("name") is not None:
                    next_item["name"] = self._build_name_locked(
                        str(updates.get("name") or ""),
                        role=next_role,
                        exclude_id=normalized_id,
                    )
                if "username" in updates and updates.get("username") is not None:
                    next_username = self._build_username_locked(
                        str(updates.get("username") or ""),
                        exclude_id=normalized_id,
                    )
                    next_item["username"] = next_username
                    if not next_username:
                        next_item["password_hash"] = ""
                if "password" in updates and updates.get("password") is not None:
                    password = self._validate_password(str(updates.get("password") or ""))
                    if not self._clean(next_item.get("username")):
                        raise ValueError("设置密码前需要先填写用户名")
                    next_item["password_hash"] = _hash_password(password)
                if "enabled" in updates and updates.get("enabled") is not None:
                    next_item["enabled"] = bool(updates.get("enabled"))
                if "key" in updates and updates.get("key") is not None:
                    raw_candidate = self._clean(str(updates.get("key") or ""))
                    next_item["key_hash"] = self._build_key_hash_locked(raw_candidate, exclude_id=normalized_id)
                    next_item["key"] = "" if next_role == "admin" else raw_candidate
                if next_role == "user":
                    if "account_tier" in updates and updates.get("account_tier") is not None:
                        next_item["account_tier"] = self._normalize_account_tier(
                            updates.get("account_tier"),
                            role=next_role,
                        )
                    should_validate_quota = self._has_quota_config_updates(updates)
                    self._apply_quota_updates_locked(next_item, updates)
                    if should_validate_quota:
                        self._validate_quota_hierarchy(next_item)
                else:
                    # admin 强制全档不限额，相关计数永远清零，挡掉外部恶意写入。
                    for kind in (*_IMAGE_KINDS, *_CHAT_KINDS):
                        next_item[f"{kind}_quota"] = 0
                        next_item[f"{kind}_used"] = 0
                        next_item[f"{kind}_unlimited"] = True
                    next_item["account_tier"] = "premium"
                self._items[index] = next_item
                self._save()
                return self._public_item(next_item)
        return None

    @classmethod
    def _apply_quota_updates_locked(cls, target: dict[str, object], updates: dict[str, object]) -> None:
        """把 update_key 传入的额度相关字段写到 target，保持 admin 路径不受影响。
        每档 quota 与 unlimited 都按字面值透传；reset_<kind>_used 把对应 used 归零并刷新 reset_at。
        旧 reset_used 等价于 reset_image_total_used，避免老 admin 客户端发布期间报错。
        """
        for kind in (*_IMAGE_KINDS, *_CHAT_KINDS):
            quota_key = f"{kind}_quota"
            unlimited_key = f"{kind}_unlimited"
            if quota_key in updates and updates.get(quota_key) is not None:
                target[quota_key] = cls._coerce_int(updates.get(quota_key), 0)
            if unlimited_key in updates and updates.get(unlimited_key) is not None:
                target[unlimited_key] = bool(updates.get(unlimited_key))
            reset_key = f"reset_{kind}_used"
            if updates.get(reset_key):
                target[f"{kind}_used"] = 0
                if _is_daily_kind(kind):
                    target[f"{kind}_reset_at"] = _today_key()
                elif _is_monthly_kind(kind):
                    target[f"{kind}_reset_at"] = _this_month_key()
        if updates.get("reset_used"):
            # 老前端协议；映射到画图总额度计数。
            target["image_total_used"] = 0

    @staticmethod
    def _has_quota_config_updates(updates: dict[str, object]) -> bool:
        for kind in (*_IMAGE_KINDS, *_CHAT_KINDS):
            if f"{kind}_quota" in updates or f"{kind}_unlimited" in updates:
                return True
        return False

    def get_by_id(self, key_id: str) -> dict[str, object] | None:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        with self._lock:
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                # 读取单条时也跑一次跨周期清零，让前端拉自己 identity 时看到的是当下的余额。
                next_item = dict(item)
                if self._apply_period_reset(next_item):
                    self._items[index] = next_item
                    try:
                        self._save()
                    except Exception:
                        pass
                return self._public_item(next_item)
        return None

    def add_image_total_quota(self, key_id: str, amount: int) -> dict[str, object]:
        normalized_id = self._clean(key_id)
        delta = self._coerce_int(amount, 0)
        if not normalized_id:
            raise ValueError("用户不存在")
        if delta <= 0:
            raise ValueError("兑换额度必须大于 0")
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                if str(item.get("role") or "").strip().lower() != "user":
                    raise ValueError("只有普通用户可以兑换额度")
                if not bool(item.get("enabled", True)):
                    raise ValueError("该账号已被禁用，请联系管理员")
                if bool(item.get("image_total_unlimited", False)):
                    raise ValueError("当前账号画图总额度不限，无需兑换")
                next_item = dict(item)
                next_item["image_total_quota"] = self._coerce_int(next_item.get("image_total_quota"), 0) + delta
                next_item["high_resolution_enabled"] = True
                self._items[index] = next_item
                self._save()
                return self._public_item(next_item)
        raise ValueError("用户不存在")

    def _consume_kinds_locked(
        self,
        key_id: str,
        amount: int,
        kinds: tuple[QuotaKind, ...],
        block_label_map: dict[str, str],
    ) -> dict[str, object]:
        """在已持锁场景下扣减一组 kinds（任一档不足都拒绝）。
        管理员直接放行；返回结构对齐画图 / 对话两侧的语义。"""
        delta = max(0, int(amount or 0))
        if not key_id or delta == 0:
            return {"ok": True, "remaining": None, "unlimited": True, "reason": ""}
        for index, item in enumerate(self._items):
            if item.get("id") != key_id:
                continue
            role = str(item.get("role") or "").strip().lower()
            if role == "admin":
                return {"ok": True, "remaining": None, "unlimited": True, "reason": ""}
            next_item = dict(item)
            self._apply_period_reset(next_item)
            blocked: list[str] = []
            snapshots: list[tuple[QuotaKind, int, int, bool]] = []
            for kind in kinds:
                quota = self._coerce_int(next_item.get(f"{kind}_quota"), 0)
                used = self._coerce_int(next_item.get(f"{kind}_used"), 0)
                unlimited = bool(next_item.get(f"{kind}_unlimited", False))
                snapshots.append((kind, quota, used, unlimited))
                # unlimited 只解除 quota 上限校验；used 仍照常累加，
                # 让管理员后续切换到限额时不会丢失"日 ⊂ 月 ⊂ 总"的历史使用数据。
                if unlimited:
                    continue
                if max(0, quota - used) < delta:
                    blocked.append(kind)
            if blocked:
                return {
                    "ok": False,
                    "blocked": blocked,
                    "unlimited": False,
                    "reason": _block_reason(blocked, block_label_map),
                    # 老协议字段：画图侧入口处会读 remaining 决定 toast 文案。
                    "remaining": _remaining_snapshot(next_item, kinds),
                }
            # 通过校验：所有档位（含 unlimited）都把本次 delta 累加进 used，
            # 这样日 / 月 / 总的 used 才能保持"包含关系"，不会因为某档不限就漏记。
            for kind, quota, used, unlimited in snapshots:
                next_item[f"{kind}_used"] = used + delta
            self._items[index] = next_item
            try:
                self._save()
            except Exception:
                self._items[index] = item
                raise
            ledger_kind = "image" if kinds == _IMAGE_KINDS else "chat"
            self._record_quota_ledger(
                next_item,
                kind=ledger_kind,
                action=f"{ledger_kind}_consume",
                amount=-delta,
                source="生图扣费" if ledger_kind == "image" else "对话扣费",
                note=f"扣除 {delta} 额度",
                remaining=_remaining_snapshot(next_item, kinds),
            )
            return {
                "ok": True,
                "unlimited": False,
                "reason": "",
                "remaining": _remaining_snapshot(next_item, kinds),
            }
        return {"ok": False, "remaining": 0, "unlimited": False, "reason": "密钥不存在"}

    def _refund_kinds_locked(
        self,
        key_id: str,
        amount: int,
        kinds: tuple[QuotaKind, ...],
    ) -> dict[str, object]:
        delta = max(0, int(amount or 0))
        if not key_id or delta == 0:
            return {"ok": True, "remaining": None, "unlimited": True, "reason": ""}
        for index, item in enumerate(self._items):
            if item.get("id") != key_id:
                continue
            role = str(item.get("role") or "").strip().lower()
            if role == "admin":
                return {"ok": True, "remaining": None, "unlimited": True, "reason": ""}
            next_item = dict(item)
            self._apply_period_reset(next_item)
            changed = False
            for kind in kinds:
                # 与 _consume_kinds_locked 对称：unlimited 档当时也累加了 used，
                # 退款也得对称还回来，否则 used 计数会单调上涨。
                used = self._coerce_int(next_item.get(f"{kind}_used"), 0)
                if used <= 0:
                    continue
                next_item[f"{kind}_used"] = max(0, used - delta)
                changed = True
            if not changed:
                return {"ok": True, "unlimited": False, "reason": "", "remaining": _remaining_snapshot(next_item, kinds)}
            self._items[index] = next_item
            try:
                self._save()
            except Exception:
                self._items[index] = item
                raise
            ledger_kind = "image" if kinds == _IMAGE_KINDS else "chat"
            self._record_quota_ledger(
                next_item,
                kind=ledger_kind,
                action=f"{ledger_kind}_refund",
                amount=delta,
                source="失败返还" if ledger_kind == "image" else "对话返还",
                note=f"返还 {delta} 额度",
                remaining=_remaining_snapshot(next_item, kinds),
            )
            return {
                "ok": True,
                "unlimited": False,
                "reason": "",
                "remaining": _remaining_snapshot(next_item, kinds),
            }
        return {"ok": False, "remaining": 0, "unlimited": False, "reason": "密钥不存在"}

    def consume_image_quota(self, key_id: str, amount: int) -> dict[str, object]:
        """扣减用户密钥的画图额度（日 / 月 / 总同时扣）。
        admin 全放行；任一档剩余不够直接拒绝（API 层据此返 402）。"""
        normalized_id = self._clean(key_id)
        with self._lock:
            return self._consume_kinds_locked(normalized_id, amount, _IMAGE_KINDS, _IMAGE_KIND_LABEL)

    def refund_image_quota(self, key_id: str, amount: int) -> dict[str, object]:
        """画图上游真失败时对画图三档同时退款。"""
        normalized_id = self._clean(key_id)
        with self._lock:
            return self._refund_kinds_locked(normalized_id, amount, _IMAGE_KINDS)

    # 兼容旧调用名（image_task_service / 其他模块直接 import 用过的）。
    consume_quota = consume_image_quota
    refund_quota = refund_image_quota

    def consume_chat_quota(self, key_id: str, amount: int = 1) -> dict[str, object]:
        """扣减用户密钥的对话额度（日 / 月 / 总同时扣）。"""
        normalized_id = self._clean(key_id)
        with self._lock:
            return self._consume_kinds_locked(normalized_id, amount, _CHAT_KINDS, _CHAT_KIND_LABEL)

    def refund_chat_quota(self, key_id: str, amount: int = 1) -> dict[str, object]:
        normalized_id = self._clean(key_id)
        with self._lock:
            return self._refund_kinds_locked(normalized_id, amount, _CHAT_KINDS)

    def reveal_key(self, key_id: str, *, role: AuthRole | None = None) -> dict[str, object] | None:
        """给 admin 后台读取明文密钥；只对 user 角色有效。
        返回 {"key": str, "key_visible": bool}：旧数据未落明文时 key_visible=False，
        前端据此提示 admin 走"重置密钥"流程。"""
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        with self._lock:
            self._reload_locked()
            for item in self._items:
                if item.get("id") != normalized_id:
                    continue
                if role is not None and item.get("role") != role:
                    return None
                if str(item.get("role") or "").strip().lower() != "user":
                    return None
                plain = self._clean(item.get("key"))
                return {"key": plain, "key_visible": bool(plain)}
        return None

    def regenerate_key(self, key_id: str, *, role: AuthRole | None = None, key: str = "") -> tuple[dict[str, object], str] | None:
        """给老数据"重置后回显"用：换新密钥（落明文 + 哈希），旧密钥立即失效。
        admin 角色不允许走这条路径。传入 key 则使用自定义值，否则自动生成。"""
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                if role is not None and item.get("role") != role:
                    return None
                if str(item.get("role") or "").strip().lower() != "user":
                    return None
                custom_key = self._clean(key)
                if custom_key:
                    key_hash = self._build_key_hash_locked(custom_key, exclude_id=normalized_id)
                    raw_key = custom_key
                else:
                    while True:
                        raw_key = f"sk-{secrets.token_urlsafe(24)}"
                        try:
                            key_hash = self._build_key_hash_locked(raw_key, exclude_id=normalized_id)
                            break
                        except ValueError:
                            continue
                next_item = dict(item)
                next_item["key_hash"] = key_hash
                next_item["key"] = raw_key
                self._items[index] = next_item
                self._save()
                return self._public_item(next_item), raw_key
        return None

    def register_user(self, *, username: str, password: str) -> tuple[dict[str, object], str]:
        normalized_username = self._validate_username(username, required=True)
        normalized_password = self._validate_password(password)
        register_defaults = dict(DEFAULT_REGISTER_QUOTAS)
        register_defaults.update(config.register_defaults)
        return self.create_key(
            role="user",
            name=normalized_username,
            username=normalized_username,
            password=normalized_password,
            account_tier="free",
            **register_defaults,
        )

    def change_password(self, key_id: str, current_password: str, new_password: str) -> dict[str, object] | None:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        current_candidate = str(current_password or "")
        next_candidate = self._validate_password(new_password)
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                if str(item.get("role") or "").strip().lower() != "user":
                    raise ValueError("只有普通用户账号可以修改密码")
                if not bool(item.get("enabled", True)):
                    raise AuthAccountDisabledError("该账号已被禁用，请联系管理员")
                password_hash = self._clean(item.get("password_hash"))
                if not password_hash:
                    raise ValueError("当前账号暂未设置密码，请联系管理员重置密码")
                if not current_candidate or not _verify_password(current_candidate, password_hash):
                    raise ValueError("当前密码不正确")
                if _verify_password(next_candidate, password_hash):
                    raise ValueError("新密码不能和当前密码相同")
                next_item = dict(item)
                next_item["password_hash"] = _hash_password(next_candidate)
                self._items[index] = next_item
                self._save()
                return self._public_item(next_item)
        return None

    def authenticate_password(self, username: str, password: str) -> tuple[dict[str, object], str] | None:
        normalized_username = self._normalize_username_value(username)
        candidate_password = str(password or "")
        if not normalized_username or not candidate_password:
            return None
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if str(item.get("role") or "").strip().lower() != "user":
                    continue
                stored_username = self._normalize_username_value(str(item.get("username") or ""))
                if stored_username != normalized_username:
                    continue
                if not bool(item.get("enabled", True)):
                    raise AuthAccountDisabledError("该账号已被禁用，请联系管理员")
                password_hash = self._clean(item.get("password_hash"))
                if not password_hash or not _verify_password(candidate_password, password_hash):
                    return None
                raw_key = self._clean(item.get("key"))
                if not raw_key:
                    raise ValueError("该账号缺少可用于登录的用户密钥，请联系管理员重置密钥")
                next_item = dict(item)
                now = datetime.now(timezone.utc)
                next_item["last_used_at"] = now.isoformat()
                self._items[index] = next_item
                try:
                    self._save()
                    self._last_used_flush_at[self._clean(next_item.get("id"))] = now
                except Exception:
                    pass
                return self._public_item(next_item), raw_key
        return None

    def delete_key(self, key_id: str, *, role: AuthRole | None = None) -> bool:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return False
        with self._lock:
            self._reload_locked()
            before = len(self._items)
            self._items = [
                item
                for item in self._items
                if not (item.get("id") == normalized_id and (role is None or item.get("role") == role))
            ]
            if len(self._items) == before:
                return False
            self._save()
            return True

    def authenticate(self, raw_key: str) -> dict[str, object] | None:
        candidate = self._clean(raw_key)
        if not candidate:
            return None
        candidate_hash = _hash_key(candidate)
        with self._lock:
            for index, item in enumerate(self._items):
                if not bool(item.get("enabled", True)):
                    continue
                stored_hash = self._clean(item.get("key_hash"))
                if not stored_hash or not hmac.compare_digest(stored_hash, candidate_hash):
                    continue
                next_item = dict(item)
                now = datetime.now(timezone.utc)
                next_item["last_used_at"] = now.isoformat()
                self._items[index] = next_item
                item_id = self._clean(next_item.get("id"))
                last_flush_at = self._last_used_flush_at.get(item_id)
                if last_flush_at is None or (now - last_flush_at).total_seconds() >= 60:
                    try:
                        self._save()
                        self._last_used_flush_at[item_id] = now
                    except Exception:
                        pass
                return self._public_item(next_item)
        return None


_IMAGE_KIND_LABEL = {
    "image_daily": "今日画图额度",
    "image_monthly": "本月画图额度",
    "image_total": "画图总额度",
}

_CHAT_KIND_LABEL = {
    "chat_daily": "今日对话额度",
    "chat_monthly": "本月对话额度",
    "chat_total": "对话总额度",
}


def _block_reason(blocked: list[str], label_map: dict[str, str]) -> str:
    labels = [label_map.get(kind, kind) for kind in blocked]
    return "、".join(labels) + "已用完，请联系管理员追加额度后再试"


def _remaining_snapshot(item: dict[str, object], kinds: tuple[QuotaKind, ...]) -> dict[str, int | None]:
    """指定 kinds 当前剩余的快照，给前端实时展示用。"""
    snapshot: dict[str, int | None] = {}
    for kind in kinds:
        quota = AuthService._coerce_int(item.get(f"{kind}_quota"), 0)
        used = AuthService._coerce_int(item.get(f"{kind}_used"), 0)
        unlimited = bool(item.get(f"{kind}_unlimited", False))
        snapshot[kind] = None if unlimited else max(0, quota - used)
    return snapshot


auth_service = AuthService(config.get_storage_backend())
