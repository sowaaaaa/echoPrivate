import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from admin_bot.fleet import WorkerFleet
from shared import db

logger = logging.getLogger("admin_bot.orchestrator")

AUTO_ROTATE_KEY = "auto_rotate"


class TokenError(Exception):
    pass


class Orchestrator:
    def __init__(self, admin_bot: Bot, admin_chat_id: int, db_path: str, auto_rotate_default: bool) -> None:
        self._bot = admin_bot
        self._chat_id = admin_chat_id
        self._db_path = db_path
        self.fleet = WorkerFleet(
            on_log=self._relay_log,
            on_banned=self._handle_banned,
            on_exit=self._handle_exit,
        )
        db.init_db(db_path)
        if db.get_setting(db_path, AUTO_ROTATE_KEY, "") == "":
            db.set_setting(db_path, AUTO_ROTATE_KEY, "true" if auto_rotate_default else "false")

    async def resume_on_startup(self) -> None:
        from shared.config import TEST_WORKER_BOT_TOKEN
        if TEST_WORKER_BOT_TOKEN:
            try:
                existing = await asyncio.to_thread(db.get_token_by_token, self._db_path, TEST_WORKER_BOT_TOKEN)
                if not existing:
                    await asyncio.to_thread(
                        db.add_token,
                        self._db_path,
                        TEST_WORKER_BOT_TOKEN,
                        "testworkechobot",
                        7491827504
                    )
                else:
                    await asyncio.to_thread(db.set_status, self._db_path, existing["id"], "active")
            except Exception as e_test_tok:
                logger.warning("Could not auto-register TEST_WORKER_BOT_TOKEN: %s", e_test_tok)

        active_tokens = await asyncio.to_thread(db.get_active_tokens, self._db_path)
        for token_row in active_tokens:
            try:
                await self.fleet.start(token_row["token"])
            except Exception as e:
                logger.error("failed to start token %s: %s", token_row["username"], e)

    async def start_mirror(self, token: str) -> None:
        await self.fleet.start(token)

    async def stop_mirror(self, token: str) -> None:
        await self.fleet.stop(token)

    async def _relay_log(self, token: str, line: str) -> None:
        pass

    async def _handle_banned(self, token: str) -> None:
        token_row = await asyncio.to_thread(db.get_token_by_token, self._db_path, token)
        if token_row is not None:
            await asyncio.to_thread(db.set_status, self._db_path, token_row["id"], "banned", "banned_at")
            owner_id = token_row["owner_tg_id"] if "owner_tg_id" in token_row.keys() else None

            # Notify the specific worker who owns this mirror
            if owner_id:
                try:
                    await self._bot.send_message(
                        owner_id,
                        "<b>❌ Ваш бот был заблокирован, создайте новое зеркало</b>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

            if not owner_id or owner_id == self._chat_id:
                await self._notify("<b>❌ Ваш бот был заблокирован, создайте новое зеркало</b>")
        else:
            await self._notify("<b>❌ Ваш бот был заблокирован, создайте новое зеркало</b>")

    async def _handle_exit(self, token: str, returncode: int) -> None:
        if returncode not in (0, -15, 15):
            logger.warning("worker process for token %s exited with code %s", token[:10], returncode)

    async def _notify(self, text: str) -> None:
        try:
            await self._bot.send_message(self._chat_id, text, parse_mode="HTML")
        except TelegramAPIError:
            logger.exception("failed to notify admin chat")
