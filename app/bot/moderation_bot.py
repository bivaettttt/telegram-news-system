"""
Moderation bot — handles approve/reject callback buttons from moderation chat.
"""
from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import settings
from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.post import Post

logger = setup_logger("moderation_bot")

router = Router()


class ModerationCallback(CallbackData, prefix="mod"):
    action: str   # "approve" | "reject"
    post_id: int


def build_moderation_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Опубликовать",
            callback_data=ModerationCallback(action="approve", post_id=post_id).pack(),
        ),
        InlineKeyboardButton(
            text="❌ Отклонить",
            callback_data=ModerationCallback(action="reject", post_id=post_id).pack(),
        ),
    ]])


@router.callback_query(ModerationCallback.filter(F.action == "approve"))
async def approve_post(query: CallbackQuery, callback_data: ModerationCallback) -> None:
    db = SessionLocal()
    try:
        post = db.query(Post).filter(Post.id == callback_data.post_id).first()
        if not post:
            await query.answer("Пост не найден")
            return

        post.status = "pending"  # Will be picked up by publish_posts
        db.commit()
        await query.answer("✅ Одобрено — поставлено в очередь")
        await query.message.edit_text(
            query.message.text + "\n\n<b>✅ ОДОБРЕНО</b>",
            parse_mode="HTML",
        )
        logger.info("Post %d approved by %s", post.id, query.from_user.username)
    finally:
        db.close()


@router.callback_query(ModerationCallback.filter(F.action == "reject"))
async def reject_post(query: CallbackQuery, callback_data: ModerationCallback) -> None:
    db = SessionLocal()
    try:
        post = db.query(Post).filter(Post.id == callback_data.post_id).first()
        if not post:
            await query.answer("Пост не найден")
            return

        post.status = "rejected"
        db.commit()
        await query.answer("❌ Отклонено")
        await query.message.edit_text(
            query.message.text + "\n\n<b>❌ ОТКЛОНЕНО</b>",
            parse_mode="HTML",
        )
        logger.info("Post %d rejected by %s", post.id, query.from_user.username)
    finally:
        db.close()
