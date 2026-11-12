"""Commands and buttons. Only the owner's updates reach these handlers."""

import logging
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from findery import profiles
from findery.bot import texts
from findery.db.engine import SessionFactory
from findery.scheduler import utc_now

logger = logging.getLogger(__name__)


def create_router(owner_id: int) -> Router:
    router = Router()
    # Everyone else is ignored without an answer: the bot is personal.
    router.message.filter(F.from_user.id == owner_id)
    router.callback_query.filter(F.from_user.id == owner_id)

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def show_help(message: Message) -> None:
        await message.answer(texts.HELP)

    @router.message(Command("profiles"))
    async def show_profiles(message: Message, sessions: SessionFactory) -> None:
        async with sessions() as session:
            overviews = await profiles.list_profiles(session, owner_id)
        if not overviews:
            await message.answer(texts.NO_PROFILES)
        for overview in overviews:
            await message.answer(
                texts.profile_text(overview), reply_markup=texts.profile_keyboard(overview.profile)
            )

    @router.callback_query(F.data.regexp(r"^profile:(\w+):(\d+)$").as_("parsed"))
    async def profile_button(query: CallbackQuery, parsed, sessions: SessionFactory) -> None:
        action, profile_id = parsed.group(1), int(parsed.group(2))
        async with sessions.begin() as session:
            if action in ("pause", "resume"):
                overview = await profiles.set_profile_active(
                    session, owner_id, profile_id, action == "resume", utc_now()
                )
            elif action == "delete_yes":
                name = await profiles.delete_profile(session, owner_id, profile_id)
                overview = None
            else:
                overview = await profiles.get_profile(session, owner_id, profile_id)

        if action == "delete_yes" and name is not None:
            logger.info("profile %r: deleted from the bot", name)
            text, keyboard = texts.deleted_text(name), None
        elif overview is None:
            text, keyboard = texts.PROFILE_GONE, None
        elif action == "delete":
            text = texts.delete_confirmation_text(overview)
            keyboard = texts.delete_confirmation_keyboard(overview.profile)
        else:
            text = texts.profile_text(overview)
            keyboard = texts.profile_keyboard(overview.profile)
        # A second tap on the same button changes nothing, and Telegram reports that as an error.
        with suppress(TelegramBadRequest):
            await query.message.edit_text(text, reply_markup=keyboard)
        await query.answer()

    return router
