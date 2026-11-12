"""Delivers pending alerts to Telegram."""

import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter

from findery.alerts import Alert, mark_sent, pending_alerts
from findery.bot import texts
from findery.db.engine import SessionFactory

logger = logging.getLogger(__name__)


async def _send(bot: Bot, alert: Alert) -> None:
    listing = alert.listing
    text = texts.alert_text(listing, alert.profile_name)
    keyboard = texts.alert_keyboard(listing)
    if listing.photos:
        try:
            await bot.send_photo(
                alert.telegram_id, listing.photos[0], caption=text, reply_markup=keyboard
            )
            return
        except TelegramBadRequest as error:
            # Telegram could not fetch or accept the picture; the listing still matters.
            logger.warning("listing %s: photo rejected (%s), sending text", listing.id, error)
    await bot.send_message(
        alert.telegram_id, text, reply_markup=keyboard, disable_web_page_preview=True
    )


async def send_pending_alerts(
    sessions: SessionFactory, bot: Bot, now: datetime, *, limit: int = 20, delay: float = 1.0
) -> int:
    """Send up to `limit` alerts, oldest first. Returns how many were delivered.

    Each alert is marked as sent right after its delivery. On a Telegram error the
    rest is left for the next call, so nothing is lost and nothing is sent twice.
    """
    async with sessions() as session:
        alerts = await pending_alerts(session, limit)
    sent = 0
    for alert in alerts:
        if sent:
            await asyncio.sleep(delay)
        try:
            await _send(bot, alert)
        except TelegramRetryAfter as error:
            logger.warning("Telegram asks to slow down for %s s", error.retry_after)
            break
        except TelegramAPIError as error:
            logger.error("alert for listing %s was not sent: %s", alert.listing.id, error)
            break
        async with sessions.begin() as session:
            await mark_sent(session, alert.match_id, now)
        sent += 1
    if alerts:
        logger.info("alerts: %d sent, %d left for later", sent, len(alerts) - sent)
    return sent
