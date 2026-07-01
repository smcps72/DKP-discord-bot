import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.database import Database
from discord_bot.voice import (
    DispatchContext,
    Dispatcher,
    IntentResult,
    build_default_registry,
)


GUILD_ID = 9001
ACTOR_ID = 42


@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    if database.pool:
        await database.pool.close()


def _ctx(db, interaction=None):
    bot = MagicMock()
    bot.db = db
    bot.get_channel.return_value = None
    if interaction is None:
        interaction = MagicMock()
        interaction.guild = None
        interaction.user = MagicMock()
        interaction.user.mention = f"<@{ACTOR_ID}>"
    return DispatchContext(
        bot=bot,
        interaction=interaction,
        guild_id=GUILD_ID,
        actor_id=ACTOR_ID,
    )


# --- DKP handlers (called directly) ---


@pytest.mark.asyncio
async def test_award_dkp_single_target(db):
    from discord_bot.voice.handlers.dkp import award_dkp

    result = await award_dkp(
        {"target": "<@555>", "amount": 25, "reason": "MVP"}, _ctx(db)
    )
    assert result.status == "ok"
    assert await db.get_user_dkp(555, GUILD_ID) == 25


@pytest.mark.asyncio
async def test_deduct_dkp_single_target(db):
    from discord_bot.voice.handlers.dkp import award_dkp, deduct_dkp

    await award_dkp({"target": "<@555>", "amount": 30}, _ctx(db))
    result = await deduct_dkp({"target": "<@555>", "amount": 10}, _ctx(db))
    assert result.status == "ok"
    assert await db.get_user_dkp(555, GUILD_ID) == 20


@pytest.mark.asyncio
async def test_award_dkp_all_uses_active_raid_roster(db):
    from discord_bot.voice.handlers.dkp import award_dkp

    raid_id = await db.execute_insert(
        "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
        (GUILD_ID, ACTOR_ID, 1, 2, 1),
    )
    await db.add_raid_member(raid_id, 101)
    await db.add_raid_member(raid_id, 102)

    result = await award_dkp({"target": "everyone", "amount": 7}, _ctx(db))
    assert result.status == "ok"
    assert result.data["count"] == 2
    assert await db.get_user_dkp(101, GUILD_ID) == 7
    assert await db.get_user_dkp(102, GUILD_ID) == 7


@pytest.mark.asyncio
async def test_award_dkp_all_no_active_raid_errors(db):
    from discord_bot.voice.handlers.dkp import award_dkp

    result = await award_dkp({"target": "all", "amount": 5}, _ctx(db))
    assert result.status == "error"


@pytest.mark.asyncio
async def test_award_dkp_all_posts_public_raid_log(db):
    from discord_bot.voice.handlers.dkp import award_dkp

    raid_id = await db.execute_insert(
        "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
        (GUILD_ID, ACTOR_ID, 1, 222, 1),
    )
    await db.add_raid_member(raid_id, 101)
    await db.add_raid_member(raid_id, 102)
    thread = MagicMock()
    thread.send = AsyncMock()
    guild = MagicMock()
    guild.get_thread.return_value = thread
    interaction = MagicMock()
    interaction.guild = guild
    interaction.user.mention = f"<@{ACTOR_ID}>"

    result = await award_dkp({"target": "everyone", "amount": 7, "reason": "Boss"}, _ctx(db, interaction))

    assert result.status == "ok"
    assert result.data["raid_log_posted"] is True
    thread.send.assert_awaited_once()
    message = thread.send.call_args.args[0]
    assert f"AI: <@{ACTOR_ID}> awarded **7 DKP** to **2** raid member(s)." in message
    assert "<@101>, <@102>" in message
    assert "Boss" in message
    rows = await db.fetchall(
        "SELECT user_id, change, reason, actor_id FROM raid_dkp_transactions WHERE raid_id = ? ORDER BY user_id",
        (raid_id,),
    )
    assert [(int(row["user_id"]), int(row["change"]), row["reason"], int(row["actor_id"])) for row in rows] == [
        (101, 7, "Boss", ACTOR_ID),
        (102, 7, "Boss", ACTOR_ID),
    ]


@pytest.mark.asyncio
async def test_deduct_dkp_single_raid_member_posts_public_raid_log(db):
    from discord_bot.voice.handlers.dkp import deduct_dkp

    raid_id = await db.execute_insert(
        "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
        (GUILD_ID, ACTOR_ID, 1, 333, 1),
    )
    await db.add_raid_member(raid_id, 555)
    await db.modify_user_dkp(555, GUILD_ID, 30, "seed")
    thread = MagicMock()
    thread.send = AsyncMock()
    guild = MagicMock()
    guild.get_thread.return_value = thread
    interaction = MagicMock()
    interaction.guild = guild
    interaction.user.mention = f"<@{ACTOR_ID}>"

    result = await deduct_dkp({"target": "<@555>", "amount": 10, "reason": "Mistake"}, _ctx(db, interaction))

    assert result.status == "ok"
    assert result.data["raid_log_posted"] is True
    assert await db.get_user_dkp(555, GUILD_ID) == 20
    thread.send.assert_awaited_once()
    message = thread.send.call_args.args[0]
    assert f"AI: <@{ACTOR_ID}> deducted **10 DKP** from <@555>." in message
    assert "Mistake" in message
    rows = await db.fetchall(
        "SELECT user_id, change, reason, actor_id FROM raid_dkp_transactions WHERE raid_id = ?",
        (raid_id,),
    )
    assert len(rows) == 1
    assert int(rows[0]["user_id"]) == 555
    assert int(rows[0]["change"]) == -10
    assert rows[0]["reason"] == "Mistake"
    assert int(rows[0]["actor_id"]) == ACTOR_ID


# --- Guild bank handlers (called directly) ---


@pytest.mark.asyncio
async def test_bank_deposit_then_withdraw(db):
    from discord_bot.voice.handlers.guild_bank import bank_deposit, bank_withdraw

    dep = await bank_deposit(
        {"item_name": "Arcanite Bar", "quantity": 10, "category": "commodities"},
        _ctx(db),
    )
    assert dep.status == "ok"
    item = await db.guild_bank_find_by_name(GUILD_ID, "arcanite bar")
    assert item is not None
    assert int(item["quantity"]) == 10

    wd = await bank_withdraw({"item_name": "Arcanite Bar", "quantity": 4}, _ctx(db))
    assert wd.status == "ok"
    item = await db.guild_bank_find_by_name(GUILD_ID, "Arcanite Bar")
    assert int(item["quantity"]) == 6


@pytest.mark.asyncio
async def test_bank_deposit_defaults_category_other(db):
    from discord_bot.voice.handlers.guild_bank import bank_deposit

    await bank_deposit({"item_name": "Mystery", "quantity": 1}, _ctx(db))
    item = await db.guild_bank_find_by_name(GUILD_ID, "Mystery")
    assert item["category"] == "other"
    assert int(item["held_by_user_id"]) == ACTOR_ID


@pytest.mark.asyncio
async def test_bank_withdraw_item_not_found(db):
    from discord_bot.voice.handlers.guild_bank import bank_withdraw

    result = await bank_withdraw({"item_name": "Nonexistent", "quantity": 1}, _ctx(db))
    assert result.status == "error"


@pytest.mark.asyncio
async def test_bank_withdraw_insufficient_quantity(db):
    from discord_bot.voice.handlers.guild_bank import bank_deposit, bank_withdraw

    await bank_deposit({"item_name": "Ore", "quantity": 3}, _ctx(db))
    result = await bank_withdraw({"item_name": "Ore", "quantity": 99}, _ctx(db))
    assert result.status == "error"
    # Quantity unchanged.
    item = await db.guild_bank_find_by_name(GUILD_ID, "Ore")
    assert int(item["quantity"]) == 3


# --- Through the dispatcher: destructive-confirm gate + real DB state ---


@pytest.mark.asyncio
async def test_dispatch_deduct_requires_confirmation_does_not_mutate(db):
    from discord_bot.voice.handlers.dkp import award_dkp

    await award_dkp({"target": "<@7>", "amount": 50}, _ctx(db))

    reg = build_default_registry()
    disp = Dispatcher(reg)
    intent = IntentResult(command_name="deduct_dkp", args={"target": "<@7>", "amount": 20})

    with patch("discord_bot.utils.is_officer", side_effect=_async_true):
        first = await disp.dispatch(intent, _ctx(db), confirmed=False)
        assert first.status == "needs_confirmation"
        # Not mutated.
        assert await db.get_user_dkp(7, GUILD_ID) == 50

        second = await disp.dispatch(intent, _ctx(db), confirmed=True)
        assert second.status == "ok"
        assert await db.get_user_dkp(7, GUILD_ID) == 30


@pytest.mark.asyncio
async def test_dispatch_award_no_confirmation_needed(db):
    reg = build_default_registry()
    disp = Dispatcher(reg)
    intent = IntentResult(command_name="award_dkp", args={"target": "<@8>", "amount": 15})

    with patch("discord_bot.utils.is_officer", side_effect=_async_true):
        result = await disp.dispatch(intent, _ctx(db), confirmed=False)
    assert result.status == "ok"
    assert await db.get_user_dkp(8, GUILD_ID) == 15


@pytest.mark.asyncio
async def test_dispatch_bank_withdraw_confirm_gate(db):
    from discord_bot.voice.handlers.guild_bank import bank_deposit

    await bank_deposit({"item_name": "Gold Bar", "quantity": 5}, _ctx(db))

    reg = build_default_registry()
    disp = Dispatcher(reg)
    intent = IntentResult(
        command_name="bank_withdraw", args={"item_name": "Gold Bar", "quantity": 2}
    )

    with patch("discord_bot.utils.is_officer", side_effect=_async_true):
        first = await disp.dispatch(intent, _ctx(db), confirmed=False)
        assert first.status == "needs_confirmation"
        item = await db.guild_bank_find_by_name(GUILD_ID, "Gold Bar")
        assert int(item["quantity"]) == 5  # untouched

        second = await disp.dispatch(intent, _ctx(db), confirmed=True)
        assert second.status == "ok"
        item = await db.guild_bank_find_by_name(GUILD_ID, "Gold Bar")
        assert int(item["quantity"]) == 3


@pytest.mark.asyncio
async def test_dispatch_records_undo_and_undo_last_reverses_dkp(db):
    reg = build_default_registry()
    disp = Dispatcher(reg)
    ctx = _ctx(db)

    with patch("discord_bot.utils.is_officer", side_effect=_async_true):
        result = await disp.dispatch(
            IntentResult(command_name="award_dkp", args={"target": "<@8>", "amount": 15}),
            ctx,
            confirmed=False,
        )
    assert result.status == "ok"
    assert result.data["undo_entry_id"]
    assert await db.get_user_dkp(8, GUILD_ID) == 15

    from discord_bot.voice.handlers.undo import undo_last_command

    undo = await undo_last_command({}, ctx)
    assert undo.status == "ok"
    assert await db.get_user_dkp(8, GUILD_ID) == 0

    second = await undo_last_command({}, ctx)
    assert second.status == "error"


@pytest.mark.asyncio
async def test_undo_last_command_is_scoped_to_actor(db):
    reg = build_default_registry()
    disp = Dispatcher(reg)
    ctx = _ctx(db)

    with patch("discord_bot.utils.is_officer", side_effect=_async_true):
        await disp.dispatch(
            IntentResult(command_name="award_dkp", args={"target": "<@8>", "amount": 15}),
            ctx,
            confirmed=False,
        )

    from discord_bot.voice.handlers.undo import undo_last_command

    other_ctx = _ctx(db)
    other_ctx.actor_id = ACTOR_ID + 1
    undo = await undo_last_command({}, other_ctx)
    assert undo.status == "error"
    assert await db.get_user_dkp(8, GUILD_ID) == 15


@pytest.mark.asyncio
async def test_dispatch_records_undo_and_undo_last_reverses_bank_deposit(db):
    reg = build_default_registry()
    disp = Dispatcher(reg)
    ctx = _ctx(db)

    with patch("discord_bot.utils.is_officer", side_effect=_async_true):
        result = await disp.dispatch(
            IntentResult(
                command_name="bank_deposit",
                args={"item_name": "Ore", "quantity": 3, "category": "commodities"},
            ),
            ctx,
            confirmed=False,
        )
    assert result.status == "ok"
    item = await db.guild_bank_find_by_name(GUILD_ID, "Ore")
    assert int(item["quantity"]) == 3

    from discord_bot.voice.handlers.undo import undo_last_command

    undo = await undo_last_command({}, ctx)
    assert undo.status == "ok"
    item = await db.guild_bank_find_by_name(GUILD_ID, "Ore")
    assert item is None


@pytest.mark.asyncio
async def test_dispatch_records_undo_and_undo_last_reverses_bank_withdraw(db):
    from discord_bot.voice.handlers.guild_bank import bank_deposit
    from discord_bot.voice.handlers.undo import undo_last_command

    ctx = _ctx(db)
    await bank_deposit({"item_name": "Ore", "quantity": 5, "category": "commodities"}, ctx)

    reg = build_default_registry()
    disp = Dispatcher(reg)
    with patch("discord_bot.utils.is_officer", side_effect=_async_true):
        result = await disp.dispatch(
            IntentResult(command_name="bank_withdraw", args={"item_name": "Ore", "quantity": 2}),
            ctx,
            confirmed=True,
        )
    assert result.status == "ok"
    item = await db.guild_bank_find_by_name(GUILD_ID, "Ore")
    assert int(item["quantity"]) == 3

    undo = await undo_last_command({}, ctx)
    assert undo.status == "ok"
    item = await db.guild_bank_find_by_name(GUILD_ID, "Ore")
    assert int(item["quantity"]) == 5


async def _async_true(*args, **kwargs):
    return True
