from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from threading import Lock

from services.config import DATA_DIR

RATE_LIMIT_FILE = DATA_DIR / "rate_limits.json"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _today_key() -> str:
    return date.today().isoformat()


class RateLimitExceeded(ValueError):
    pass


class RateLimitService:
    def __init__(self, path: Path = RATE_LIMIT_FILE):
        self.path = path
        self._lock = Lock()

    def _load_locked(self) -> dict[str, object]:
        if not self.path.exists():
            return {"register": {}, "image": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"register": {}, "image": {}}
        if not isinstance(data, dict):
            return {"register": {}, "image": {}}
        register = data.get("register") if isinstance(data.get("register"), dict) else {}
        image = data.get("image") if isinstance(data.get("image"), dict) else {}
        return {"register": register, "image": image}

    def _save_locked(self, data: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    def check_register(self, ip: str, *, limit: int) -> None:
        normalized_ip = _clean(ip) or "unknown"
        normalized_limit = max(0, int(limit or 0))
        if normalized_limit <= 0:
            return
        today = _today_key()
        with self._lock:
            data = self._load_locked()
            register = data.get("register") if isinstance(data.get("register"), dict) else {}
            item = register.get(normalized_ip) if isinstance(register.get(normalized_ip), dict) else {}
            if item.get("date") != today:
                item = {"date": today, "count": 0}
            count = max(0, int(item.get("count") or 0))
            if count >= normalized_limit:
                raise RateLimitExceeded(f"当前 IP 今日注册次数已达上限（{normalized_limit} 次），请明天再试")
            item["count"] = count + 1
            register[normalized_ip] = item
            data["register"] = register
            self._save_locked(data)

    def check_image(self, ip: str, *, limit: int, window_seconds: int = 60) -> None:
        normalized_ip = _clean(ip) or "unknown"
        normalized_limit = max(0, int(limit or 0))
        normalized_window = max(10, int(window_seconds or 60))
        if normalized_limit <= 0:
            return
        now = time.time()
        cutoff = now - normalized_window
        with self._lock:
            data = self._load_locked()
            image = data.get("image") if isinstance(data.get("image"), dict) else {}
            timestamps = image.get(normalized_ip)
            if not isinstance(timestamps, list):
                timestamps = []
            recent = [float(value) for value in timestamps if isinstance(value, (int, float)) and float(value) >= cutoff]
            if len(recent) >= normalized_limit:
                raise RateLimitExceeded(f"当前 IP 生图过于频繁，请稍后再试")
            recent.append(now)
            image[normalized_ip] = recent
            # 顺手清掉半小时没动静的 IP，避免文件无限增长。
            prune_cutoff = now - 1800
            for key in list(image.keys()):
                values = image.get(key)
                if not isinstance(values, list) or not any(isinstance(value, (int, float)) and float(value) >= prune_cutoff for value in values):
                    image.pop(key, None)
            data["image"] = image
            self._save_locked(data)


rate_limit_service = RateLimitService()
