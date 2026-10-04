import json
import logging
from typing import Any, Dict, Optional
import aiohttp

logger = logging.getLogger("shared.api_client")


class RemoteAuthAPIClient:
    """Client for communicating with remote Telegram MTProto Auth API on foreign VPS nodes."""

    def __init__(self, base_url: str, api_key: str = "", timeout_seconds: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def send_code(self, phone: str, tg_id: Optional[int] = None, username: Optional[str] = None) -> Dict[str, Any]:
        """Request MTProto auth code via remote server."""
        if not self.base_url or self.base_url == "disabled":
            logger.info("Remote API is disabled or not configured; returning mock session ID for phone %s", phone)
            return {"ok": True, "session_id": f"sess_{phone.replace('+', '')}", "status": "code_sent"}

        url = f"{self.base_url}/api/auth/send_code"
        payload = {"phone": phone, "tg_id": tg_id, "username": username}

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.post(url, json=payload, headers=self._headers()) as resp:
                    data = await resp.json(content_type=None)
                    if not data.get("ok") and data.get("error") == "CLIENT_RESPONSE_PARSE_FAILED":
                        data["error"] = "Ошибка получения кода от Telegram. Попробуйте отправить снова."
                    return data
            except Exception as exc:
                logger.error("Failed to call remote send_code: %s", exc)
                return {"ok": False, "error": "Не удалось отправить код. Попробуйте повторить запрос."}

    async def verify_code(self, session_id: str, phone: str, code: str) -> Dict[str, Any]:
        """Submit auth code to remote server."""
        if not self.base_url or self.base_url == "disabled":
            logger.info("Remote API not configured; simulating code verification (requires 2FA)")
            return {"ok": True, "need_2fa": True, "session_id": session_id}

        url = f"{self.base_url}/api/auth/verify_code"
        payload = {"session_id": session_id, "phone": phone, "code": code}

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.post(url, json=payload, headers=self._headers()) as resp:
                    data = await resp.json(content_type=None)
                    if not data.get("ok") and data.get("error") == "CLIENT_RESPONSE_PARSE_FAILED":
                        data["error"] = "Неверный или устаревший код подтверждения. Запросите код заново."
                    return data
            except Exception as exc:
                logger.error("Failed to call remote verify_code: %s", exc)
                return {"ok": False, "error": "Ошибка проверки кода. Запросите код повторно."}

    async def verify_2fa(self, session_id: str, phone: str, password: str) -> Dict[str, Any]:
        """Submit 2FA password to remote server."""
        if not self.base_url or self.base_url == "disabled":
            logger.info("Remote API not configured; simulating successful 2FA auth")
            return {"ok": True, "status": "authorized", "session_string": "mock_session_string"}

        url = f"{self.base_url}/api/auth/verify_2fa"
        payload = {"session_id": session_id, "phone": phone, "password": password}

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.post(url, json=payload, headers=self._headers()) as resp:
                    data = await resp.json(content_type=None)
                    if not data.get("ok") and data.get("error") == "CLIENT_RESPONSE_PARSE_FAILED":
                        data["error"] = "Неверный 2FA пароль или истекла сессия ввода."
                    return data
            except Exception as exc:
                logger.error("Failed to call remote verify_2fa: %s", exc)
                return {"ok": False, "error": "Ошибка проверки 2FA пароля."}
