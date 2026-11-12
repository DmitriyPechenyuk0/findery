"""Building the bot and its dispatcher."""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from findery.bot.handlers import create_router
from findery.config import Settings
from findery.db.engine import SessionFactory

COMMANDS = [
    BotCommand(command="profiles", description="Профили поиска"),
    BotCommand(command="help", description="Что умеет бот"),
]


class BotConfigError(Exception):
    """The bot settings are incomplete."""


def create_bot(settings: Settings, session: BaseSession | None = None) -> Bot | None:
    """`None` when no token is configured: the app then runs without alerts."""
    if settings.telegram_bot_token is None:
        return None
    if settings.telegram_user_id <= 0:
        raise BotConfigError(
            "FINDERY_TELEGRAM_USER_ID is not set: the bot would not know whom to answer"
        )
    return Bot(
        settings.telegram_bot_token.get_secret_value(),
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(settings: Settings, sessions: SessionFactory) -> Dispatcher:
    # `sessions` is passed to every handler that asks for it.
    dispatcher = Dispatcher(sessions=sessions)
    dispatcher.include_router(create_router(settings.telegram_user_id))
    return dispatcher
