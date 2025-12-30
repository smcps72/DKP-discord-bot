import pytest
from unittest.mock import AsyncMock, MagicMock

import discord

from discord_bot.cogs.raid_cog import RaidCog


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.db = AsyncMock()
    return bot


@pytest.fixture
def raid_cog(mock_bot):
    return RaidCog(mock_bot)


@pytest.fixture
def mock_thread():
    thread = MagicMock(spec=discord.Thread)
    thread.id = 555
    return thread


@pytest.fixture
def mock_interaction(mock_thread):
    interaction = MagicMock()
    interaction.channel = mock_thread
    interaction.channel_id = mock_thread.id
    interaction.guild = MagicMock()
    interaction.guild.id = 1234
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 42
    interaction.user.display_name = "Leader"

    interaction.response = AsyncMock()
    interaction.response.is_done.return_value = True
    interaction.response.defer = AsyncMock()

    interaction.followup = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_member_autocomplete_filters_bots_and_matches_current(raid_cog, mock_interaction):
    # Arrange: active raid with a VC containing members and a bot
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value={"vc_id": 123})

    vc = MagicMock()
    member1 = MagicMock(spec=discord.Member)
    member1.display_name = "specialK"
    member1.bot = False
    member1.id = 1

    member2 = MagicMock(spec=discord.Member)
    member2.display_name = "OtherUser"
    member2.bot = False
    member2.id = 2

    bot_member = MagicMock(spec=discord.Member)
    bot_member.display_name = "RaidBot"
    bot_member.bot = True
    bot_member.id = 3

    vc.members = [member1, member2, bot_member]
    mock_interaction.guild.get_channel.return_value = vc

    # Act: type part of member1's name
    choices = await raid_cog.member_autocomplete(mock_interaction, current="spec")

    # Assert: only the matching non-bot member is suggested
    assert len(choices) == 1
    choice = choices[0]
    assert choice.name == member1.display_name
    assert choice.value == str(member1.id)


@pytest.mark.asyncio
async def test_member_autocomplete_no_active_raid_returns_empty(raid_cog, mock_interaction):
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=None)

    choices = await raid_cog.member_autocomplete(mock_interaction, current="any")

    assert choices == []


@pytest.mark.asyncio
async def test_member_autocomplete_no_voice_channel_returns_empty(raid_cog, mock_interaction):
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value={"vc_id": 123})
    mock_interaction.guild.get_channel.return_value = None

    choices = await raid_cog.member_autocomplete(mock_interaction, current="any")

    assert choices == []


@pytest.mark.asyncio
async def test_process_dkp_adjustment_triggers_panel_every_fourth_change(raid_cog, mock_interaction, mock_thread):
    # Arrange
    raid = {"id": 1, "leader_id": mock_interaction.user.id, "vc_id": 999}
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)

    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = 999
    member = MagicMock(spec=discord.Member)
    member.id = 111
    member.bot = False
    vc.members = [member]
    mock_interaction.guild.get_channel.return_value = vc

    raid_cog.bot.db.modify_user_dkp = AsyncMock()
    raid_cog._send_control_panel_ephemeral = AsyncMock()

    # Ensure the interaction is considered already acknowledged so we don't
    # depend on defer semantics in this unit test.
    mock_interaction.response.is_done.return_value = True

    # Act: call adjustment 4 times for the same raid/leader/thread
    for i in range(4):
        await raid_cog.process_dkp_adjustment(
            mock_interaction,
            action="Award",
            amount_str="5",
            reason=f"Test {i}",
            member=None,
        )

    # Assert: control panel is re-shown only on the 4th adjustment
    assert raid_cog._send_control_panel_ephemeral.await_count == 1
    raid_cog._send_control_panel_ephemeral.assert_awaited_with(mock_interaction, mock_thread)


@pytest.mark.asyncio
async def test_close_raid_sends_ephemeral_confirmation(raid_cog, mock_interaction, mock_thread):
    # Arrange
    raid = {"id": 1, "guild_id": mock_interaction.guild.id, "leader_id": mock_interaction.user.id, "vc_id": 999}
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)
    raid_cog.bot.db.execute = AsyncMock()
    raid_cog.bot.db.get_guild_config = AsyncMock(return_value={})

    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = 999
    vc.members = []
    mock_interaction.guild.get_channel.return_value = vc

    mock_interaction.channel = mock_thread
    mock_thread.send = AsyncMock()
    mock_thread.edit = AsyncMock()

    # Act
    await raid_cog.close_raid(mock_interaction)

    # Assert: final ephemeral confirmation replaces any prior "thinking" state
    mock_interaction.followup.send.assert_any_call(
        "Raid has been closed and the raid voice channel cleaned up.",
        ephemeral=True,
    )
