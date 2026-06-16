from __future__ import annotations

import base64
import json
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from curl_cffi import requests as curl_requests
from curl_cffi.const import CurlHttpVersion

from services.config import DATA_DIR, config

HIGH_RES_IMAGE_RELAYS_FILE = DATA_DIR / "high_res_image_relays.json"
NODE_FETCH_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "high_res_image_relay_fetch.mjs"
URL_RE = re.compile(r"https?://[^\s\"'<>）)\]}]+")
HIGH_RES_RELAY_TIMEOUT = (30, 600)
HIGH_RES_RELAY_TIMEOUT_SECONDS = 630


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _parse_iso(value: object) -> datetime | None:
    raw = _clean(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_paused(item: dict[str, object]) -> bool:
    paused_until = _parse_iso(item.get("paused_until"))
    return bool(paused_until and paused_until > datetime.now(timezone.utc))


def _pause_remaining_seconds(item: dict[str, object]) -> int:
    paused_until = _parse_iso(item.get("paused_until"))
    if not paused_until:
        return 0
    return max(0, int((paused_until - datetime.now(timezone.utc)).total_seconds()))


def _clean(value: object) -> str:
    return str(value or "").strip()


def _normalize_base_url(value: object) -> str:
    return _clean(value).rstrip("/")


def _normalize_mode(value: object) -> str:
    return "images"


def _api_url(base_url: str, resource: str) -> str:
    base = _normalize_base_url(base_url)
    if not base:
        raise ValueError("中转接口 Base URL 不能为空")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}{resource}"


def _outbound_proxy() -> str:
    return config.get_proxy_settings()


def _target_size(size: object, resolution: object) -> str:
    aspect = _clean(size)
    normalized_resolution = _clean(resolution).lower()
    table = {
        "1k": {
            "1:1": "1024x1024",
            "3:2": "1536x1024",
            "2:3": "1024x1536",
            "16:9": "1280x720",
            "9:16": "720x1280",
            "4:3": "1024x768",
            "3:4": "768x1024",
            "21:9": "1280x544",
            "": "1024x1024",
        },
        "2k": {
            "1:1": "2048x2048",
            "3:2": "2016x1344",
            "2:3": "1344x2016",
            "16:9": "2048x1152",
            "9:16": "1152x2048",
            "4:3": "2048x1536",
            "3:4": "1536x2048",
            "21:9": "2048x864",
            "": "2048x2048",
        },
        "4k": {
            "1:1": "2880x2880",
            "3:2": "3264x2176",
            "2:3": "2176x3264",
            "16:9": "3840x2160",
            "9:16": "2160x3840",
            "4:3": "2880x2160",
            "3:4": "2160x2880",
            "21:9": "3840x1620",
            "": "2880x2880",
        },
    }
    return table.get(normalized_resolution, {}).get(aspect) or table.get(normalized_resolution, {}).get("") or aspect


def _image_body(*, prompt: str, model: str, size: str, resolution: str = "") -> dict[str, object]:
    body: dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "output_format": "png",
        "moderation": "auto",
        "n": 1,
        "stream": False,
    }
    normalized_resolution = _clean(resolution).lower()
    if normalized_resolution in {"1k", "2k", "4k"}:
        body["resolution"] = normalized_resolution
    return body


def _chat_body(*, prompt: str, model: str, size: str) -> dict[str, object]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "prompt": prompt,
        "size": size,
        "style": "vivid",
        "n": 1,
        "temperature": 0.7,
    }


def _compact_error(response_payload: object) -> str:
    if isinstance(response_payload, dict):
        error = response_payload.get("error")
        if isinstance(error, dict):
            return _clean(error.get("message")) or _clean(error.get("code")) or json.dumps(error, ensure_ascii=False)[:300]
        if error:
            return _clean(error) or json.dumps(error, ensure_ascii=False)[:300]
        message = response_payload.get("message")
        if message:
            return _clean(message) or json.dumps(message, ensure_ascii=False)[:300]
    return _clean(response_payload)[:300]


def _string_value(source: dict[str, object], key: str) -> str:
    value = source.get(key)
    return value.strip() if isinstance(value, str) else ""


def _number_value(source: dict[str, object], key: str) -> int | None:
    value = source.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


class HighResImageRelayService:
    def __init__(self, path: Path = HIGH_RES_IMAGE_RELAYS_FILE):
        self.path = path
        self._lock = threading.RLock()
        self._next_index = 0

    def _load_locked(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        normalized: list[dict[str, object]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            base_url = _normalize_base_url(raw.get("base_url"))
            if not base_url:
                continue
            item = {
                "id": _clean(raw.get("id")) or uuid.uuid4().hex[:12],
                "name": _clean(raw.get("name")) or "中转接口",
                "base_url": base_url,
                "api_key": _clean(raw.get("api_key")),
                "model": _clean(raw.get("model")) or "gpt-image-2",
                "mode": _normalize_mode(raw.get("mode")),
                "enabled": bool(raw.get("enabled", True)),
                "success": max(0, int(raw.get("success") or 0)),
                "fail": max(0, int(raw.get("fail") or 0)),
                "total_duration_ms": max(0, int(raw.get("total_duration_ms") or 0)),
                "today_date": _clean(raw.get("today_date")) or _today_key(),
                "today_success": max(0, int(raw.get("today_success") or 0)),
                "today_fail": max(0, int(raw.get("today_fail") or 0)),
                "today_duration_ms": max(0, int(raw.get("today_duration_ms") or 0)),
                "consecutive_fail": max(0, int(raw.get("consecutive_fail") or 0)),
                "paused_until": _clean(raw.get("paused_until")) or None,
                "pause_reason": _clean(raw.get("pause_reason")),
                "last_used_at": _clean(raw.get("last_used_at")) or None,
                "last_error": _clean(raw.get("last_error")),
                "created_at": _clean(raw.get("created_at")) or _now_iso(),
                "updated_at": _clean(raw.get("updated_at")) or _now_iso(),
            }
            normalized.append(item)
        return normalized

    def _save_locked(self, items: list[dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    @staticmethod
    def _public_item(item: dict[str, object]) -> dict[str, object]:
        success = int(item.get("success") or 0)
        fail = int(item.get("fail") or 0)
        total_count = success + fail
        total_duration_ms = int(item.get("total_duration_ms") or 0)
        today_date = _clean(item.get("today_date"))
        today_success = int(item.get("today_success") or 0) if today_date == _today_key() else 0
        today_fail = int(item.get("today_fail") or 0) if today_date == _today_key() else 0
        today_count = today_success + today_fail
        today_duration_ms = int(item.get("today_duration_ms") or 0) if today_date == _today_key() else 0
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "base_url": item.get("base_url"),
            "model": item.get("model"),
            "mode": item.get("mode") or "images",
            "enabled": bool(item.get("enabled", True)),
            "has_api_key": bool(_clean(item.get("api_key"))),
            "success": success,
            "fail": fail,
            "avg_duration_ms": int(total_duration_ms / total_count) if total_count else 0,
            "today_success": today_success,
            "today_fail": today_fail,
            "today_avg_duration_ms": int(today_duration_ms / today_count) if today_count else 0,
            "consecutive_fail": int(item.get("consecutive_fail") or 0),
            "temporarily_paused": _is_paused(item),
            "paused_until": item.get("paused_until") if _is_paused(item) else None,
            "pause_reason": item.get("pause_reason") if _is_paused(item) else "",
            "pause_remaining_seconds": _pause_remaining_seconds(item),
            "last_used_at": item.get("last_used_at") or None,
            "last_error": item.get("last_error") or "",
            "created_at": item.get("created_at") or None,
            "updated_at": item.get("updated_at") or None,
        }

    def list_relays(self) -> list[dict[str, object]]:
        with self._lock:
            items = self._load_locked()
            return [self._public_item(item) for item in items]

    def add_relay(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str = "gpt-image-2",
        mode: str = "images",
        enabled: bool = True,
    ) -> dict[str, object]:
        normalized_base_url = _normalize_base_url(base_url)
        normalized_api_key = _clean(api_key)
        if not normalized_base_url:
            raise ValueError("请输入中转接口 Base URL")
        if not normalized_api_key:
            raise ValueError("请输入中转接口 API Key")
        now = _now_iso()
        item = {
            "id": uuid.uuid4().hex[:12],
            "name": _clean(name) or "中转接口",
            "base_url": normalized_base_url,
            "api_key": normalized_api_key,
            "model": _clean(model) or "gpt-image-2",
            "mode": _normalize_mode(mode),
            "enabled": bool(enabled),
            "success": 0,
            "fail": 0,
            "total_duration_ms": 0,
            "today_date": _today_key(),
            "today_success": 0,
            "today_fail": 0,
            "today_duration_ms": 0,
            "consecutive_fail": 0,
            "paused_until": None,
            "pause_reason": "",
            "last_used_at": None,
            "last_error": "",
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            items = self._load_locked()
            items.append(item)
            self._save_locked(items)
            return self._public_item(item)

    def update_relay(self, relay_id: str, updates: dict[str, object]) -> dict[str, object] | None:
        normalized_id = _clean(relay_id)
        if not normalized_id:
            return None
        with self._lock:
            items = self._load_locked()
            for index, item in enumerate(items):
                if item.get("id") != normalized_id:
                    continue
                next_item = dict(item)
                if "name" in updates:
                    next_item["name"] = _clean(updates.get("name")) or "中转接口"
                if "base_url" in updates:
                    base_url = _normalize_base_url(updates.get("base_url"))
                    if not base_url:
                        raise ValueError("请输入中转接口 Base URL")
                    next_item["base_url"] = base_url
                if "api_key" in updates and _clean(updates.get("api_key")):
                    next_item["api_key"] = _clean(updates.get("api_key"))
                if "model" in updates:
                    next_item["model"] = _clean(updates.get("model")) or "gpt-image-2"
                if "mode" in updates:
                    next_item["mode"] = _normalize_mode(updates.get("mode"))
                if "enabled" in updates and updates.get("enabled") is not None:
                    next_item["enabled"] = bool(updates.get("enabled"))
                    if next_item["enabled"]:
                        next_item["consecutive_fail"] = 0
                        next_item["paused_until"] = None
                        next_item["pause_reason"] = ""
                next_item["updated_at"] = _now_iso()
                items[index] = next_item
                self._save_locked(items)
                return self._public_item(next_item)
        return None

    def delete_relay(self, relay_id: str) -> bool:
        normalized_id = _clean(relay_id)
        if not normalized_id:
            return False
        with self._lock:
            items = self._load_locked()
            next_items = [item for item in items if item.get("id") != normalized_id]
            if len(next_items) == len(items):
                return False
            self._save_locked(next_items)
            return True

    def _enabled_relays_locked(self) -> list[dict[str, object]]:
        items = self._load_locked()
        changed = False
        enabled_items: list[dict[str, object]] = []
        for index, item in enumerate(items):
            next_item = item
            paused_until = _parse_iso(item.get("paused_until"))
            if paused_until and paused_until <= datetime.now(timezone.utc):
                next_item = dict(item)
                next_item["consecutive_fail"] = 0
                next_item["paused_until"] = None
                next_item["pause_reason"] = ""
                next_item["updated_at"] = _now_iso()
                items[index] = next_item
                changed = True
            if (
                bool(next_item.get("enabled", True))
                and _clean(next_item.get("base_url"))
                and _clean(next_item.get("api_key"))
                and not _is_paused(next_item)
            ):
                enabled_items.append(next_item)
        if changed:
            self._save_locked(items)
        return enabled_items

    def _ordered_enabled_relays(self) -> list[dict[str, object]]:
        with self._lock:
            items = self._enabled_relays_locked()
            if not items:
                return []
            offset = self._next_index % len(items)
            self._next_index = (self._next_index + 1) % len(items)
            return items[offset:] + items[:offset]

    def _mark_result(self, relay_id: object, *, ok: bool, error: str = "", duration_ms: int = 0) -> None:
        normalized_id = _clean(relay_id)
        if not normalized_id:
            return
        with self._lock:
            items = self._load_locked()
            for index, item in enumerate(items):
                if item.get("id") != normalized_id:
                    continue
                next_item = dict(item)
                today = _today_key()
                if _clean(next_item.get("today_date")) != today:
                    next_item["today_date"] = today
                    next_item["today_success"] = 0
                    next_item["today_fail"] = 0
                    next_item["today_duration_ms"] = 0
                if ok:
                    next_item["success"] = int(next_item.get("success") or 0) + 1
                    next_item["today_success"] = int(next_item.get("today_success") or 0) + 1
                    next_item["last_error"] = ""
                    next_item["consecutive_fail"] = 0
                    next_item["paused_until"] = None
                    next_item["pause_reason"] = ""
                else:
                    next_item["fail"] = int(next_item.get("fail") or 0) + 1
                    next_item["today_fail"] = int(next_item.get("today_fail") or 0) + 1
                    compact_error = _clean(error)[:500]
                    next_item["last_error"] = compact_error
                    consecutive_fail = int(next_item.get("consecutive_fail") or 0) + 1
                    next_item["consecutive_fail"] = consecutive_fail
                    threshold = config.high_res_relay_fail_threshold
                    if consecutive_fail >= threshold:
                        cooldown = config.high_res_relay_cooldown_seconds
                        next_item["paused_until"] = (datetime.now(timezone.utc) + timedelta(seconds=cooldown)).isoformat()
                        next_item["pause_reason"] = f"连续失败 {consecutive_fail} 次：{compact_error[:160]}"
                if duration_ms > 0:
                    next_item["total_duration_ms"] = int(next_item.get("total_duration_ms") or 0) + int(duration_ms)
                    next_item["today_duration_ms"] = int(next_item.get("today_duration_ms") or 0) + int(duration_ms)
                next_item["last_used_at"] = _now_iso()
                next_item["updated_at"] = _now_iso()
                items[index] = next_item
                self._save_locked(items)
                return

    def _session(self) -> curl_requests.Session:
        session_kwargs: dict[str, object] = {"impersonate": "chrome", "verify": True}
        proxy = _outbound_proxy()
        if proxy:
            session_kwargs["proxy"] = proxy
        session = curl_requests.Session(**session_kwargs)
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/143.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        return session

    @staticmethod
    def _headers(relay: dict[str, object]) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {_clean(relay.get('api_key'))}",
        }

    def _decode_url_image(self, session: curl_requests.Session, url: str) -> str:
        if url.startswith("data:image/") and ";base64," in url:
            return url.split(",", 1)[1].strip()
        response = session.get(url, timeout=(20, 180), http_version=CurlHttpVersion.V2TLS)
        if not (200 <= response.status_code < 300):
            raise RuntimeError(f"download image failed: HTTP {response.status_code}")
        return base64.b64encode(response.content).decode("ascii")

    def _normalize_response_items(self, session: curl_requests.Session, payload: object, prompt: str) -> tuple[int, list[dict[str, object]]]:
        if not isinstance(payload, dict):
            raise RuntimeError("中转接口返回格式不是 JSON 对象")
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            message = _compact_error(payload) or "中转接口未返回图片"
            raise RuntimeError(message)
        items: list[dict[str, object]] = []
        for raw in data:
            if not isinstance(raw, dict):
                continue
            revised_prompt = _clean(raw.get("revised_prompt")) or prompt
            b64_json = _clean(raw.get("b64_json"))
            url = _clean(raw.get("url"))
            if not b64_json:
                if url:
                    try:
                        b64_json = self._decode_url_image(session, url)
                    except Exception as exc:
                        items.append({
                            "url": url,
                            "revised_prompt": revised_prompt,
                            "download_error": str(exc) or exc.__class__.__name__,
                        })
                        continue
            if not b64_json:
                continue
            items.append({
                "b64_json": b64_json,
                "url": url,
                "revised_prompt": revised_prompt,
            })
        if not items:
            raise RuntimeError("中转接口返回了结果，但没有可读取的图片数据")
        try:
            created = int(payload.get("created") or time.time())
        except (TypeError, ValueError):
            created = int(time.time())
        return created, items

    @staticmethod
    def _append_url_items(items: list[dict[str, object]], text: str, prompt: str) -> None:
        for url in URL_RE.findall(text):
            items.append({"url": url.rstrip(".,，。"), "revised_prompt": prompt})
        if text.startswith("data:image/") and ";base64," in text:
            items.append({"b64_json": text.split(",", 1)[1].strip(), "revised_prompt": prompt})

    def _extract_chat_items(self, payload: object, prompt: str) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        seen: set[str] = set()

        def add_item(item: dict[str, object]) -> None:
            b64_json = _clean(item.get("b64_json"))
            url = _clean(item.get("url"))
            key = b64_json or url
            if not key or key in seen:
                return
            seen.add(key)
            next_item: dict[str, object] = {"revised_prompt": _clean(item.get("revised_prompt")) or prompt}
            if b64_json:
                next_item["b64_json"] = b64_json
            if url:
                next_item["url"] = url
            items.append(next_item)

        def walk(value: object) -> None:
            if isinstance(value, dict):
                direct_b64 = _clean(value.get("b64_json")) or _clean(value.get("base64"))
                direct_url = _clean(value.get("url"))
                image_url = value.get("image_url")
                if isinstance(image_url, dict):
                    direct_url = direct_url or _clean(image_url.get("url"))
                elif isinstance(image_url, str):
                    direct_url = direct_url or _clean(image_url)
                if direct_b64 or direct_url:
                    add_item({
                        "b64_json": direct_b64,
                        "url": direct_url,
                        "revised_prompt": value.get("revised_prompt"),
                    })
                for key, nested in value.items():
                    if key in {"b64_json", "base64", "url", "image_url"}:
                        continue
                    walk(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    walk(nested)
                return
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    return
                before = len(items)
                self._append_url_items(items, text, prompt)
                for item in items[before:]:
                    key = _clean(item.get("b64_json")) or _clean(item.get("url"))
                    if key in seen:
                        continue
                    seen.add(key)
                if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
                    try:
                        walk(json.loads(text))
                    except Exception:
                        pass

        walk(payload)
        return items

    def _normalize_chat_response_items(
        self,
        session: curl_requests.Session,
        payload: object,
        prompt: str,
    ) -> tuple[int, list[dict[str, object]]]:
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return self._normalize_response_items(session, payload, prompt)
        items = self._extract_chat_items(payload, prompt)
        if not items:
            message = _compact_error(payload) or "Chat Completions 中转未返回可识别的图片数据"
            raise RuntimeError(message)
        try:
            created = int(payload.get("created") if isinstance(payload, dict) else 0) or int(time.time())
        except (TypeError, ValueError):
            created = int(time.time())
        return created, items

    @staticmethod
    def _event_to_item(event: dict[str, object], prompt: str) -> dict[str, object]:
        item: dict[str, object] = {}
        b64_json = _string_value(event, "b64_json")
        url = _string_value(event, "url")
        if b64_json:
            item["b64_json"] = b64_json
        if url:
            item["url"] = url
        item["revised_prompt"] = _string_value(event, "revised_prompt") or prompt
        return item

    @staticmethod
    def _parse_sse_block(lines: list[str]) -> object | None:
        data_lines: list[str] = []
        for line in lines:
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            return None
        return json.loads(data)

    def _normalize_stream_response(
        self,
        session: curl_requests.Session,
        response: curl_requests.Response,
        prompt: str,
    ) -> tuple[int, list[dict[str, object]]]:
        completed_items: list[dict[str, object]] = []
        result_payload: object | None = None
        sse_lines: list[str] = []

        def process_block(lines: list[str]) -> None:
            nonlocal result_payload
            if not lines:
                return
            event = self._parse_sse_block(lines)
            if not isinstance(event, dict):
                return
            error_message = _compact_error(event)
            if event.get("error") and error_message:
                raise RuntimeError(error_message)
            event_type = _string_value(event, "type")
            event_object = _string_value(event, "object")
            if event_type in {"image_generation.partial_image", "image_edit.partial_image"}:
                return
            if event_object in {"image.generation.result", "image.edit.result"}:
                result_payload = event
                return
            if event_type in {"image_generation.completed", "image_edit.completed"}:
                item = self._event_to_item(event, prompt)
                if item.get("b64_json") or item.get("url"):
                    completed_items.append(item)

        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line or "")
                if line:
                    sse_lines.append(line)
                    continue
                process_block(sse_lines)
                sse_lines = []
            process_block(sse_lines)
        finally:
            response.close()

        if result_payload is not None:
            return self._normalize_response_items(session, result_payload, prompt)
        if not completed_items:
            raise RuntimeError("流式中转接口未返回最终图片数据")
        return int(time.time()), completed_items

    def _normalize_stream_text(
        self,
        session: curl_requests.Session,
        text: str,
        prompt: str,
    ) -> tuple[int, list[dict[str, object]]]:
        completed_items: list[dict[str, object]] = []
        result_payload: object | None = None
        sse_lines: list[str] = []

        def process_block(lines: list[str]) -> None:
            nonlocal result_payload
            if not lines:
                return
            event = self._parse_sse_block(lines)
            if not isinstance(event, dict):
                return
            error_message = _compact_error(event)
            if event.get("error") and error_message:
                raise RuntimeError(error_message)
            event_type = _string_value(event, "type")
            event_object = _string_value(event, "object")
            if event_type in {"image_generation.partial_image", "image_edit.partial_image"}:
                return
            if event_object in {"image.generation.result", "image.edit.result"}:
                result_payload = event
                return
            if event_type in {"image_generation.completed", "image_edit.completed"}:
                item = self._event_to_item(event, prompt)
                if item.get("b64_json") or item.get("url"):
                    completed_items.append(item)

        for raw_line in text.splitlines():
            line = str(raw_line or "")
            if line:
                sse_lines.append(line)
                continue
            process_block(sse_lines)
            sse_lines = []
        process_block(sse_lines)

        if result_payload is not None:
            return self._normalize_response_items(session, result_payload, prompt)
        if not completed_items:
            raise RuntimeError("流式中转接口未返回最终图片数据")
        return int(time.time()), completed_items

    def _request_with_node_fetch(self, request_payload: dict[str, object]) -> dict[str, object]:
        try:
            completed = subprocess.run(
                ["node", str(NODE_FETCH_SCRIPT)],
                input=json.dumps(request_payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=HIGH_RES_RELAY_TIMEOUT_SECONDS + 30,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Node fetch helper unavailable: node not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Node fetch helper timed out") from exc

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            raise RuntimeError(stderr or stdout or f"Node fetch helper exited with {completed.returncode}")
        try:
            result = json.loads(stdout)
        except Exception as exc:
            raise RuntimeError(f"Node fetch helper returned invalid JSON: {stdout[:300]}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Node fetch helper returned invalid payload")
        return result

    def _post_json_with_node_fetch(
        self,
        relay: dict[str, object],
        resource: str,
        body: dict[str, object],
    ) -> tuple[int, list[dict[str, object]]]:
        request_payload = {
            "url": _api_url(_clean(relay.get("base_url")), resource),
            "apiKey": _clean(relay.get("api_key")),
            "body": body,
            "timeoutMs": HIGH_RES_RELAY_TIMEOUT_SECONDS * 1000,
            "proxy": _outbound_proxy(),
        }
        result = self._request_with_node_fetch(request_payload)
        if result.get("networkError"):
            parts = [
                _clean(result.get("networkError")) or "Node fetch network error",
                _clean(result.get("errorName")),
                _clean(result.get("causeCode")),
                _clean(result.get("cause")),
                f"proxy_used={bool(result.get('proxyUsed'))}",
            ]
            raise RuntimeError(" / ".join(part for part in parts if part))
        if not bool(result.get("ok")):
            status = int(result.get("status") or 0)
            payload = result.get("json") if result.get("json") is not None else result.get("text")
            raise RuntimeError(f"HTTP {status}: {_compact_error(payload) or _clean(payload)[:300]}")

        session = self._session()
        try:
            content_type = _clean(result.get("contentType")).lower()
            if "text/event-stream" in content_type:
                return self._normalize_stream_text(session, _clean(result.get("text")), _clean(body.get("prompt")))
            payload = result.get("json")
            if payload is None:
                text = _clean(result.get("text"))
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = text
            return self._normalize_response_items(session, payload, _clean(body.get("prompt")))
        finally:
            session.close()

    def _post_multipart_with_node_fetch(
        self,
        relay: dict[str, object],
        resource: str,
        data: dict[str, object],
        images: list[str],
        image_field: str,
    ) -> tuple[int, list[dict[str, object]]]:
        request_payload = {
            "url": _api_url(_clean(relay.get("base_url")), resource),
            "apiKey": _clean(relay.get("api_key")),
            "multipart": True,
            "data": data,
            "images": images,
            "imageField": image_field,
            "timeoutMs": HIGH_RES_RELAY_TIMEOUT_SECONDS * 1000,
            "proxy": _outbound_proxy(),
        }
        result = self._request_with_node_fetch(request_payload)
        if result.get("networkError"):
            parts = [
                _clean(result.get("networkError")) or "Node fetch network error",
                _clean(result.get("errorName")),
                _clean(result.get("causeCode")),
                _clean(result.get("cause")),
                f"proxy_used={bool(result.get('proxyUsed'))}",
            ]
            raise RuntimeError(" / ".join(part for part in parts if part))
        if not bool(result.get("ok")):
            status = int(result.get("status") or 0)
            payload = result.get("json") if result.get("json") is not None else result.get("text")
            raise RuntimeError(f"HTTP {status}: {_compact_error(payload) or _clean(payload)[:300]}")

        session = self._session()
        try:
            content_type = _clean(result.get("contentType")).lower()
            if "text/event-stream" in content_type:
                return self._normalize_stream_text(session, _clean(result.get("text")), _clean(data.get("prompt")))
            payload = result.get("json")
            if payload is None:
                text = _clean(result.get("text"))
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = text
            return self._normalize_response_items(session, payload, _clean(data.get("prompt")))
        finally:
            session.close()

    def _post_json(self, relay: dict[str, object], resource: str, body: dict[str, object]) -> tuple[int, list[dict[str, object]]]:
        if resource == "/images/generations":
            return self._post_json_with_node_fetch(relay, resource, body)
        session = self._session()
        try:
            accept = (
                "text/event-stream, application/json;q=0.9, */*;q=0.8"
                if bool(body.get("stream"))
                else "application/json, text/plain, */*"
            )
            response = session.post(
                _api_url(_clean(relay.get("base_url")), resource),
                headers={**self._headers(relay), "Content-Type": "application/json", "Accept": accept},
                json=body,
                timeout=HIGH_RES_RELAY_TIMEOUT,
                stream=bool(body.get("stream")),
                http_version=CurlHttpVersion.V2TLS,
            )
            if not (200 <= response.status_code < 300):
                try:
                    payload: object = response.json()
                except Exception:
                    payload = response.text
                raise RuntimeError(f"HTTP {response.status_code}: {_compact_error(payload) or response.text[:300]}")
            if bool(body.get("stream")) and "text/event-stream" in response.headers.get("Content-Type", "").lower():
                return self._normalize_stream_response(session, response, _clean(body.get("prompt")))
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            return self._normalize_response_items(session, payload, _clean(body.get("prompt")))
        finally:
            session.close()

    def _post_chat_json(self, relay: dict[str, object], body: dict[str, object]) -> tuple[int, list[dict[str, object]]]:
        session = self._session()
        try:
            response = session.post(
                _api_url(_clean(relay.get("base_url")), "/chat/completions"),
                headers={**self._headers(relay), "Content-Type": "application/json"},
                json=body,
                timeout=HIGH_RES_RELAY_TIMEOUT,
                http_version=CurlHttpVersion.V2TLS,
            )
            try:
                payload: object = response.json()
            except Exception:
                payload = response.text
            if not (200 <= response.status_code < 300):
                raise RuntimeError(f"HTTP {response.status_code}: {_compact_error(payload) or response.text[:300]}")
            return self._normalize_chat_response_items(session, payload, _clean(body.get("prompt")))
        finally:
            session.close()

    def _post_multipart(
        self,
        relay: dict[str, object],
        resource: str,
        data: dict[str, object],
        images: list[str],
        image_field: str = "image[]",
    ) -> tuple[int, list[dict[str, object]]]:
        for encoded in images:
            try:
                base64.b64decode(encoded)
            except Exception as exc:
                raise RuntimeError("参考图数据无效") from exc
        return self._post_multipart_with_node_fetch(relay, resource, data, images, image_field)

    def generate(
        self,
        *,
        prompt: str,
        model: str,
        size: object,
        resolution: object,
        images: list[str] | None = None,
    ) -> dict[str, object]:
        relays = self._ordered_enabled_relays()
        if not relays:
            raise RuntimeError("未配置可用的中转接口，请在管理员设置里添加后再试")
        errors: list[str] = []
        for relay in relays:
            relay_id = relay.get("id")
            relay_name = _clean(relay.get("name")) or _clean(relay.get("base_url"))
            body_model = _clean(relay.get("model")) or _clean(model) or "gpt-image-2"
            target_size = _target_size(size, resolution)
            attempt_started = time.perf_counter()
            try:
                if images:
                    data = _image_body(prompt=prompt, model=body_model, size=target_size, resolution=_clean(resolution))
                    created, items = self._post_multipart(
                        relay,
                        "/images/edits",
                        {key: str(value) for key, value in data.items()},
                        images,
                    )
                else:
                    created, items = self._post_json(
                        relay,
                        "/images/generations",
                        _image_body(prompt=prompt, model=body_model, size=target_size, resolution=_clean(resolution)),
                    )
                duration_ms = int((time.perf_counter() - attempt_started) * 1000)
                self._mark_result(relay_id, ok=True, duration_ms=duration_ms)
                return {
                    "created": created,
                    "items": items,
                    "relay_id": relay_id,
                    "relay_name": relay_name,
                    "target_size": target_size,
                    "target_resolution": _clean(resolution),
                }
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                errors.append(f"{relay_name}: {message}")
                duration_ms = int((time.perf_counter() - attempt_started) * 1000)
                self._mark_result(relay_id, ok=False, error=message, duration_ms=duration_ms)
                continue
        raise RuntimeError("中转接口调用失败：" + "；".join(errors[-3:]))

    def test_relay(self, relay_id: str) -> dict[str, object]:
        normalized_id = _clean(relay_id)
        with self._lock:
            relay = next((item for item in self._load_locked() if item.get("id") == normalized_id), None)
        if relay is None:
            raise ValueError("中转接口不存在，可能已经被删除")
        if not _clean(relay.get("api_key")):
            raise ValueError("这个中转接口还没有配置 API Key")
        started = time.perf_counter()
        session = self._session()
        try:
            response = session.get(
                _api_url(_clean(relay.get("base_url")), "/models"),
                headers=self._headers(relay),
                timeout=30,
                http_version=CurlHttpVersion.V2TLS,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            ok = 200 <= response.status_code < 300
            error = "" if ok else response.text[:300]
            return {"ok": ok, "status": int(response.status_code), "latency_ms": latency_ms, "error": error}
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return {"ok": False, "status": 0, "latency_ms": latency_ms, "error": str(exc) or exc.__class__.__name__}
        finally:
            session.close()


high_res_image_relay_service = HighResImageRelayService()
