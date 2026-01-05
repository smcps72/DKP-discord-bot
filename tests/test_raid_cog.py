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
    raid_cog.bot.db.get_raid_members = AsyncMock(return_value=[])

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
    raid_cog.bot.db.get_raid_members = AsyncMock(return_value=[])
    mock_interaction.guild.get_channel.return_value = None

    choices = await raid_cog.member_autocomplete(mock_interaction, current="any")

    assert choices == []


@pytest.mark.asyncio
async def test_process_dkp_adjustment_triggers_panel_every_fourth_change(raid_cog, mock_interaction, mock_thread):
    # Arrange
    raid = {"id": 1, "leader_id": mock_interaction.user.id, "vc_id": 999}
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)
    raid_cog.bot.db.get_raid_members = AsyncMock(return_value=[])

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

    mock_interaction.channel = mock_thread
    mock_thread.send = AsyncMock()
    mock_thread.edit = AsyncMock()

    # Act
    await raid_cog.close_raid(mock_interaction)

    # Assert: final ephemeral confirmation replaces any prior "thinking" state
    mock_interaction.followup.send.assert_any_call(
        "Raid has been closed and the raid log thread has been archived.",
        ephemeral=True,
    )


@pytest.mark.asyncio
async def test_process_dkp_adjustment_awards_all_vc_and_raid_members(raid_cog, mock_interaction, mock_thread):
    # Arrange: raid exists with one member in VC and one manually added raid member
    raid = {"id": 1, "guild_id": mock_interaction.guild.id, "leader_id": mock_interaction.user.id, "vc_id": 999}
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)

    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = 999
    member_in_vc = MagicMock(spec=discord.Member)
    member_in_vc.id = 111
    member_in_vc.bot = False
    vc.members = [member_in_vc]
    mock_interaction.guild.get_channel.return_value = vc

    manual_member = MagicMock(spec=discord.Member)
    manual_member.id = 222
    manual_member.bot = False

    # raid_members contains the manually added member (and may or may not
    # include the VC member; duplicates are de-duplicated in the logic).
    raid_cog.bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": manual_member.id}])

    def get_member_side_effect(user_id):
        if user_id == member_in_vc.id:
            return member_in_vc
        if user_id == manual_member.id:
            return manual_member
        return None

    mock_interaction.guild.get_member.side_effect = get_member_side_effect

    raid_cog.bot.db.modify_user_dkp = AsyncMock()

    # Ensure we don't depend on defer semantics
    mock_interaction.response.is_done.return_value = True

    # Act: mass award (member=None)
    await raid_cog.process_dkp_adjustment(
        mock_interaction,
        action="Award",
        amount_str="5",
        reason="Mass award",
        member=None,
    )

    # Assert: DKP was modified for both the VC member and the manual raid member
    assert raid_cog.bot.db.modify_user_dkp.await_count == 2
    raid_cog.bot.db.modify_user_dkp.assert_any_await(
        member_in_vc.id,
        mock_interaction.guild.id,
        5,
        "Award: Mass award (Raid)",
    )
    raid_cog.bot.db.modify_user_dkp.assert_any_await(
        manual_member.id,
        mock_interaction.guild.id,
        5,
        "Award: Mass award (Raid)",
    )


@pytest.mark.asyncio
async def test_raid_add_member_cmd_adds_member_to_raid(raid_cog, mock_interaction, mock_thread):
    # Arrange
    raid = {"id": 1, "guild_id": mock_interaction.guild.id, "leader_id": mock_interaction.user.id, "vc_id": 999}
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)
    raid_cog.bot.db.add_raid_member = AsyncMock()

    member = MagicMock(spec=discord.Member)
    member.id = 777
    member.bot = False
    member.mention = "@ManualRaider"

    # Act
    await raid_cog.raid_add_member_cmd.callback(raid_cog, mock_interaction, member)

    # Assert
    raid_cog.bot.db.get_raid_by_thread.assert_called_once_with(mock_thread.id)
    raid_cog.bot.db.add_raid_member.assert_called_once_with(raid["id"], member.id)
    mock_interaction.response.send_message.assert_called_once()
    args, kwargs = mock_interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    # Message content should mention the added member
    assert any("@ManualRaider" in str(arg) for arg in args) or "@ManualRaider" in str(kwargs)


@pytest.mark.asyncio
async def test_process_dkp_adjustment_allows_raid_member_not_in_vc(raid_cog, mock_interaction, mock_thread):
    # Arrange: raid exists but VC has no members; target is recorded in raid_members
    raid = {"id": 1, "guild_id": mock_interaction.guild.id, "leader_id": mock_interaction.user.id, "vc_id": 999}
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)

    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = 999
    vc.members = []
    mock_interaction.guild.get_channel.return_value = vc

    member = MagicMock(spec=discord.Member)
    member.id = 222
    member.bot = False

    raid_cog.bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": member.id}])
    raid_cog.bot.db.modify_user_dkp = AsyncMock()

    # Ensure we don't depend on defer semantics
    mock_interaction.response.is_done.return_value = True

    # Act
    await raid_cog.process_dkp_adjustment(
        mock_interaction,
        action="Award",
        amount_str="5",
        reason="Manual raid member",
        member=member,
    )

    # Assert: DKP was modified for the manually added raid member
    raid_cog.bot.db.modify_user_dkp.assert_awaited_once_with(
        member.id,
        mock_interaction.guild.id,
        5,
        "Award: Manual raid member (Raid)",
    )


@pytest.mark.asyncio
async def test_process_dkp_adjustment_rejects_member_not_in_vc_or_raid(raid_cog, mock_interaction, mock_thread):
    # Arrange: raid exists, VC has no members, and target is not recorded in raid_members
    raid = {"id": 1, "guild_id": mock_interaction.guild.id, "leader_id": mock_interaction.user.id, "vc_id": 999}
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)

    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = 999
    vc.members = []
    mock_interaction.guild.get_channel.return_value = vc

    member = MagicMock(spec=discord.Member)
    member.id = 333
    member.bot = False

    raid_cog.bot.db.get_raid_members = AsyncMock(return_value=[])
    raid_cog.bot.db.modify_user_dkp = AsyncMock()

    mock_interaction.response.is_done.return_value = True

    # Act
    await raid_cog.process_dkp_adjustment(
        mock_interaction,
        action="Award",
        amount_str="5",
        reason="Not in raid",
        member=member,
    )

    # Assert: DKP should not be modified and an error should be sent
    raid_cog.bot.db.modify_user_dkp.assert_not_awaited()
    mock_interaction.followup.send.assert_called_once()
    _args, kwargs = mock_interaction.followup.send.call_args
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed")
    assert embed is not None
    assert embed.title == "Invalid Target"
