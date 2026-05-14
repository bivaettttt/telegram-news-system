from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_source_keyboard(original_url: str | None) -> InlineKeyboardMarkup | None:
    if not original_url:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📰 Читать полностью", url=original_url)]
        ]
    )


async def send_text_post(
    bot: Bot,
    chat_id: int,
    post_text_html: str,
    original_url: str | None = None,
    disable_preview: bool = True,
) -> int:
    message = await bot.send_message(
        chat_id=chat_id,
        text=post_text_html,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=disable_preview,
        reply_markup=build_source_keyboard(original_url),
    )
    return message.message_id