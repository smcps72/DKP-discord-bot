import pytest
import discord
from discord.ext import commands
from discord import app_commands
from unittest.mock import AsyncMock, MagicMock

from discord_bot.cogs.guild_bank_cog import GuildBankCog


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=commands.Bot)
    bot.db = AsyncMock()
    return bot


@pytest.fixture
def guild_bank_cog(mock_bot):
    cog = GuildBankCog(mock_bot)
    cog._update_bank_panel = AsyncMock()
    return cog


@pytest.fixture
def mock_interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 12345

    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 67890
    interaction.user.mention = "<@67890>"

    interaction.response = MagicMock(spec=discord.InteractionResponse)
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()

    interaction.followup = MagicMock(spec=discord.Webhook)
    interaction.followup.send = AsyncMock()
    return interaction


def _assert_followup_public(followup_send: AsyncMock):
    assert followup_send.call_count == 1
    _args, kwargs = followup_send.call_args
    assert kwargs.get("ephemeral") in (None, False)


@pytest.mark.asyncio
async def test_bank_deposit_cmd_success_followup_is_public(guild_bank_cog, mock_interaction, mock_bot):
    held_by = MagicMock(spec=discord.Member)
    held_by.id = 24680
    held_by.mention = "<@24680>"

    mock_bot.db.guild_bank_deposit = AsyncMock(return_value=77)

    await guild_bank_cog.bank_deposit_cmd.callback(
        guild_bank_cog,
        mock_interaction,
        item_name="Arcanite Bar",
        quantity=5,
        category=app_commands.Choice(name="Material", value="material"),
        location="Vault Tab 1",
        held_by=held_by,
        note="",
    )

    mock_interaction.response.defer.assert_called_once_with()
    _assert_followup_public(mock_interaction.followup.send)


@pytest.mark.asyncio
async def test_bank_withdraw_cmd_success_followup_is_public(guild_bank_cog, mock_interaction, mock_bot):
    mock_bot.db.guild_bank_get_item = AsyncMock(
        return_value={"id": 3, "item_name": "Arcanite Bar", "quantity": 10}
    )
    mock_bot.db.guild_bank_withdraw = AsyncMock(return_value=True)

    await guild_bank_cog.bank_withdraw_cmd.callback(
        guild_bank_cog,
        mock_interaction,
        item_id=3,
        quantity=4,
        note="",
    )

    mock_interaction.response.defer.assert_called_once_with()
    _assert_followup_public(mock_interaction.followup.send)


@pytest.mark.asyncio
async def test_process_deposit_success_followup_is_public(guild_bank_cog, mock_interaction, mock_bot):
    mock_bot.db.guild_bank_deposit = AsyncMock(return_value=88)

    await guild_bank_cog.process_deposit(
        mock_interaction,
        item_name="Greater Fire Protection Potion",
        quantity_str="2",
        category="consumable",
        location="Bank Alt",
        held_by_name="",
        note="",
    )

    mock_interaction.response.defer.assert_called_once_with()
    _assert_followup_public(mock_interaction.followup.send)


@pytest.mark.asyncio
async def test_process_withdraw_success_followup_is_public(guild_bank_cog, mock_interaction, mock_bot):
    mock_bot.db.guild_bank_get_item = AsyncMock(
        return_value={"id": 9, "item_name": "Flask of Titans", "quantity": 20}
    )
    mock_bot.db.guild_bank_withdraw = AsyncMock(return_value=True)

    await guild_bank_cog.process_withdraw(
        mock_interaction,
        item_id_str="9",
        quantity_str="5",
        note="",
    )

    mock_interaction.response.defer.assert_called_once_with()
    _assert_followup_public(mock_interaction.followup.send)


@pytest.mark.asyncio
async def test_bank_withdraw_cmd_item_not_found_followup_is_ephemeral(guild_bank_cog, mock_interaction, mock_bot):
    mock_bot.db.guild_bank_get_item = AsyncMock(return_value=None)

    await guild_bank_cog.bank_withdraw_cmd.callback(
        guild_bank_cog,
        mock_interaction,
        item_id=999,
        quantity=1,
        note="",
    )

    mock_interaction.followup.send.assert_called_once()
    _args, kwargs = mock_interaction.followup.send.call_args
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_bank_withdraw_cmd_failed_withdraw_followup_is_ephemeral(guild_bank_cog, mock_interaction, mock_bot):
    mock_bot.db.guild_bank_get_item = AsyncMock(
        return_value={"id": 7, "item_name": "Mooncloth", "quantity": 3}
    )
    mock_bot.db.guild_bank_withdraw = AsyncMock(return_value=False)

    await guild_bank_cog.bank_withdraw_cmd.callback(
        guild_bank_cog,
        mock_interaction,
        item_id=7,
        quantity=5,
        note="",
    )

    mock_interaction.followup.send.assert_called_once()
    _args, kwargs = mock_interaction.followup.send.call_args
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_process_withdraw_item_not_found_followup_is_ephemeral(guild_bank_cog, mock_interaction, mock_bot):
    mock_bot.db.guild_bank_get_item = AsyncMock(return_value=None)

    await guild_bank_cog.process_withdraw(
        mock_interaction,
        item_id_str="999",
        quantity_str="1",
        note="",
    )

    mock_interaction.followup.send.assert_called_once()
    _args, kwargs = mock_interaction.followup.send.call_args
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_process_withdraw_failed_withdraw_followup_is_ephemeral(guild_bank_cog, mock_interaction, mock_bot):
    mock_bot.db.guild_bank_get_item = AsyncMock(
        return_value={"id": 5, "item_name": "Black Lotus", "quantity": 1}
    )
    mock_bot.db.guild_bank_withdraw = AsyncMock(return_value=False)

    await guild_bank_cog.process_withdraw(
        mock_interaction,
        item_id_str="5",
        quantity_str="3",
        note="",
    )

    mock_interaction.followup.send.assert_called_once()
    _args, kwargs = mock_interaction.followup.send.call_args
    assert kwargs.get("ephemeral") is True
