from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from findery.db.tables import ListingRow, ListingSnapshot, Match, Profile, User
from findery.models import Price
from findery.pipeline import BASELINE, PASSED, REJECTED, run_profile
from findery.profiles import ProfileConfig, get_or_create_user, sync_profiles
from support import T0, FakeSource, make_listing, run

LATER = T0 + timedelta(minutes=30)


def create_profile(db_path, **overrides) -> None:
    fields = {"name": "PS5", "query": "playstation 5", "price_from": 10000, "price_to": 20000}
    config = ProfileConfig(**(fields | overrides))

    async def scenario(session):
        user = await get_or_create_user(session, 1, T0)
        await sync_profiles(session, user, [config], T0)

    run(db_path, scenario)


def poll(db_path, source, now=T0, **options):
    async def scenario(session):
        profile = (await session.scalars(select(Profile))).one()
        return await run_profile(session, profile, source, now, page_delay=0, **options)

    return run(db_path, scenario)


def matches(db_path) -> dict[str, tuple[str, str | None]]:
    """external_id -> (stage, reason)"""

    async def scenario(session):
        rows = await session.execute(
            select(ListingRow.external_id, Match.stage, Match.reason).join(
                Match, Match.listing_id == ListingRow.id
            )
        )
        return {external_id: (stage, reason) for external_id, stage, reason in rows}

    return run(db_path, scenario)


def priced(external_id: str, amount: str, **overrides):
    return make_listing(external_id, amount, **overrides)


def test_first_poll_collects_everything_as_baseline(db_path):
    create_profile(db_path)
    source = FakeSource(
        [
            priced("1", "15000"),
            priced("2", "25000"),
            priced("3", "15000", title="Куплю PlayStation 5"),
            priced("4", "15000", price=None),
            priced("5", "15000", promoted=True),
        ]
    )

    stats = poll(db_path, source)

    assert stats.initial
    assert (stats.fetched, stats.new, stats.candidates) == (4, 4, 4)
    assert (stats.rejected_price, stats.rejected_stop_word, stats.passed) == (2, 1, 1)
    assert matches(db_path) == {
        "1": (BASELINE, None),
        "2": (REJECTED, "price"),
        "3": (REJECTED, "stop_word:куплю"),
        "4": (REJECTED, "no_price"),
    }


def test_query_is_sent_without_the_price_range(db_path):
    create_profile(db_path, city_id=176, private_only=True)
    source = FakeSource([priced("1", "15000")])

    poll(db_path, source)

    query, offset = source.requests[0]
    assert (query.text, query.city_id, query.private_only) == ("playstation 5", 176, True)
    assert (query.price_from, query.price_to, offset) == (None, None, 0)


def test_first_poll_reads_every_page_up_to_the_limit(db_path):
    create_profile(db_path)
    source = FakeSource([priced(str(n), "15000") for n in range(7)], page_size=2)

    stats = poll(db_path, source, initial_max_pages=3)

    assert [offset for _, offset in source.requests] == [0, 2, 4]
    assert (stats.pages, stats.fetched) == (3, 6)


def test_later_poll_passes_only_listings_new_to_the_profile(db_path):
    create_profile(db_path)
    source = FakeSource([priced("1", "15000"), priced("2", "25000")])
    poll(db_path, source)

    source.listings = [priced("3", "12000"), priced("4", "30000"), *source.listings]
    stats = poll(db_path, source, now=LATER)

    assert not stats.initial
    assert (stats.fetched, stats.new, stats.candidates, stats.passed) == (4, 2, 2, 1)
    assert matches(db_path) == {
        "1": (BASELINE, None),
        "2": (REJECTED, "price"),
        "3": (PASSED, None),
        "4": (REJECTED, "price"),
    }


def test_later_poll_stops_at_the_first_page_with_nothing_new(db_path):
    create_profile(db_path)
    known = [priced(str(n), "15000") for n in range(6)]
    source = FakeSource(known, page_size=2)
    poll(db_path, source)

    source.requests.clear()
    source.listings = [priced("new", "15000"), *known]
    stats = poll(db_path, source, now=LATER, poll_max_pages=3)

    # Page 1 has the new listing, page 2 has only known ones, page 3 is not requested.
    assert [offset for _, offset in source.requests] == [0, 2]
    assert stats.new == 1


def test_price_drop_into_the_range_overturns_a_price_rejection(db_path):
    create_profile(db_path)
    source = FakeSource([priced("1", "25000"), priced("2", "25000", title="PS5 на запчастини")])
    poll(db_path, source)

    source.listings = [priced("1", "19000"), priced("2", "19000", title="PS5 на запчастини")]
    stats = poll(db_path, source, now=LATER)

    assert (stats.changed, stats.candidates, stats.passed, stats.rejected_stop_word) == (2, 2, 1, 1)
    assert matches(db_path) == {"1": (PASSED, None), "2": (REJECTED, "stop_word:на запчастини")}


def test_price_change_does_not_reopen_other_verdicts(db_path):
    create_profile(db_path)
    source = FakeSource([priced("1", "15000"), priced("2", "15000", title="Куплю PS5")])
    poll(db_path, source)

    source.listings = [priced("1", "14000"), priced("2", "14000", title="Куплю PS5")]
    stats = poll(db_path, source, now=LATER)

    assert (stats.changed, stats.candidates) == (2, 0)
    assert matches(db_path) == {"1": (BASELINE, None), "2": (REJECTED, "stop_word:куплю")}


def test_profile_stop_words_and_foreign_currency(db_path):
    create_profile(db_path, stop_words=["VR"])
    usd = Price(amount=Decimal("400"), currency="USD", amount_uah=Decimal("16800"))
    source = FakeSource(
        [priced("1", "15000", title="Sony PlayStation VR2"), priced("2", "0", price=usd)]
    )

    poll(db_path, source)

    assert matches(db_path) == {"1": (REJECTED, "stop_word:vr"), "2": (BASELINE, None)}


def test_profile_without_price_range_accepts_any_price(db_path):
    create_profile(db_path, price_from=None, price_to=None)
    poll(db_path, FakeSource([priced("1", "5"), priced("2", "0", price=None)]))

    assert set(matches(db_path).values()) == {(BASELINE, None)}


def test_poll_schedules_the_next_one(db_path):
    create_profile(db_path, interval_minutes=45)
    poll(db_path, FakeSource([]))

    async def scenario(session):
        return (await session.scalars(select(Profile))).one()

    profile = run(db_path, scenario)
    assert profile.last_run_at == T0
    assert profile.next_run_at == T0 + timedelta(minutes=45)


def test_two_profiles_share_listings_but_judge_them_separately(db_path):
    cheap = ProfileConfig(name="cheap", query="ps5", price_to=10000)
    dear = ProfileConfig(name="dear", query="ps5", price_from=10000)

    async def setup(session):
        user = await get_or_create_user(session, 1, T0)
        await sync_profiles(session, user, [cheap, dear], T0)

    run(db_path, setup)
    source = FakeSource([priced("1", "15000")])

    async def poll_both(session):
        for profile in (await session.scalars(select(Profile).order_by(Profile.name))).all():
            await run_profile(session, profile, source, T0, page_delay=0)
        verdicts = await session.execute(
            select(Profile.name, Match.stage).join(Match, Match.profile_id == Profile.id)
        )
        listings = (await session.scalars(select(ListingRow))).all()
        snapshots = (await session.scalars(select(ListingSnapshot))).all()
        return dict(verdicts.all()), len(listings), len(snapshots)

    assert run(db_path, poll_both) == ({"cheap": REJECTED, "dear": BASELINE}, 1, 1)


def test_sync_updates_pauses_and_resumes_profiles(db_path):
    create_profile(db_path)

    def sync(configs, now):
        async def scenario(session):
            user = (await session.scalars(select(User))).one()
            await sync_profiles(session, user, configs, now)
            rows = await session.scalars(select(Profile).order_by(Profile.name))
            return {p.name: (p.is_active, p.price_to, p.next_run_at) for p in rows}

        return run(db_path, scenario)

    changed = ProfileConfig(name="PS5", query="playstation 5", price_to=30000)
    other = ProfileConfig(name="iPhone", query="iphone 13")

    assert sync([changed, other], LATER) == {
        "PS5": (True, 30000, T0),
        "iPhone": (True, None, LATER),
    }
    assert sync([other], LATER)["PS5"][0] is False
    resumed_at = LATER + timedelta(hours=1)
    assert sync([changed, other], resumed_at)["PS5"] == (True, 30000, resumed_at)
