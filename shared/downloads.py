import logging
import os
import secrets
import sqlite3
import time
from typing import Optional, Tuple

from shared.config import DB_PATH, PUBLIC_DOWNLOAD_BASE_URL

logger = logging.getLogger("downloads")


def _init_downloads_db(db_path: str = DB_PATH) -> None:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_tokens (
                    token TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    user_tg_id INTEGER,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            conn.commit()
    except Exception as e:
        logger.error("Failed to init download_tokens table: %s", e)


def create_download_token(
    file_path: str,
    filename: str,
    user_tg_id: int,
    ttl_hours: int = 24,
    db_path: str = DB_PATH,
) -> Tuple[str, str]:
    """
    Creates a secure token for downloading a file directly from the VPS.
    Returns (token, full_download_url).
    """
    _init_downloads_db(db_path)
    token = secrets.token_urlsafe(24)
    now = time.time()
    expires_at = now + (ttl_hours * 3600)

    try:
        with sqlite3.connect(db_path) as conn:
            # Clean up expired tokens
            conn.execute("DELETE FROM download_tokens WHERE expires_at < ?", (now,))
            conn.execute(
                """
                INSERT INTO download_tokens (token, file_path, filename, user_tg_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token, os.path.abspath(file_path), filename, user_tg_id, now, expires_at),
            )
            conn.commit()
    except Exception as e:
        logger.error("Error creating download token: %s", e)

    base_url = PUBLIC_DOWNLOAD_BASE_URL.rstrip("/")
    download_url = f"{base_url}/api/download/{token}"
    return token, download_url


def get_download_file(token: str, db_path: str = DB_PATH) -> Optional[Tuple[str, str]]:
    """
    Validates the token and returns (file_path, filename) if valid and file exists.
    """
    _init_downloads_db(db_path)
    now = time.time()
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT file_path, filename, expires_at FROM download_tokens WHERE token = ?",
                (token,),
            )
            row = cur.fetchone()
            if not row:
                return None
            file_path, filename, expires_at = row
            if expires_at < now:
                # Expired
                conn.execute("DELETE FROM download_tokens WHERE token = ?", (token,))
                conn.commit()
                return None

            if os.path.exists(file_path):
                return file_path, filename
            return None
    except Exception as e:
        logger.error("Error retrieving download file for token %s: %s", token, e)
        return None
