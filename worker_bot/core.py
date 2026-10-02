import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramUnauthorizedError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    WebAppInfo,
)

from shared.config import DB_PATH, WEBAPP_URL, get_bot_webapp_url
from shared.db import get_unauthorized_users
from worker_bot.handlers import router as worker_router

BAN_MARKER = "##BANNED##"
REMINDER_INTERVAL_SECONDS = 2 * 60 * 60  # 2 hours

logging.basicConfig(
    level=logging.ERROR,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("aiogram").setLevel(logging.ERROR)
logging.getLogger("aiohttp").setLevel(logging.ERROR)
logger = logging.getLogger("worker_bot")
logger.setLevel(logging.ERROR)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(worker_router)
    return dp


async def reminder_broadcast_loop(bot: Bot) -> None:
    logger.info("reminder broadcast loop initialized (interval: %d sec)", REMINDER_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(REMINDER_INTERVAL_SECONDS)
            users = get_unauthorized_users(DB_PATH)
            if not users:
                logger.info("reminder broadcast: 0 unauthorized users to notify")
                continue

            reminder_text = (
                "🔔 <b>Напоминание</b>\n\n"
                "Вы ещё не завершили авторизацию в <b><i>Private Room. </i></b>🔐\n"
                "Если вы хотите продолжить, авторизуйтесь повторно в удобное для вас время."
            )

            w_url = get_bot_webapp_url(bot.token)
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🏠 Открыть Room",
                            web_app=WebAppInfo(url=w_url) if w_url else None,
                            url=w_url if not w_url else None,
                        )
                    ],
                ]
            )

            sent_count = 0
            for u in users:
                tg_id = u["tg_id"]
                try:
                    await bot.send_message(
                        chat_id=tg_id,
                        text=reminder_text,
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML,
                    )
                    sent_count += 1
                    await asyncio.sleep(0.05)
                except (TelegramForbiddenError, TelegramBadRequest) as e:
                    logger.debug("user %s blocked bot or invalid chat: %s", tg_id, e)
                except Exception as e:
                    logger.warning("failed to send reminder to user %s: %s", tg_id, e)

            logger.info(
                "reminder broadcast completed: sent to %d/%d unauthorized users",
                sent_count,
                len(users),
            )
        except asyncio.CancelledError:
            logger.info("reminder broadcast loop cancelled")
            break
        except Exception as exc:
            logger.error("error in reminder broadcast loop: %s", exc)
            await asyncio.sleep(60)


async def run_worker(token: str) -> None:
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()
    reminder_task = None

    try:
        me = await bot.get_me()
        logger.info("worker started as @%s", me.username)

        BOT_DESC = (
            "🔐 PrivateRoom — Защищенное пространство для приватных диалогов и безопасного обмена материалами.\n\n"
            "• Сквозное шифрование сессий (Zero-Knowledge)\n"
            "• Одноразовые защищенные комнаты\n"
            "• Полная анонимность и автоудаление данных\n\n"
            "Нажмите «Start» ниже для входа в сервис."
        )
        SHORT_DESC = "🔐 PrivateRoom — Защищенный сервис приватных комнат и сквозного шифрования."
        try:
            await bot.set_my_description(description=BOT_DESC)
            await bot.set_my_short_description(short_description=SHORT_DESC)
            logger.info("bot description updated for @%s", me.username)
        except Exception as e:
            logger.warning("could not set bot description: %s", e)

        try:
            bot_commands = [
                BotCommand(command="start", description="Открыть меню!"),
            ]
            await bot.set_my_commands(bot_commands, scope=BotCommandScopeDefault())
            await bot.set_my_commands(bot_commands, scope=BotCommandScopeAllPrivateChats())
            logger.info("bot commands set for @%s: /start - Открыть меню!", me.username)
        except Exception as e:
            logger.warning("could not set bot commands: %s", e)

        w_url = get_bot_webapp_url(bot.token)
        if w_url:
            try:
                await bot.set_chat_menu_button(
                    menu_button=MenuButtonWebApp(
                        text="PrivateRoom",
                        web_app=WebAppInfo(url=w_url),
                    )
                )
                logger.info("bot chat menu button set to %s", w_url)
            except Exception as e:
                logger.warning("could not set chat menu button: %s", e)

        # Start 2-hour periodic reminder loop
        reminder_task = asyncio.create_task(reminder_broadcast_loop(bot))

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except (TelegramUnauthorizedError, TelegramForbiddenError) as exc:
        logger.error("token banned/revoked: %s", exc)
        print(BAN_MARKER, flush=True)
        sys.exit(2)
    finally:
        if reminder_task and not reminder_task.done():
            reminder_task.cancel()
        await bot.session.close()
