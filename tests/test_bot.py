"""The bot against a fake Telegram: every request is recorded instead of being sent."""

import html
import logging
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendPhoto
from sqlalchemy import select

from findery.alerts import pending_alerts
from findery.bot import texts
from findery.bot.app import BotConfigError, create_bot, create_dispatcher
from findery.bot.notifier import send_pending_alerts
from findery.config import Settings
from findery.db.tables import ListingRow, ListingSnapshot, Match, Profile, User
from findery.models import Price
from findery.pipeline import run_profile
from findery.profiles import ProfileConfig, get_or_create_user, list_profiles, sync_profiles
from support import T0, FakeSource, make_listing, with_database

OWNER = 4242
STRANGER = 999
LATER = T0 + timedelta(minutes=30)
SETTINGS = Settings(
    _env_file=None, telegram_bot_token="1:test", telegram_user_id=OWNER, page_delay=0
)


class FakeTelegram(BaseSession):
    """Records the requests. `fail` maps a method class to the error it should raise once."""

    def __init__(self) -> None:
        super().__init__()
        self.requests = []
        self.fail: dict[type, Exception] = {}

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        error = self.fail.pop(type(method), None)
        if error is not None:
            raise error
        if isinstance(method, AnswerCallbackQuery):
            return True
        return {
            "message_id": len(self.requests),
            "date": 0,
            "chat": {"id": OWNER, "type": "private"},
        }

    async def close(self) -> None:
        pass

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError
        yield

    def sent(self) -> list[tuple[str, str]]:
        """(method name, text) of every request that carries a text."""
        result = []
        for method in self.requests:
            text = getattr(method, "caption", None) or getattr(method, "text", None)
            if text:
                result.append((type(method).__name__, text))
        return result


@pytest.fixture
def telegram():
    return FakeTelegram()


async def seed(sessions, listings, *, later=(), configs=None) -> None:
    """Create profiles, take `listings` as the baseline, then poll again with `later` added."""
    configs = configs or [
        ProfileConfig(name="PS5", query="playstation 5", price_from=10000, price_to=20000)
    ]
    source = FakeSource(list(listings))
    async with sessions.begin() as session:
        user = await get_or_create_user(session, OWNER, T0)
        await sync_profiles(session, user, configs, T0)
    for now, extra in ((T0, []), (LATER, list(later))):
        source.listings = [*extra, *source.listings]
        async with sessions.begin() as session:
            for profile in (await session.scalars(select(Profile))).all():
                await run_profile(session, profile, source, now, page_delay=0)


async def notify(sessions, telegram, **options) -> int:
    bot = create_bot(SETTINGS, session=telegram)
    return await send_pending_alerts(sessions, bot, LATER, delay=0, **options)


def message_update(text: str, user_id: int = OWNER) -> dict:
    user = {"id": user_id, "is_bot": False, "first_name": "U"}
    chat = {"id": user_id, "type": "private"}
    return {
        "update_id": 1,
        "message": {"message_id": 1, "date": 0, "chat": chat, "from": user, "text": text},
    }


def button_update(data: str, user_id: int = OWNER) -> dict:
    user = {"id": user_id, "is_bot": False, "first_name": "U"}
    message = {
        "message_id": 7,
        "date": 0,
        "chat": {"id": user_id, "type": "private"},
        "text": "old",
    }
    return {
        "update_id": 2,
        "callback_query": {
            "id": "1",
            "from": user,
            "chat_instance": "x",
            "message": message,
            "data": data,
        },
    }


async def feed(sessions, telegram, *updates: dict) -> None:
    bot = create_bot(SETTINGS, session=telegram)
    dispatcher = create_dispatcher(SETTINGS, sessions)
    for update in updates:
        await dispatcher.feed_raw_update(bot, update)


async def profile_state(sessions) -> list[tuple]:
    async with sessions() as session:
        rows = await session.scalars(select(Profile).order_by(Profile.id))
        return [(profile.name, profile.is_active, profile.next_run_at) for profile in rows]


# --- configuration ---


def test_no_token_means_no_bot():
    assert create_bot(Settings(_env_file=None)) is None


def test_token_without_owner_is_a_configuration_error():
    with pytest.raises(BotConfigError, match="FINDERY_TELEGRAM_USER_ID"):
        create_bot(Settings(_env_file=None, telegram_bot_token="1:test"))


def test_token_is_not_shown_when_settings_are_printed():
    assert "1:test" not in repr(SETTINGS)


def test_profiles_collected_before_the_telegram_id_was_set_move_to_the_owner(db_path):
    async def scenario(sessions):
        async with sessions.begin() as session:
            nobody = await get_or_create_user(session, 0, T0)
            await sync_profiles(session, nobody, [ProfileConfig(name="a", query="a")], T0)
        async with sessions.begin() as session:
            owner = await get_or_create_user(session, OWNER, T0)
            again = await get_or_create_user(session, OWNER, T0)
            users = (await session.scalars(select(User))).all()
            overviews = await list_profiles(session, OWNER)
            return owner.id == again.id, len(users), [o.profile.name for o in overviews]

    assert with_database(db_path, scenario) == (True, 1, ["a"])


# --- alerts ---


def test_only_new_suitable_listings_become_alerts(db_path, telegram):
    async def scenario(sessions):
        await seed(
            sessions,
            [make_listing("old", "15000")],
            later=[
                make_listing("new", "18500", title="PlayStation 5 <Slim> & диск"),
                make_listing("dear", "50000"),
                make_listing("wanted", "15000", title="Куплю PS5"),
            ],
        )
        first = await notify(sessions, telegram)
        second = await notify(sessions, telegram)
        async with sessions() as session:
            sent_at = await session.scalars(select(Match.sent_at).where(Match.sent_at.is_not(None)))
            return first, second, sent_at.all()

    first, second, sent_at = with_database(db_path, scenario)

    assert (first, second) == (1, 0)
    assert sent_at == [LATER]
    assert len(telegram.requests) == 1
    photo = telegram.requests[0]
    assert isinstance(photo, SendPhoto)
    assert photo.chat_id == OWNER
    assert photo.photo == "https://example.com/1.jpg"
    assert photo.caption.splitlines() == [
        '<a href="https://www.olx.ua/d/uk/obyavlenie/x-IDnew.html">'
        "PlayStation 5 &lt;Slim&gt; &amp; диск</a>",
        "<b>18 500 грн</b>",
        "Львів · частное лицо",
        "Профиль: PS5",
    ]
    button = photo.reply_markup.inline_keyboard[0][0]
    assert (button.text, button.url) == (
        "Открыть на OLX",
        "https://www.olx.ua/d/uk/obyavlenie/x-IDnew.html",
    )


def test_listing_without_photo_is_sent_as_text(db_path, telegram):
    async def scenario(sessions):
        await seed(sessions, [], later=[make_listing("1", "15000", photos=[])])
        return await notify(sessions, telegram)

    assert with_database(db_path, scenario) == 1
    assert [name for name, _ in telegram.sent()] == ["SendMessage"]


def test_rejected_photo_falls_back_to_text(db_path, telegram, caplog):
    telegram.fail[SendPhoto] = TelegramBadRequest(SendPhoto(chat_id=1, photo="x"), "wrong file")

    async def scenario(sessions):
        await seed(sessions, [], later=[make_listing("1", "15000")])
        return await notify(sessions, telegram)

    with caplog.at_level(logging.WARNING, logger="findery.bot.notifier"):
        assert with_database(db_path, scenario) == 1
    assert [name for name, _ in telegram.sent()] == ["SendPhoto", "SendMessage"]
    assert "photo rejected" in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        TelegramRetryAfter(SendPhoto(chat_id=1, photo="x"), "flood", retry_after=30),
        TelegramForbiddenError(SendPhoto(chat_id=1, photo="x"), "bot was blocked by the user"),
    ],
)
def test_telegram_error_leaves_the_rest_for_the_next_time(db_path, telegram, error):
    listings = [make_listing(str(n), "15000") for n in range(3)]

    async def scenario(sessions):
        await seed(sessions, [], later=listings)
        first = await notify(sessions, telegram)
        telegram.fail[SendPhoto] = error
        second = await notify(sessions, telegram, limit=1)
        async with sessions() as session:
            left = len(await pending_alerts(session, 100))
        third = await notify(sessions, telegram)
        return first, second, left, third

    telegram.fail[SendPhoto] = error
    # First call fails on the first alert; the second fails again; the third delivers all.
    assert with_database(db_path, scenario) == (0, 0, 3, 3)
    assert len(telegram.requests) == 5


def test_limit_caps_one_batch_and_order_is_oldest_first(db_path, telegram):
    listings = [make_listing(str(n), "15000", title=f"PS5 #{n}") for n in range(5)]

    async def scenario(sessions):
        await seed(sessions, [], later=listings)
        return await notify(sessions, telegram, limit=2), await notify(sessions, telegram, limit=10)

    assert with_database(db_path, scenario) == (2, 3)
    titles = [text.splitlines()[0].split(">")[1].split("<")[0] for _, text in telegram.sent()]
    assert titles == [f"PS5 #{n}" for n in range(5)]


def test_paused_profile_holds_its_alerts(db_path, telegram):
    async def scenario(sessions):
        await seed(sessions, [], later=[make_listing("1", "15000")])
        await feed(sessions, telegram, button_update("profile:pause:1"))
        held = await notify(sessions, telegram)
        await feed(sessions, telegram, button_update("profile:resume:1"))
        return held, await notify(sessions, telegram)

    assert with_database(db_path, scenario) == (0, 1)


def test_price_drop_into_the_range_is_alerted(db_path, telegram):
    async def scenario(sessions):
        await seed(sessions, [make_listing("1", "25000")], later=[])
        nothing = await notify(sessions, telegram)
        source = FakeSource([make_listing("1", "19000")])
        async with sessions.begin() as session:
            profile = (await session.scalars(select(Profile))).one()
            await run_profile(session, profile, source, LATER, page_delay=0)
        return nothing, await notify(sessions, telegram)

    assert with_database(db_path, scenario) == (0, 1)
    assert "<b>19 000 грн</b>" in telegram.sent()[0][1]


# --- texts ---


def listing_row(**fields) -> ListingRow:
    defaults = {
        "source": "olx",
        "url": "https://www.olx.ua/x",
        "title": "PS5",
        "price_amount": Decimal("18500"),
        "price_currency": "UAH",
        "price_uah": Decimal("18500"),
        "price_negotiable": False,
        "price_free": False,
        "seller_is_business": False,
        "city": "Львів",
        "district": "Сихівський",
    }
    return ListingRow(**(defaults | fields))


def test_price_line_variants():
    assert texts.price_line(listing_row()) == "<b>18 500 грн</b>"
    assert texts.price_line(listing_row(price_negotiable=True)) == "<b>18 500 грн</b> · торг"
    assert texts.price_line(listing_row(price_amount=None)) == "Цена не указана"
    assert texts.price_line(listing_row(price_amount=Decimal(0), price_free=True)) == "Бесплатно"
    usd = listing_row(
        price_amount=Decimal("9350"), price_currency="USD", price_uah=Decimal("430140.21")
    )
    assert texts.price_line(usd) == "<b>9 350 USD</b> (≈ 430 140 грн)"


def test_alert_text_always_fits_a_photo_caption():
    row = listing_row(
        title="<b>" * 400,
        url="https://www.olx.ua/" + "x" * 300,
        city="Місто" * 20,
        district="Район" * 20,
        seller_is_business=True,
    )
    text = texts.alert_text(row, "Профиль" * 10)

    # Telegram counts the text as shown, after the markup is parsed.
    shown = html.unescape(re.sub(r"<[^>]+>", "", text))
    assert len(shown) <= texts.CAPTION_LIMIT
    assert "бизнес" in text
    assert text.count("<b>") == 1  # only the price; the title is escaped


# --- commands and buttons ---


def test_start_and_help(db_path, telegram):
    with_database(
        db_path,
        lambda sessions: feed(
            sessions, telegram, message_update("/start"), message_update("/help")
        ),
    )
    assert [text for _, text in telegram.sent()] == [texts.HELP, texts.HELP]


def test_strangers_are_ignored(db_path, telegram):
    async def scenario(sessions):
        await seed(sessions, [make_listing("1", "15000")])
        await feed(
            sessions,
            telegram,
            message_update("/start", STRANGER),
            message_update("/profiles", STRANGER),
            button_update("profile:delete_yes:1", STRANGER),
        )
        return await profile_state(sessions)

    assert len(with_database(db_path, scenario)) == 1
    assert telegram.requests == []


def test_profiles_command_lists_profiles_with_buttons(db_path, telegram):
    configs = [
        ProfileConfig(name="PS5 <Львів>", query="playstation 5", price_from=10000, price_to=20000),
        ProfileConfig(name="iPhone", query="iphone 13", price_to=9000, interval_minutes=15),
    ]

    async def scenario(sessions):
        await seed(
            sessions,
            [make_listing("1", "15000"), make_listing("2", "50000")],
            later=[make_listing("3", "12000")],
            configs=configs,
        )
        await notify(sessions, telegram)
        telegram.requests.clear()
        await feed(sessions, telegram, message_update("/profiles"))

    with_database(db_path, scenario)
    first, second = telegram.requests

    lines = first.text.splitlines()
    assert lines[0] == "<b>PS5 &lt;Львів&gt;</b> — активен"
    assert lines[1] == "Запрос: playstation 5"
    assert lines[2] == "10 000–20 000 грн · каждые 30 мин"
    assert lines[3] == "Подходящих: 2, отправлено: 1"
    assert lines[4].startswith("Последний опрос: ")
    assert lines[5].startswith("Следующий: ")
    buttons = first.reply_markup.inline_keyboard[0]
    assert [(b.text, b.callback_data) for b in buttons] == [
        ("Пауза", "profile:pause:1"),
        ("Удалить", "profile:delete:1"),
    ]
    assert "до 9 000 грн · каждые 15 мин" in second.text
    assert "Подходящих: 0, отправлено: 0" in second.text


def test_profiles_command_without_profiles(db_path, telegram):
    with_database(db_path, lambda sessions: feed(sessions, telegram, message_update("/profiles")))
    assert telegram.sent() == [("SendMessage", texts.NO_PROFILES)]


def test_pause_and_resume_buttons(db_path, telegram):
    async def scenario(sessions):
        await seed(sessions, [make_listing("1", "15000")])
        await feed(sessions, telegram, button_update("profile:pause:1"))
        paused = await profile_state(sessions)
        await feed(sessions, telegram, button_update("profile:resume:1"))
        return paused, await profile_state(sessions)

    paused, resumed = with_database(db_path, scenario)

    assert paused[0][1] is False
    assert resumed[0][1] is True
    # Resuming makes the profile due at once instead of waiting out the old schedule.
    assert resumed[0][2] != paused[0][2]
    pause_edit, pause_answer, resume_edit, _ = telegram.requests
    assert (pause_edit.chat_id, pause_edit.message_id) == (OWNER, 7)
    assert "на паузе" in pause_edit.text
    assert pause_edit.reply_markup.inline_keyboard[0][0].text == "Возобновить"
    assert "Следующий" not in pause_edit.text
    assert isinstance(pause_answer, AnswerCallbackQuery)
    assert "активен" in resume_edit.text


def test_delete_asks_first_and_can_be_cancelled(db_path, telegram):
    async def scenario(sessions):
        await seed(sessions, [make_listing("1", "15000")])
        await feed(
            sessions,
            telegram,
            button_update("profile:delete:1"),
            button_update("profile:show:1"),
        )
        return await profile_state(sessions)

    assert len(with_database(db_path, scenario)) == 1
    ask, _, shown, _ = telegram.requests
    assert ask.text.startswith("Удалить профиль <b>PS5</b>?")
    assert [b.callback_data for b in ask.reply_markup.inline_keyboard[0]] == [
        "profile:delete_yes:1",
        "profile:show:1",
    ]
    assert shown.text.startswith("<b>PS5</b> — активен")


def test_confirmed_delete_removes_the_profile_and_its_verdicts_but_keeps_listings(
    db_path, telegram
):
    async def scenario(sessions):
        await seed(sessions, [make_listing("1", "15000")], later=[make_listing("2", "16000")])
        await feed(
            sessions,
            telegram,
            button_update("profile:delete_yes:1"),
            button_update("profile:pause:1"),
        )
        async with sessions() as session:
            counts = [
                len((await session.scalars(select(table))).all())
                for table in (Profile, Match, ListingRow, ListingSnapshot)
            ]
        return counts, await notify(sessions, telegram)

    assert with_database(db_path, scenario) == ([0, 0, 2, 2], 0)
    deleted, _, gone, _ = telegram.requests
    assert deleted.text == texts.deleted_text("PS5")
    assert deleted.reply_markup is None
    assert gone.text == texts.PROFILE_GONE


def test_repeated_tap_that_changes_nothing_is_not_an_error(db_path, telegram):
    telegram.fail[EditMessageText] = TelegramBadRequest(
        EditMessageText(text="x"), "message is not modified"
    )

    async def scenario(sessions):
        await seed(sessions, [make_listing("1", "15000")])
        await feed(sessions, telegram, button_update("profile:show:1"))

    with_database(db_path, scenario)
    assert isinstance(telegram.requests[-1], AnswerCallbackQuery)


def test_usd_price_is_shown_with_conversion(db_path, telegram):
    usd = Price(amount=Decimal("400"), currency="USD", amount_uah=Decimal("16800"), negotiable=True)

    async def scenario(sessions):
        await seed(sessions, [], later=[make_listing("1", "0", price=usd)])
        await notify(sessions, telegram)

    with_database(db_path, scenario)
    assert "<b>400 USD</b> (≈ 16 800 грн) · торг" in telegram.sent()[0][1]
