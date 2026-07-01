import pytest

from discord_bot.voice.tiering import (
    FREE,
    PAID,
    VALID_TIERS,
    VOICE_MINUTE_LIMITS,
    Entitlements,
    load_entitlements,
    reset_if_new_period,
    tier_from_license,
    usage_state,
    voice_allowed,
)
from discord_bot.database import Database

import licensing_server.server as licensing_server


# --- Pure helper tests ------------------------------------------------------

def test_constants():
    assert FREE == "free"
    assert PAID == "paid"
    assert VALID_TIERS == {FREE, PAID}
    assert VOICE_MINUTE_LIMITS == {FREE: 0, PAID: 1000}


def test_voice_allowed():
    assert voice_allowed(PAID) is True
    assert voice_allowed(FREE) is False
    assert voice_allowed("nonsense") is False


def test_tier_from_license_paid():
    assert tier_from_license({"status": "active", "tier": "paid"}) == PAID


def test_tier_from_license_free_default():
    assert tier_from_license({"status": "active", "tier": "free"}) == FREE


def test_tier_from_license_unknown_tier():
    assert tier_from_license({"status": "active", "tier": "platinum"}) == FREE


def test_tier_from_license_missing_key():
    assert tier_from_license({"status": "active"}) == FREE


def test_tier_from_license_lapsed_loses_voice():
    # A lapsed paid subscription must lose voice.
    assert tier_from_license({"status": "lapsed", "tier": "paid"}) == FREE


def test_tier_from_license_non_dict():
    assert tier_from_license(None) == FREE


# --- usage_state tests ------------------------------------------------------

def test_usage_state_ok_below_75():
    state = usage_state(700, 1000)
    assert state["level"] == "ok"
    assert state["remaining"] == 300
    assert state["pct"] == pytest.approx(0.7)


def test_usage_state_warn_at_exactly_75():
    state = usage_state(750, 1000)
    assert state["level"] == "warn"
    assert state["remaining"] == 250


def test_usage_state_warn_between():
    assert usage_state(999, 1000)["level"] == "warn"


def test_usage_state_capped_at_exactly_100():
    state = usage_state(1000, 1000)
    assert state["level"] == "capped"
    assert state["remaining"] == 0


def test_usage_state_over_100():
    state = usage_state(1500, 1000)
    assert state["level"] == "capped"
    assert state["remaining"] == 0


def test_usage_state_free_limit_zero_no_usage():
    state = usage_state(0, 0)
    assert state["level"] == "ok"
    assert state["remaining"] == 0
    assert state["pct"] == 0.0


def test_usage_state_free_limit_zero_with_usage():
    state = usage_state(5, 0)
    assert state["level"] == "capped"
    assert state["remaining"] == 0


def test_usage_state_no_div_by_zero():
    # Should not raise even though limit is 0.
    usage_state(10, 0)


# --- DB method tests (real temp Database) -----------------------------------

@pytest.mark.asyncio
async def test_set_voice_tier_and_get_config():
    db = Database(":memory:")
    try:
        await db.connect()
        await db.execute("INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (1,))
        await db.set_voice_tier(1, PAID)
        cfg = await db.get_guild_config(1)
        assert cfg["voice_tier"] == PAID
    finally:
        if db.pool:
            await db.pool.close()


@pytest.mark.asyncio
async def test_add_voice_minutes_accumulates():
    db = Database(":memory:")
    try:
        await db.connect()
        total = await db.add_voice_minutes(2, 10)
        assert total == 10
        total = await db.add_voice_minutes(2, 5)
        assert total == 15
        cfg = await db.get_guild_config(2)
        assert cfg["voice_minutes_used"] == 15
    finally:
        if db.pool:
            await db.pool.close()


@pytest.mark.asyncio
async def test_reset_voice_minutes():
    db = Database(":memory:")
    try:
        await db.connect()
        await db.add_voice_minutes(3, 100)
        await db.execute("UPDATE guilds SET voice_warn_75_sent = 1, voice_warn_100_sent = 1 WHERE guild_id = ?", (3,))
        await db.reset_voice_minutes(3)
        cfg = await db.get_guild_config(3)
        assert cfg["voice_minutes_used"] == 0
        assert cfg["voice_warn_75_sent"] == 0
        assert cfg["voice_warn_100_sent"] == 0
    finally:
        if db.pool:
            await db.pool.close()


@pytest.mark.asyncio
async def test_load_entitlements_paid():
    db = Database(":memory:")
    try:
        await db.connect()
        await db.execute("INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (4,))
        await db.set_voice_tier(4, PAID)
        await db.add_voice_minutes(4, 750)
        ent = await load_entitlements(db, 4)
        assert isinstance(ent, Entitlements)
        assert ent.tier == PAID
        assert ent.voice_allowed is True
        assert ent.minutes_limit == 1000
        assert ent.minutes_used == 750
        assert ent.level == "warn"
        assert ent.remaining == 250
    finally:
        if db.pool:
            await db.pool.close()


@pytest.mark.asyncio
async def test_load_entitlements_free_default():
    db = Database(":memory:")
    try:
        await db.connect()
        await db.execute("INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (5,))
        ent = await load_entitlements(db, 5)
        assert ent.tier == FREE
        assert ent.voice_allowed is False
        assert ent.minutes_limit == 0
        assert ent.level == "ok"
    finally:
        if db.pool:
            await db.pool.close()


@pytest.mark.asyncio
async def test_reset_if_new_period_resets_on_rollover():
    db = Database(":memory:")
    try:
        await db.connect()
        await db.execute("INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (6,))
        await db.add_voice_minutes(6, 900)
        await db.execute(
            "UPDATE guilds SET voice_warn_75_sent = 1 WHERE guild_id = ?", (6,)
        )

        # First call in a fresh period: stored period is NULL -> resets + records.
        did = await reset_if_new_period(db, 6, "2026-06")
        assert did is True
        cfg = await db.get_guild_config(6)
        assert cfg["voice_minutes_used"] == 0
        assert cfg["voice_warn_75_sent"] == 0
        assert cfg["voice_minutes_period"] == "2026-06"

        # Same period again: no reset.
        await db.add_voice_minutes(6, 50)
        did = await reset_if_new_period(db, 6, "2026-06")
        assert did is False
        cfg = await db.get_guild_config(6)
        assert cfg["voice_minutes_used"] == 50

        # New period: resets again.
        did = await reset_if_new_period(db, 6, "2026-07")
        assert did is True
        cfg = await db.get_guild_config(6)
        assert cfg["voice_minutes_used"] == 0
        assert cfg["voice_minutes_period"] == "2026-07"
    finally:
        if db.pool:
            await db.pool.close()


# --- Licensing server test --------------------------------------------------

def test_licensing_server_returns_paid_tier():
    client = licensing_server.app.test_client()
    resp = client.post(
        "/check_license",
        json={"license_key": "D1ZmwnrP91Lan-PLRQ7tBEYYYod7Eypos_KBKvwaHLg"},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["status"] == "active"
    assert payload["tier"] == "paid"
