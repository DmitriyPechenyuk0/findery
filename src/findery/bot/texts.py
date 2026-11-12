"""Everything the bot says, in one place."""

import html
from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from findery.db.tables import ListingRow, Profile
from findery.formatting import format_amount
from findery.profiles import ProfileOverview

# Telegram limits: a photo caption and a text message.
CAPTION_LIMIT = 1024

HELP = (
    "Я слежу за объявлениями по твоим профилям поиска и присылаю новые.\n\n"
    "/profiles — профили: статус, пауза, удаление\n"
    "/help — эта справка\n\n"
    "Профили пока задаются в файле <code>profiles.toml</code>."
)
NO_PROFILES = "Профилей пока нет. Добавь их в <code>profiles.toml</code> и перезапусти findery."
PROFILE_GONE = "Этого профиля уже нет."
DELETE_NOTE = (
    "Если он остался в <code>profiles.toml</code>, при следующем запуске создастся заново."
)

SOURCE_NAMES = {"olx": "OLX"}


def _money(amount, currency: str | None) -> str:
    unit = "грн" if currency == "UAH" else (currency or "")
    return f"{format_amount(amount)} {unit}".strip()


def price_line(listing: ListingRow) -> str:
    if listing.price_amount is None:
        return "Цена не указана"
    if listing.price_free:
        return "Бесплатно"
    text = f"<b>{_money(listing.price_amount, listing.price_currency)}</b>"
    if listing.price_currency != "UAH" and listing.price_uah is not None:
        text += f" (≈ {_money(listing.price_uah, 'UAH')})"
    if listing.price_negotiable:
        text += " · торг"
    return text


def alert_text(listing: ListingRow, profile_name: str) -> str:
    place = ", ".join(part for part in (listing.city or listing.region, listing.district) if part)
    seller = "бизнес" if listing.seller_is_business else "частное лицо"
    # The title is cut so that the whole text always fits a photo caption.
    title = listing.title if len(listing.title) <= 200 else listing.title[:199] + "…"
    lines = [
        f'<a href="{html.escape(listing.url)}">{html.escape(title)}</a>',
        price_line(listing),
        html.escape(" · ".join(part for part in (place, seller) if part)),
        f"Профиль: {html.escape(profile_name)}",
    ]
    return "\n".join(lines)


def alert_keyboard(listing: ListingRow) -> InlineKeyboardMarkup:
    source = SOURCE_NAMES.get(listing.source, listing.source)
    button = InlineKeyboardButton(text=f"Открыть на {source}", url=listing.url)
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def _price_range(profile: Profile) -> str:
    low, high = profile.price_from, profile.price_to
    if low is None and high is None:
        return "любая цена"
    if low is None:
        return f"до {format_amount(high)} грн"
    if high is None:
        return f"от {format_amount(low)} грн"
    return f"{format_amount(low)}–{format_amount(high)} грн"


def _local_time(moment: datetime | None) -> str:
    return f"{moment.astimezone():%d.%m %H:%M}" if moment else "—"


def profile_text(overview: ProfileOverview) -> str:
    profile = overview.profile
    status = "активен" if profile.is_active else "на паузе"
    lines = [
        f"<b>{html.escape(profile.name)}</b> — {status}",
        f"Запрос: {html.escape(profile.query)}",
        f"{_price_range(profile)} · каждые {profile.interval_minutes} мин",
        f"Подходящих: {overview.suitable}, отправлено: {overview.sent}",
        f"Последний опрос: {_local_time(profile.last_run_at)}",
    ]
    if profile.is_active:
        lines.append(f"Следующий: {_local_time(profile.next_run_at)}")
    return "\n".join(lines)


def profile_keyboard(profile: Profile) -> InlineKeyboardMarkup:
    toggle = (
        InlineKeyboardButton(text="Пауза", callback_data=f"profile:pause:{profile.id}")
        if profile.is_active
        else InlineKeyboardButton(text="Возобновить", callback_data=f"profile:resume:{profile.id}")
    )
    delete = InlineKeyboardButton(text="Удалить", callback_data=f"profile:delete:{profile.id}")
    return InlineKeyboardMarkup(inline_keyboard=[[toggle, delete]])


def delete_confirmation_text(overview: ProfileOverview) -> str:
    name = html.escape(overview.profile.name)
    return (
        f"Удалить профиль <b>{name}</b>?\n"
        "Пропадут его результаты проверки объявлений. Сами объявления и история цен останутся."
    )


def delete_confirmation_keyboard(profile: Profile) -> InlineKeyboardMarkup:
    confirm = InlineKeyboardButton(
        text="Да, удалить", callback_data=f"profile:delete_yes:{profile.id}"
    )
    cancel = InlineKeyboardButton(text="Отмена", callback_data=f"profile:show:{profile.id}")
    return InlineKeyboardMarkup(inline_keyboard=[[confirm, cancel]])


def deleted_text(name: str) -> str:
    return f"Профиль <b>{html.escape(name)}</b> удалён.\n{DELETE_NOTE}"
