"""Entry point: `uv run findery` or `python -m findery`."""

import asyncio
import logging
import sys

from aiogram.exceptions import TelegramUnauthorizedError

from findery import __version__
from findery.bot.app import COMMANDS, BotConfigError, create_bot, create_dispatcher
from findery.bot.notifier import send_pending_alerts
from findery.cli import build_parser, run_command
from findery.config import Settings, load_settings
from findery.db.engine import SessionFactory, create_engine, create_session_factory, migrate
from findery.log import setup_logging
from findery.profiles import (
    ProfilesFileError,
    get_or_create_user,
    load_profiles_file,
    sync_profiles,
)
from findery.scheduler import run_due_profiles, run_forever, utc_now
from findery.sources import olx

logger = logging.getLogger("findery")


async def load_profiles(settings: Settings, sessions: SessionFactory) -> None:
    """Mirror the profiles file into the database. Without the file the database is left as is."""
    path = settings.profiles_file
    if not path.exists():
        logger.warning("no profiles file at %s, see profiles.example.toml", path.resolve())
        return
    configs = load_profiles_file(path)
    now = utc_now()
    async with sessions.begin() as session:
        user = await get_or_create_user(session, settings.telegram_user_id, now)
        await sync_profiles(session, user, configs, now)
    logger.info("%d profile(s) loaded from %s", len(configs), path)


async def run(settings: Settings, *, once: bool = False) -> None:
    """Application lifecycle: poll the profiles and send alerts, on schedule or just once."""
    logger.info("findery %s started, data dir: %s", __version__, settings.data_dir.resolve())
    bot = create_bot(settings)
    if bot is None:
        logger.warning("FINDERY_TELEGRAM_BOT_TOKEN is not set: polling only, no alerts")
    engine = create_engine(settings.db_path)
    sessions = create_session_factory(engine)

    async def send_alerts() -> None:
        if bot is not None:
            await send_pending_alerts(
                sessions,
                bot,
                utc_now(),
                limit=settings.alerts_per_tick,
                delay=settings.alert_delay,
            )

    try:
        await load_profiles(settings, sessions)
        async with olx.OlxClient(user_agent=settings.user_agent) as olx_client:
            sources = {olx.SOURCE: olx_client}
            if once:
                polled = await run_due_profiles(sessions, sources, settings, utc_now())
                logger.info("%d profile(s) polled", polled)
                await send_alerts()
                return
            if bot is not None:
                # Also the first request to Telegram: a wrong token fails here, at start.
                await bot.set_my_commands(COMMANDS)
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(run_forever(sessions, sources, settings, after_tick=send_alerts))
                if bot is not None:
                    dispatcher = create_dispatcher(settings, sessions)
                    tasks.create_task(
                        dispatcher.start_polling(bot, handle_signals=False, close_bot_session=False)
                    )
    finally:
        if bot is not None:
            await bot.session.close()
        await engine.dispose()


def main() -> None:
    args = build_parser().parse_args()
    settings = load_settings()
    setup_logging(settings.log_level)
    migrate(settings.db_path)
    try:
        if args.command in (None, "once"):
            asyncio.run(run(settings, once=args.command == "once"))
        else:
            sys.exit(asyncio.run(run_command(args, settings)))
    except ProfilesFileError as error:
        logger.error("profiles file is invalid: %s", error)
        sys.exit(2)
    except BotConfigError as error:
        logger.error("%s", error)
        sys.exit(2)
    except TelegramUnauthorizedError:
        logger.error("Telegram rejected FINDERY_TELEGRAM_BOT_TOKEN, check it in @BotFather")
        sys.exit(2)
    except KeyboardInterrupt:
        logger.info("stopped")


if __name__ == "__main__":
    main()
