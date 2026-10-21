import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    ChatJoinRequest,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    TelegramObject,
)

from shared import db
from shared.config import (
    ADMIN_BOT_TOKEN,
    ADMIN_CHAT_ID,
    ADMIN_CHAT_IDS,
    DB_PATH,
    MASTER_ADMIN_IDS,
    TEST_ADMIN_BOT_TOKEN,
    WORKER_CHAT_ID,
    WORKER_CHAT_INVITE_LINK,
)

logger = logging.getLogger("admin_bot.gate")
router = Router(name="team_gate")

WORK_PANEL_PHOTO = "assets/workPanel.png"
_membership_cache: Dict[int, float] = {}
_cached_invite_link: Optional[str] = WORKER_CHAT_INVITE_LINK or None


def is_admin(user_id: Optional[int]) -> bool:
    if not user_id:
        return False
    if user_id == ADMIN_CHAT_ID or user_id in ADMIN_CHAT_IDS or user_id in MASTER_ADMIN_IDS:
        return True
    return db.is_admin_user(DB_PATH, user_id)


async def get_team_invite_link(bot: Bot) -> Optional[str]:
    global _cached_invite_link
    if _cached_invite_link and _cached_invite_link.strip():
        return _cached_invite_link.strip()

    bots_to_try = [bot]
    if ADMIN_BOT_TOKEN and (not bot or bot.token != ADMIN_BOT_TOKEN):
        bots_to_try.append(Bot(token=ADMIN_BOT_TOKEN))

    for b in bots_to_try:
        try:
            invite = await b.create_chat_invite_link(
                chat_id=WORKER_CHAT_ID,
                creates_join_request=True,
                name="ECHO TEAM Worker Gate",
            )
            if invite and invite.invite_link:
                _cached_invite_link = invite.invite_link
                logger.info("Created new join-request invite link for chat %s: %s", WORKER_CHAT_ID, _cached_invite_link)
                if b != bot:
                    await b.session.close()
                return _cached_invite_link
        except Exception as exc:
            logger.debug("Failed creating join request link for chat %s via %s: %s", WORKER_CHAT_ID, getattr(b, "id", None), exc)

        try:
            chat = await b.get_chat(WORKER_CHAT_ID)
            if chat.invite_link:
                _cached_invite_link = chat.invite_link
                if b != bot:
                    await b.session.close()
                return _cached_invite_link
        except Exception as exc:
            logger.debug("Failed getting chat invite_link via %s: %s", getattr(b, "id", None), exc)

        if b != bot:
            try:
                await b.session.close()
            except Exception:
                pass

    return None


async def is_team_member(bot: Bot, user_id: int, bypass_cache: bool = False) -> bool:
    if is_admin(user_id):
        return True

    now = time.time()
    if not bypass_cache:
        cached_exp = _membership_cache.get(user_id)
        if cached_exp and cached_exp > now:
            return True

    member = None
    bots_to_try = [bot]
    if ADMIN_BOT_TOKEN and (not bot or bot.token != ADMIN_BOT_TOKEN):
        bots_to_try.append(Bot(token=ADMIN_BOT_TOKEN))

    for b in bots_to_try:
        try:
            member = await b.get_chat_member(chat_id=WORKER_CHAT_ID, user_id=user_id)
            if b != bot:
                await b.session.close()
            break
        except Exception as exc:
            logger.debug("get_chat_member check failed for user %s via %s: %s", user_id, getattr(b, "id", None), exc)
            if b != bot:
                try:
                    await b.session.close()
                except Exception:
                    pass

    if not member:
        _membership_cache.pop(user_id, None)
        return False

    status = member.status
    if status in ("creator", "administrator", "member"):
        _membership_cache[user_id] = now + 120
        return True
    if status == "restricted":
        is_m = getattr(member, "is_member", False)
        if is_m:
            _membership_cache[user_id] = now + 120
            return True
        _membership_cache.pop(user_id, None)
        return False

    _membership_cache.pop(user_id, None)
    return False


def get_gate_text() -> str:
    return "Чтобы получить доступ к боту, войдите в чат"


def get_gate_keyboard(invite_link: Optional[str] = None) -> InlineKeyboardMarkup:
    link = invite_link or "https://t.me/+igNvlIJQtaNiNjgy"
    buttons = [
        [InlineKeyboardButton(text="Подать заявку", url=link)],
        [InlineKeyboardButton(text="Проверить заявку", callback_data="gate_check_sub")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_gate_view(
    target: Message | CallbackQuery,
    bot: Bot,
    alert_text: Optional[str] = None,
) -> None:
    invite_link = await get_team_invite_link(bot)
    text = get_gate_text()
    keyboard = get_gate_keyboard(invite_link)

    if isinstance(target, CallbackQuery):
        if alert_text:
            try:
                await target.answer(alert_text, show_alert=True)
            except Exception:
                pass
        else:
            try:
                await target.answer()
            except Exception:
                pass

        msg = target.message
        if msg:
            if msg.photo:
                try:
                    await msg.delete()
                except Exception:
                    pass
            else:
                try:
                    await msg.edit_text(text=text, reply_markup=keyboard)
                    return
                except Exception:
                    pass

        try:
            await bot.send_message(
                chat_id=target.from_user.id,
                text=text,
                reply_markup=keyboard,
            )
        except Exception as exc:
            logger.debug("Failed sending gate message: %s", exc)
    else:
        await target.answer(
            text=text,
            reply_markup=keyboard,
        )


class TeamGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        bot: Bot = data.get("bot") or getattr(event, "bot", None)

        if not bot:
            return await handler(event, data)

        if isinstance(event, Message):
            if event.chat.type != "private":
                return await handler(event, data)

            user_id = event.from_user.id if event.from_user else 0
            if is_admin(user_id):
                return await handler(event, data)

            is_ok = await is_team_member(bot, user_id)
            if not is_ok:
                await send_gate_view(event, bot)
                return

        elif isinstance(event, CallbackQuery):
            if event.data == "gate_check_sub":
                return await handler(event, data)

            if event.message and event.message.chat and event.message.chat.type != "private":
                return await handler(event, data)

            user_id = event.from_user.id if event.from_user else 0
            if is_admin(user_id):
                return await handler(event, data)

            is_ok = await is_team_member(bot, user_id)
            if not is_ok:
                await send_gate_view(event, bot, alert_text="⛔️ Доступ ограничен! Вы должны состоять в чате команды.")
                return

        return await handler(event, data)


@router.callback_query(F.data == "gate_check_sub")
async def cb_gate_check_sub(callback: CallbackQuery, bot: Bot) -> None:

    user_id = callback.from_user.id if callback.from_user else 0
    is_ok = await is_team_member(bot, user_id, bypass_cache=True)
    if not is_ok:
        await callback.answer(
            "❌ Ваша заявка ещё не принята. Отправьте заявку в чат команды и дождитесь подтверждения администратора.",
            show_alert=True,
        )
        return

    await callback.answer("✅ Заявка одобрена! Доступ к ECHO TEAM открыт.", show_alert=True)

    from admin_bot.handlers import WORKER_WELCOME_TEXT, get_worker_keyboard, _send_or_edit_menu
    if callback.from_user:
        db.get_or_create_worker(DB_PATH, user_id, callback.from_user.username)
    is_adm = is_admin(user_id)
    await _send_or_edit_menu(
        callback,
        WORKER_WELCOME_TEXT,
        get_worker_keyboard(is_admin_flag=is_adm),
        photo_path=WORK_PANEL_PHOTO,
    )


@router.message(Command("setchatlink"))
async def cmd_set_chat_link(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not is_admin(user_id):
        return

    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        current = await get_team_invite_link(bot)
        await message.reply(
            f"Текущая ссылка на чат команды:\n<code>{current or 'не задана'}</code>\n\n"
            f"Использование: <code>/setchatlink https://t.me/+...</code>",
            parse_mode="HTML",
        )
        return

    new_link = parts[1].strip()
    global _cached_invite_link
    _cached_invite_link = new_link
    await message.reply(f"✅ Ссылка на чат команды обновлена:\n<code>{new_link}</code>", parse_mode="HTML")


@router.chat_member()
async def on_team_chat_member_updated(event: ChatMemberUpdated, bot: Bot) -> None:
    if event.chat.id != WORKER_CHAT_ID:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    user = event.new_chat_member.user
    user_id = user.id

    if new_status in ("member", "administrator") and old_status in ("left", "kicked"):
        _membership_cache[user_id] = time.time() + 300
        logger.info("User %s (@%s) joined team chat %s", user_id, user.username, WORKER_CHAT_ID)
        try:
            from admin_bot.handlers import WORKER_WELCOME_TEXT, get_worker_keyboard
            if user:
                db.get_or_create_worker(DB_PATH, user_id, user.username)
            is_adm = is_admin(user_id)
            keyboard = get_worker_keyboard(is_admin_flag=is_adm)
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 <b>Ваша заявка в ECHO TEAM одобрена!</b>\n\n"
                    "Вам открыт доступ к рабочему боту и управлению зеркалами.\n"
                    "Нажмите /start или используйте меню ниже."
                ),
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.debug("Failed notifying user %s about acceptance: %s", user_id, exc)

    elif new_status in ("left", "kicked"):
        _membership_cache.pop(user_id, None)
        logger.info("User %s (@%s) left team chat %s, access revoked", user_id, user.username, WORKER_CHAT_ID)


@router.chat_join_request()
async def on_team_chat_join_request(event: ChatJoinRequest, bot: Bot) -> None:
    if event.chat.id != WORKER_CHAT_ID:
        return
    logger.info(
        "Chat join request received in team chat %s from user %s (@%s)",
        WORKER_CHAT_ID,
        event.from_user.id,
        event.from_user.username,
    )
