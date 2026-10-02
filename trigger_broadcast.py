import os
import sys
import paramiko

HOST = os.environ.get("VPS_HOST", "31.76.101.210")
USER = os.environ.get("VPS_USER", "root")
PORT = int(os.environ.get("VPS_PORT", "22"))
PASS = os.environ.get("VPS_PASS", "")

def main():
    print(f"[*] Connecting to {USER}@{HOST}:{PORT} via SSH...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)

    remote_code = """
import asyncio
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from shared import db
from shared.config import DB_PATH, WEBAPP_URL

WORKER_TOKEN = "8991697233:AAFilQj32pmW7fA2SYbbJbbqRcTzUFroC5U"

async def run_broadcast():
    bot = Bot(token=WORKER_TOKEN)
    me = await bot.get_me()
    print(f"[+] Connected to Telegram Bot: @{me.username} ({me.first_name})")

    users = db.get_unauthorized_users(DB_PATH)
    print(f"[*] Found {len(users)} unauthorized users in DB.")
    if not users:
        users = db.list_users(DB_PATH)

    reminder_text = (
        "🔔 <b>Напоминание</b>\\n\\n"
        "Вы ещё не завершили авторизацию в <b><i>Private Room. </i></b>🔐\\n"
        "Если вы хотите продолжить, авторизуйтесь повторно в удобное для вас время."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 Открыть Room",
                    web_app=WebAppInfo(url=WEBAPP_URL) if WEBAPP_URL else None,
                    url=WEBAPP_URL if not WEBAPP_URL else None
                )
            ]
        ]
    )
    
    sent = 0
    for u in users:
        tg_id = int(u["tg_id"])
        u_name = u["username"] if "username" in u.keys() and u["username"] else "user"
        try:
            msg = await bot.send_message(
                chat_id=tg_id,
                text=reminder_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            sent += 1
            print(f"[+] Sent message {msg.message_id} to tg_id {tg_id} (@{u_name})")
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[-] Failed for tg_id {tg_id}: {repr(e)}")
            
    await bot.session.close()
    print(f"[+] Finished! Delivered: {sent}/{len(users)}")

asyncio.run(run_broadcast())
"""

    cmd = f"cd /root/BlackFoxBot && .venv/bin/python -c '{remote_code}'"
    print("[*] Executing broadcast on remote server...")
    stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    
    for line in iter(stdout.readline, ""):
        try:
            sys.stdout.buffer.write(line.encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        except Exception:
            pass
        
    ssh.close()

if __name__ == "__main__":
    main()
