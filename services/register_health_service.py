from __future__ import annotations

import time
from urllib.parse import urlparse

import requests

from services.register import mail_provider, openai_register
from services.register_service import register_service


def _clean(value: object) -> str:
    return str(value or "").strip()


def _check(name: str, fn) -> dict[str, object]:
    started = time.perf_counter()
    try:
        result = fn()
        latency_ms = int((time.perf_counter() - started) * 1000)
        if isinstance(result, dict):
            return {"name": name, "ok": bool(result.get("ok", True)), "latency_ms": latency_ms, **result}
        return {"name": name, "ok": True, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "name": name,
            "ok": False,
            "status": 0,
            "latency_ms": latency_ms,
            "error": str(exc) or exc.__class__.__name__,
        }


def _mailbox_probe(mail_config: dict, proxy: str) -> dict[str, object]:
    mailbox = mail_provider.create_mailbox(mail_config, proxy=proxy)
    try:
        address = _clean(mailbox.get("address"))
        return {
            "ok": bool(address),
            "status": 201 if address else 0,
            "detail": address.rsplit("@", 1)[-1] if "@" in address else address,
        }
    finally:
        try:
            mail_provider.delete_mailbox(mail_config, mailbox, proxy=proxy)
        except Exception:
            pass


def _csrf_probe(proxy: str) -> dict[str, object]:
    session = openai_register.create_session(proxy)
    try:
        response = session.get(
            "https://chatgpt.com/api/auth/csrf",
            headers={"User-Agent": "Mozilla/5.0 (chatgpt2api register health)"},
            timeout=15,
        )
        data = {}
        try:
            data = response.json()
        except Exception:
            pass
        ok = response.status_code == 200 and bool(data.get("csrfToken"))
        return {
            "ok": ok,
            "status": int(response.status_code),
            "detail": "csrfToken ok" if ok else (response.text or "")[:160],
        }
    finally:
        try:
            session.close()
        except Exception:
            pass


def _auth_probe(proxy: str) -> dict[str, object]:
    session = openai_register.create_session(proxy)
    try:
        response = session.get(
            "https://auth.openai.com",
            headers={"User-Agent": "Mozilla/5.0 (chatgpt2api register health)"},
            timeout=15,
            allow_redirects=True,
        )
        return {
            "ok": 200 <= int(response.status_code) < 400,
            "status": int(response.status_code),
            "detail": (response.url or "")[:180],
        }
    finally:
        try:
            session.close()
        except Exception:
            pass


def _mihomo_node(proxy: str) -> dict[str, object]:
    candidate = _clean(proxy)
    if not candidate:
        return {"proxy": "", "node": "", "detail": "未配置注册代理"}
    parsed = urlparse(candidate)
    host = parsed.hostname or ""
    if not host:
        return {"proxy": candidate, "node": "", "detail": "代理地址无法解析"}
    controller_host = "127.0.0.1" if host in {"localhost", "127.0.0.1"} else host
    url = f"http://{controller_host}:9090/proxies/GLOBAL"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code != 200:
            return {"proxy": candidate, "node": "", "detail": f"mihomo API HTTP {response.status_code}"}
        data = response.json()
        node = _clean(data.get("now")) or _clean(data.get("name"))
        return {"proxy": candidate, "node": node, "detail": url}
    except Exception as exc:
        return {"proxy": candidate, "node": "", "detail": str(exc) or exc.__class__.__name__}


def run_register_health_check() -> dict[str, object]:
    register_config = register_service.get()
    mail_config = register_config.get("mail") if isinstance(register_config.get("mail"), dict) else {}
    proxy = _clean(register_config.get("proxy"))
    checks = [
        _check("邮箱直连", lambda: _mailbox_probe(mail_config, "")),
        _check(
            "邮箱代理",
            lambda: _mailbox_probe(mail_config, proxy) if proxy else {
                "ok": False,
                "status": 0,
                "error": "未配置注册代理",
            },
        ),
        _check("ChatGPT CSRF", lambda: _csrf_probe(proxy)),
        _check("auth.openai.com", lambda: _auth_probe(proxy)),
    ]
    return {
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "proxy": _mihomo_node(proxy),
        "checks": checks,
        "ok": all(bool(item.get("ok")) for item in checks),
    }
