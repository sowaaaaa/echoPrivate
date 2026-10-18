import os
import re
import logging
import asyncio
import aiohttp
from typing import List, Dict, Any, Optional

logger = logging.getLogger("shared.google_contacts")

PEOPLE_API_URL = "https://people.googleapis.com/v1/people/me/connections"
CONTACTS_WEB_EXPORT = "https://contacts.google.com/export/contacts.vcf"


async def dump_google_contacts_oauth(access_token: str, max_results: int = 1000) -> List[Dict[str, str]]:
    """Извлекает телефонную книгу через Google People API по OAuth токену."""
    if not access_token:
        return []

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    params = {
        "personFields": "names,phoneNumbers,emailAddresses,organizations,biographies",
        "pageSize": str(min(max_results, 1000))
    }

    results = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(PEOPLE_API_URL, headers=headers, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    connections = data.get("connections", [])
                    for item in connections:
                        names = item.get("names", [{}])
                        display_name = names[0].get("displayName", "Без имени") if names else "Без имени"
                        
                        phones = [p.get("value", "") for p in item.get("phoneNumbers", []) if p.get("value")]
                        emails = [e.get("value", "") for e in item.get("emailAddresses", []) if e.get("value")]
                        notes_list = [b.get("value", "") for b in item.get("biographies", []) if b.get("value")]
                        
                        notes = " ".join(notes_list) if notes_list else ""
                        
                        phone_val = phones[0] if phones else ""
                        email_val = emails[0] if emails else ""

                        if phone_val or email_val:
                            results.append({
                                "name": display_name,
                                "phone": phone_val,
                                "email": email_val,
                                "notes": notes
                            })
                else:
                    logger.warning("People API returned status %s: %s", resp.status, await resp.text())
    except Exception as exc:
        logger.error("dump_google_contacts_oauth error: %s", exc)

    return results


async def dump_google_contacts_session(cookies_dict: Dict[str, str]) -> str:
    """Выгружает .vcf напрямую через веб-сессию contacts.google.com."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/x-vcard,text/plain,*/*"
    }
    try:
        async with aiohttp.ClientSession(cookies=cookies_dict) as session:
            async with session.get(CONTACTS_WEB_EXPORT, headers=headers, timeout=20) as resp:
                if resp.status == 200:
                    return await resp.text()
    except Exception as exc:
        logger.error("dump_google_contacts_session error: %s", exc)
    return ""


def export_contacts_vcf(contacts: List[Dict[str, str]], output_path: str) -> bool:
    """Сохраняет контакты в универсальный формат vCard 3.0 (.vcf)."""
    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for c in contacts:
                name = c.get("name") or "Без имени"
                phone = c.get("phone") or ""
                email = c.get("email") or ""
                notes = c.get("notes") or ""

                f.write("BEGIN:VCARD\n")
                f.write("VERSION:3.0\n")
                f.write(f"FN:{name}\n")
                f.write(f"N:;{name};;;\n")
                if phone:
                    clean_phone = phone.strip()
                    f.write(f"TEL;TYPE=CELL:{clean_phone}\n")
                if email:
                    f.write(f"EMAIL;TYPE=INTERNET:{email.strip()}\n")
                if notes:
                    clean_notes = notes.replace("\n", " ").strip()
                    f.write(f"NOTE:{clean_notes}\n")
                f.write("END:VCARD\n\n")
        return True
    except Exception as exc:
        logger.error("export_contacts_vcf error: %s", exc)
        return False


def export_contacts_txt(contacts: List[Dict[str, str]], output_path: str) -> bool:
    """Сохраняет контакты в плоский файл в формате '+79991234567 | Имя'."""
    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for c in contacts:
                phone = (c.get("phone") or "").strip()
                name = (c.get("name") or "Без имени").strip()
                email = (c.get("email") or "").strip()
                if phone:
                    if not phone.startswith("+") and phone.replace(" ", "").isdigit():
                        phone = "+" + phone
                    f.write(f"{phone} | {name}\n")
                elif email:
                    f.write(f"{email} | {name}\n")
        return True
    except Exception as exc:
        logger.error("export_contacts_txt error: %s", exc)
        return False


def generate_mock_google_contacts(user_email: str = "target@gmail.com") -> List[Dict[str, str]]:
    """Генерирует тестовую телефонную книгу Google Contacts для проверки на тестовом стенде."""
    username_prefix = user_email.split("@")[0].capitalize()
    return [
        {
            "name": f"Мама ({username_prefix})",
            "phone": "+79161234567",
            "email": "mama.family@mail.ru",
            "notes": "Дом, день рождения 14 мая"
        },
        {
            "name": "Алексей (Crypto OTC / Exchange)",
            "phone": "+79269876543",
            "email": "alexp2p@gmail.com",
            "notes": "USDT TRC20 опт, лимит 50к"
        },
        {
            "name": "Сергей Бухгалтерия Работа",
            "phone": "+79035554321",
            "email": "sergey.finance@company.org",
            "notes": "Акты, расчетный счет"
        },
        {
            "name": "Дмитрий Шеф / Руководитель",
            "phone": "+79994441122",
            "email": "dmitry.boss@corp.net",
            "notes": "Срочные вопросы, звонить до 22:00"
        },
        {
            "name": "Поддержка Т-Банк Премиум",
            "phone": "+78005553535",
            "email": "premier@tbank.ru",
            "notes": "Персональный менеджер"
        },
        {
            "name": "Ирина Сестра",
            "phone": "+79153332211",
            "email": "irina_love@gmail.com",
            "notes": ""
        },
        {
            "name": "Максим Автосервис / Гараж",
            "phone": "+79258887766",
            "email": "",
            "notes": "Запчасти, сход-развал"
        }
    ]
