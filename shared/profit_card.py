import io
import logging
import os
from typing import Optional

from aiogram import Bot
from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger("shared.profit_card")

PROFIT_TEMPLATE = "assets/profit.jpg"
DEFAULT_TEAM_LOGO = "assets/logo.png"

FONT_AMOUNT_PRIMARY = "assets/fonts/Ultra/Colossus Expanded RUS/ColossusExpandedRUS.ttf"
FONT_NICK_PRIMARY = "assets/fonts/Ultra/Colossus Expanded RUS/ColossusExpandedRUS.ttf"


def _get_font(path: str, size: int, fallbacks: list[str]) -> ImageFont.FreeTypeFont:
    if os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    for fb in fallbacks:
        if os.path.exists(fb):
            try:
                return ImageFont.truetype(fb, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


async def generate_profit_image(
    bot: Bot,
    worker_tg_id: int,
    worker_username: Optional[str],
    amount: float,
    template_path: str = PROFIT_TEMPLATE,
    default_logo_path: str = DEFAULT_TEAM_LOGO,
) -> str:
    """
    Generates customized profit image using the profit template:
    - Top-Right window: Worker Telegram Avatar (or ECHO TEAM Logo assets/logo.png if unavailable)
    - Center window: Profit amount with Colossus Expanded RUS in format: + $3 000 (Left-aligned, no stroke)
    - Bottom window: Worker nick with benzin font through @ (Left-aligned, no stroke)
    Returns the path to the saved generated image.
    """
    os.makedirs("data/temp", exist_ok=True)
    out_path = f"data/temp/profit_{worker_tg_id}_{int(amount)}.jpg"

    # 1. Try to download worker avatar (method 1: get_user_profile_photos, method 2: get_chat photo)
    avatar_path = None
    avatar_temp = f"data/temp/avatar_{worker_tg_id}.jpg"
    try:
        photos = await bot.get_user_profile_photos(user_id=worker_tg_id, limit=1)
        if photos and photos.total_count > 0 and photos.photos:
            file_id = photos.photos[0][-1].file_id
            f_info = await bot.get_file(file_id)
            if f_info.file_path:
                await bot.download_file(f_info.file_path, destination=avatar_temp)
                if os.path.exists(avatar_temp):
                    avatar_path = avatar_temp
    except Exception as e_av:
        logger.debug("Could not get profile photos for worker %s: %s", worker_tg_id, e_av)

    if not avatar_path:
        try:
            chat = await bot.get_chat(chat_id=worker_tg_id)
            if chat and chat.photo:
                f_info = await bot.get_file(chat.photo.big_file_id)
                if f_info.file_path:
                    await bot.download_file(f_info.file_path, destination=avatar_temp)
                    if os.path.exists(avatar_temp):
                        avatar_path = avatar_temp
        except Exception as e_chat:
            logger.debug("Could not get chat photo for worker %s: %s", worker_tg_id, e_chat)

    # 2. Render image using PIL
    base = Image.open(template_path).convert("RGBA")
    w, h = base.size

    # Box 1: Avatar Box (Top Right)
    avatar_box = (756, 266, 1174, 780)
    box_w = avatar_box[2] - avatar_box[0]
    box_h = avatar_box[3] - avatar_box[1]

    img_to_paste = None
    if avatar_path and os.path.exists(avatar_path):
        try:
            img_to_paste = Image.open(avatar_path).convert("RGBA")
        except Exception:
            pass

    if not img_to_paste:
        for fallback_logo in [default_logo_path, "assets/logo.png", "assets/logoWORK.jpg", "assets/avatar.jpg"]:
            if os.path.exists(fallback_logo):
                try:
                    img_to_paste = Image.open(fallback_logo).convert("RGBA")
                    break
                except Exception:
                    pass

    if img_to_paste:
        img_fitted = ImageOps.fit(img_to_paste, (box_w, box_h), Image.Resampling.LANCZOS)
        mask = Image.new("L", (box_w, box_h), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, box_w, box_h], radius=40, fill=255)
        base.paste(img_fitted, (avatar_box[0], avatar_box[1]), mask)

    draw = ImageDraw.Draw(base)

    # Load custom fonts: Colossus Expanded RUS (size 145) & Benzin (size 54)
    fallback_fonts = [
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "arial.ttf",
    ]
    font_amount = _get_font(FONT_AMOUNT_PRIMARY, 145, fallback_fonts)
    font_nick = _get_font(FONT_NICK_PRIMARY, 54, fallback_fonts)

    # Box 2: Profit Amount (format: + $3 000, Left-aligned, No stroke/outline)
    amount_int = int(amount) if amount.is_integer() else amount
    amount_str = f"{amount_int:,}".replace(",", " ") if isinstance(amount_int, int) else f"{amount:,.2f}".replace(",", " ")
    amount_text = f"+ ${amount_str}"

    amount_x = 120
    amount_y = 955
    max_amount_width = 1000

    # Dynamic auto-shrink for large amounts
    amount_font_size = 145
    font_amount = _get_font(FONT_AMOUNT_PRIMARY, amount_font_size, fallback_fonts)
    while amount_font_size > 70:
        bbox = draw.textbbox((amount_x, amount_y), amount_text, font=font_amount, anchor="lm")
        if (bbox[2] - bbox[0]) <= max_amount_width:
            break
        amount_font_size -= 5
        font_amount = _get_font(FONT_AMOUNT_PRIMARY, amount_font_size, fallback_fonts)

    # Direct clean crisp white text
    draw.text((amount_x, amount_y), amount_text, font=font_amount, fill=(255, 255, 255, 255), anchor="lm")

    # Box 3: Worker nickname in bottom box (format: @nickname, Left-aligned, No stroke/outline)
    if worker_username:
        worker_display = f"@{worker_username.lstrip('@')}"
    else:
        worker_display = f"ID: {worker_tg_id}"

    nick_x = 430
    nick_y = 1150
    max_nick_width = 670

    # Dynamic auto-shrink for long usernames
    nick_font_size = 48
    font_nick = _get_font(FONT_NICK_PRIMARY, nick_font_size, fallback_fonts)
    while nick_font_size > 22:
        bbox = draw.textbbox((nick_x, nick_y), worker_display, font=font_nick, anchor="lm")
        if (bbox[2] - bbox[0]) <= max_nick_width:
            break
        nick_font_size -= 2
        font_nick = _get_font(FONT_NICK_PRIMARY, nick_font_size, fallback_fonts)

    # Direct clean crisp white text
    draw.text((nick_x, nick_y), worker_display, font=font_nick, fill=(255, 255, 255, 255), anchor="lm")

    final_im = base.convert("RGB")
    final_im.save(out_path, "JPEG", quality=95)
    return out_path
