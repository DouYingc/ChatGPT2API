from __future__ import annotations

import time
import uuid
from urllib.parse import urlencode, urlparse

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
            ok = bool(result.get("ok", True))
            return {"name": name, "ok": ok, "level": "ok" if ok else "error", "latency_ms": latency_ms, **result}
        return {"name": name, "ok": True, "level": "ok", "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "name": name,
            "ok": False,
            "level": "error",
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
            "level": "ok" if ok else "warning",
            "status": int(response.status_code),
            "detail": "csrfToken ok" if ok else "脚本访问被拒绝，不一定影响注册",
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
        ok = 200 <= int(response.status_code) < 400
        return {
            "ok": ok,
            "level": "ok" if ok else "warning",
            "status": int(response.status_code),
            "detail": (response.url or "")[:180] if ok else "首页被拒绝，不等于注册 API 不可用",
        }
    finally:
        try:
            session.close()
        except Exception:
            pass


def _platform_authorize_probe(proxy: str) -> dict[str, object]:
    session = openai_register.create_session(proxy)
    try:
        device_id = str(uuid.uuid4())
        _, code_challenge = openai_register._generate_pkce()
        params = {
            "issuer": openai_register.auth_base,
            "client_id": openai_register.platform_oauth_client_id,
            "audience": openai_register.platform_oauth_audience,
            "redirect_uri": openai_register.platform_oauth_redirect_uri,
            "device_id": device_id,
            "screen_hint": "login_or_signup",
            "max_age": "0",
            "login_hint": f"health-{int(time.time())}@example.com",
            "scope": "openid profile email offline_access",
            "response_type": "code",
            "response_mode": "query",
            "state": "health",
            "nonce": "health",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "auth0Client": openai_register.platform_auth0_client,
        }
        headers = dict(openai_register.navigate_headers)
        headers["referer"] = f"{openai_register.platform_base}/"
        response = session.get(
            f"{openai_register.auth_base}/api/accounts/authorize?{urlencode(params)}",
            headers=headers,
            timeout=15,
            allow_redirects=True,
            verify=False,
        )
        ok = int(response.status_code) == 200
        return {
            "ok": ok,
            "level": "ok" if ok else "error",
            "status": int(response.status_code),
            "detail": "authorize ok" if ok else (response.text or "")[:160],
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
    direct_mail = _check("邮箱直连", lambda: _mailbox_probe(mail_config, ""))
    if proxy and not direct_mail.get("ok"):
        direct_mail["level"] = "warning"
        direct_mail["detail"] = _clean(direct_mail.get("detail")) or "当前注册配置会优先看邮箱代理"

    proxy_mail = _check(
        "邮箱代理",
        lambda: _mailbox_probe(mail_config, proxy) if proxy else {
            "ok": False,
            "level": "warning",
            "status": 0,
            "error": "未配置注册代理",
        },
    )
    if not proxy and not proxy_mail.get("ok"):
        proxy_mail["level"] = "warning"

    checks = [
        direct_mail,
        proxy_mail,
        _check("OpenAI 注册入口", lambda: _platform_authorize_probe(proxy)),
        _check(
            "ChatGPT CSRF",
            lambda: _csrf_probe(proxy),
        ),
        _check("auth.openai.com 首页", lambda: _auth_probe(proxy)),
    ]
    return {
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "proxy": _mihomo_node(proxy),
        "checks": checks,
        "ok": all(_clean(item.get("level")) != "error" for item in checks),
    }
