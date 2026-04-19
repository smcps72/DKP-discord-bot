import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from discord_bot.cogs.raid_cog import RaidCog


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.db = AsyncMock()
    bot.db.is_raid_member_excluded = AsyncMock(return_value=False)
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

    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=True)
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()

    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_member_autocomplete_filters_bots_and_matches_current(raid_cog, mock_interaction):
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

    # Option B: autocomplete uses approved raid_members only.
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 123})
    raid_cog.bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": member1.id}, {"user_id": member2.id}, {"user_id": bot_member.id}])

    def get_member_side_effect(user_id):
        if user_id == member1.id:
            return member1
        if user_id == member2.id:
            return member2
        if user_id == bot_member.id:
            return bot_member
        return None

    mock_interaction.guild.get_member.side_effect = get_member_side_effect

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
    member = MagicMock(spec=discord.Member)
    member.id = 111
    member.bot = False
    member.mention = f"<@{member.id}>"
    raid_cog.bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": member.id}])
    mock_interaction.guild.get_channel.return_value = None
    mock_interaction.guild.get_member.side_effect = lambda uid: member if uid == member.id else None

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
async def test_rename_raid_thread_success_and_inactive_rejection(raid_cog, mock_interaction, mock_thread):
    # Arrange: active raid and user is raid leader
    raid = {"id": 1, "guild_id": mock_interaction.guild.id, "leader_id": mock_interaction.user.id, "is_active": 1, "thread_id": 555}
    raid_cog.bot.db.fetchone = AsyncMock(return_value=raid)
    mock_thread.edit = AsyncMock()
    mock_interaction.guild.get_thread.return_value = mock_thread

    # Act: rename active raid
    await raid_cog.rename_raid_thread(mock_interaction, raid["id"], "New Name")

    # Assert: thread is renamed and success message sent
    args, kwargs = mock_thread.edit.call_args
    assert "name" in kwargs
    assert "New Name" in kwargs["name"]
    mock_interaction.followup.send.assert_called_with("Thread renamed successfully.", ephemeral=True)

    # Arrange: inactive raid
    inactive_raid = {**raid, "is_active": 0}
    raid_cog.bot.db.fetchone = AsyncMock(return_value=inactive_raid)
    mock_interaction.reset_mock()

    # Act: attempt rename on inactive raid
    await raid_cog.rename_raid_thread(mock_interaction, raid["id"], "New Name")

    # Assert: rename rejected
    mock_thread.edit.assert_not_called()
    mock_interaction.followup.send.assert_called_with("This raid is no longer active.", ephemeral=True)

@pytest.mark.asyncio
async def test_close_raid_posts_summary_in_completed_channel(raid_cog, mock_interaction, mock_thread):
    # Arrange
    raid = {
        "id": 1,
        "guild_id": mock_interaction.guild.id,
        "leader_id": mock_interaction.user.id,
        "vc_id": 999,
        "announcement_message_id": 222,
    }
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)
    raid_cog.bot.db.execute = AsyncMock()
    raid_cog.bot.db.get_guild_config = AsyncMock(return_value={"completed_raid_channel_id": 111, "raid_channel_id": 333})

    mock_interaction.channel = mock_thread
    mock_thread.send = AsyncMock()
    mock_thread.edit = AsyncMock()
    mock_thread.mention = "#archived-thread"
    mock_interaction.user.mention = "@User"

    mock_completed_channel = MagicMock()
    mock_completed_channel.send = AsyncMock()
    mock_active_channel = MagicMock(spec=discord.TextChannel)
    mock_announcement_msg = MagicMock(spec=discord.Message)
    mock_announcement_msg.delete = AsyncMock()
    mock_active_channel.fetch_message = AsyncMock(return_value=mock_announcement_msg)

    def get_channel_side_effect(cid):
        if cid == 111:
            return mock_completed_channel
        if cid == 333:
            return mock_active_channel
        return None

    mock_interaction.guild.get_channel.side_effect = get_channel_side_effect

    # Act
    await raid_cog.close_raid(mock_interaction)

    # Assert: summary is posted in completed raids channel
    mock_completed_channel.send.assert_called_once()
    args, kwargs = mock_completed_channel.send.call_args
    embed = kwargs.get("embed")
    assert embed is not None
    assert "Raid Completed" in embed.title
    assert mock_thread.mention in embed.description
    assert mock_interaction.user.mention in embed.description


@pytest.mark.asyncio
async def test_process_dkp_adjustment_awards_all_vc_and_raid_members(raid_cog, mock_interaction, mock_thread):
    # Arrange: Option B mass award uses raid_members only.
    raid = {"id": 1, "guild_id": mock_interaction.guild.id, "leader_id": mock_interaction.user.id, "vc_id": 999}
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)

    manual_member = MagicMock(spec=discord.Member)
    manual_member.id = 222
    manual_member.bot = False
    manual_member.mention = f"<@{manual_member.id}>"

    member_in_vc = MagicMock(spec=discord.Member)
    member_in_vc.id = 111
    member_in_vc.bot = False
    member_in_vc.mention = f"<@{member_in_vc.id}>"

    mock_interaction.guild.get_channel.return_value = None

    raid_cog.bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": member_in_vc.id}, {"user_id": manual_member.id}])

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

    # Assert: DKP was modified for both approved raid members
    assert raid_cog.bot.db.modify_user_dkp.await_count == 2
    raid_cog.bot.db.modify_user_dkp.assert_any_await(
        member_in_vc.id,
        mock_interaction.guild.id,
        5,
        "Award: Mass award (Raid)",
        username=member_in_vc.display_name,
    )
    raid_cog.bot.db.modify_user_dkp.assert_any_await(
        manual_member.id,
        mock_interaction.guild.id,
        5,
        "Award: Mass award (Raid)",
        username=manual_member.display_name,
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


@patch("discord_bot.cogs.raid_cog.is_officer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_raid_set_group_cmd_allows_not_in_raid_group_zero(mock_is_officer, raid_cog, mock_interaction):
    mock_is_officer.return_value = True

    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1})
    raid_cog.bot.db.is_raid_member = AsyncMock(return_value=True)
    raid_cog.bot.db.set_raid_member_group = AsyncMock()

    member = MagicMock(spec=discord.Member)
    member.id = 777
    member.bot = False
    member.mention = "@ManualRaider"

    await raid_cog.raid_set_group_cmd.callback(raid_cog, mock_interaction, member, 0)

    raid_cog.bot.db.set_raid_member_group.assert_awaited_once_with(1, 777, 0)
    mock_interaction.response.send_message.assert_awaited_once_with(
        "Assigned @ManualRaider to **Not in raid**.",
        ephemeral=True,
    )


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
        username=member.display_name,
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


@pytest.mark.asyncio
async def test_process_dkp_adjustment_excludes_direct_member_in_not_in_raid_group(raid_cog, mock_interaction, mock_thread):
    raid = {
        "id": 1,
        "guild_id": mock_interaction.guild.id,
        "leader_id": mock_interaction.user.id,
        "vc_id": 999,
    }
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)
    raid_cog.bot.db.get_guild_config = AsyncMock(return_value={})

    member = MagicMock(spec=discord.Member)
    member.id = 333
    member.bot = False
    member.mention = f"<@{member.id}>"
    member.display_name = "NotInRaidMember"

    raid_cog.bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": member.id}])
    raid_cog.bot.db.get_raid_member_groups = AsyncMock(return_value=[{"user_id": member.id, "group_number": 0}])
    raid_cog.bot.db.modify_user_dkp = AsyncMock()

    mock_interaction.response.is_done.return_value = True

    await raid_cog.process_dkp_adjustment(
        mock_interaction,
        action="Award",
        amount_str="5",
        reason="Targeted award",
        member=member,
    )

    raid_cog.bot.db.modify_user_dkp.assert_not_awaited()
    mock_interaction.followup.send.assert_called_once()
    _args, kwargs = mock_interaction.followup.send.call_args
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed")
    assert embed is not None
    assert embed.title == "No Eligible Targets"


@pytest.mark.asyncio
async def test_process_dkp_adjustment_excludes_members_and_groups(raid_cog, mock_interaction, mock_thread):
    raid = {
        "id": 1,
        "guild_id": mock_interaction.guild.id,
        "leader_id": mock_interaction.user.id,
        "vc_id": 999,
        "group_count": 2,
    }
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)

    m1 = MagicMock(spec=discord.Member)
    m1.id = 111
    m1.bot = False
    m1.mention = f"<@{m1.id}>"
    m1.display_name = "A"

    m2 = MagicMock(spec=discord.Member)
    m2.id = 222
    m2.bot = False
    m2.mention = f"<@{m2.id}>"
    m2.display_name = "B"

    m3 = MagicMock(spec=discord.Member)
    m3.id = 333
    m3.bot = False
    m3.mention = f"<@{m3.id}>"
    m3.display_name = "C"

    raid_cog.bot.db.get_raid_members = AsyncMock(
        return_value=[{"user_id": m1.id}, {"user_id": m2.id}, {"user_id": m3.id}]
    )
    raid_cog.bot.db.get_raid_member_groups = AsyncMock(
        return_value=[
            {"user_id": m1.id, "group_number": 1},
            {"user_id": m2.id, "group_number": 2},
            {"user_id": m3.id, "group_number": 1},
        ]
    )

    def get_member_side_effect(user_id):
        if int(user_id) == m1.id:
            return m1
        if int(user_id) == m2.id:
            return m2
        if int(user_id) == m3.id:
            return m3
        return None

    mock_interaction.guild.get_member.side_effect = get_member_side_effect
    raid_cog.bot.db.modify_user_dkp = AsyncMock()
    mock_interaction.response.is_done.return_value = True

    await raid_cog.process_dkp_adjustment(
        mock_interaction,
        action="Award",
        amount_str="5",
        reason="Mass award with exclusions",
        member=None,
        exclude_member_ids={333},
        exclude_group_numbers={2},
    )

    # group 2 excludes m2; explicit exclude removes m3; only m1 should be awarded
    raid_cog.bot.db.modify_user_dkp.assert_awaited_once()
    raid_cog.bot.db.modify_user_dkp.assert_awaited_once_with(
        m1.id,
        mock_interaction.guild.id,
        5,
        "Award: Mass award with exclusions (Raid)",
        username=m1.display_name,
    )


@pytest.mark.asyncio
async def test_process_dkp_adjustment_includes_groups(raid_cog, mock_interaction, mock_thread):
    raid = {
        "id": 1,
        "guild_id": mock_interaction.guild.id,
        "leader_id": mock_interaction.user.id,
        "vc_id": 999,
        "group_count": 2,
    }
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)

    m1 = MagicMock(spec=discord.Member)
    m1.id = 111
    m1.bot = False
    m1.mention = f"<@{m1.id}>"
    m1.display_name = "A"

    m2 = MagicMock(spec=discord.Member)
    m2.id = 222
    m2.bot = False
    m2.mention = f"<@{m2.id}>"
    m2.display_name = "B"

    m3 = MagicMock(spec=discord.Member)
    m3.id = 333
    m3.bot = False
    m3.mention = f"<@{m3.id}>"
    m3.display_name = "C"

    raid_cog.bot.db.get_raid_members = AsyncMock(
        return_value=[{"user_id": m1.id}, {"user_id": m2.id}, {"user_id": m3.id}]
    )
    raid_cog.bot.db.get_raid_member_groups = AsyncMock(
        return_value=[
            {"user_id": m1.id, "group_number": 1},
            {"user_id": m2.id, "group_number": 2},
            {"user_id": m3.id, "group_number": 1},
        ]
    )

    def get_member_side_effect(user_id):
        if int(user_id) == m1.id:
            return m1
        if int(user_id) == m2.id:
            return m2
        if int(user_id) == m3.id:
            return m3
        return None

    mock_interaction.guild.get_member.side_effect = get_member_side_effect
    raid_cog.bot.db.modify_user_dkp = AsyncMock()
    mock_interaction.response.is_done.return_value = True

    await raid_cog.process_dkp_adjustment(
        mock_interaction,
        action="Award",
        amount_str="5",
        reason="Mass award include group 2",
        member=None,
        include_group_numbers={2},
    )

    # include group 2 should only award m2
    raid_cog.bot.db.modify_user_dkp.assert_awaited_once()
    raid_cog.bot.db.modify_user_dkp.assert_awaited_once_with(
        m2.id,
        mock_interaction.guild.id,
        5,
        "Award: Mass award include group 2 (Raid)",
        username=m2.display_name,
    )


@pytest.mark.asyncio
async def test_update_team_from_voice_channel_adds_all_voice_members(raid_cog, mock_interaction, mock_thread):
    """Update Team adds all voice members (exclusions are cleared when leader clicks Update Team)."""
    raid = {
        "id": 1,
        "guild_id": mock_interaction.guild.id,
        "leader_id": mock_interaction.user.id,
        "vc_id": 999,
    }
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)
    raid_cog.bot.db.execute = AsyncMock()
    raid_cog.bot.db.add_raid_voice_channel = AsyncMock()
    raid_cog.bot.db.get_raid_voice_channels = AsyncMock(return_value=[])
    raid_cog.bot.db.remove_raid_member_exclusion = AsyncMock()

    leader_member = MagicMock(spec=discord.Member)
    leader_member.id = mock_interaction.user.id
    leader_member.bot = False
    leader_voice = MagicMock()
    leader_vc = MagicMock()
    leader_voice.channel = leader_vc
    leader_member.voice = leader_voice
    mock_interaction.guild.get_member.return_value = leader_member

    vc_member_ok = MagicMock(spec=discord.Member)
    vc_member_ok.id = 111
    vc_member_ok.bot = False
    vc_member_ok.display_name = "MemberOne"

    vc_member_two = MagicMock(spec=discord.Member)
    vc_member_two.id = 222
    vc_member_two.bot = False
    vc_member_two.display_name = "MemberTwo"

    leader_vc.id = 999
    leader_vc.members = [vc_member_ok, vc_member_two]
    leader_vc.mention = "#voice"

    mock_interaction.guild.get_channel.return_value = leader_vc

    raid_cog.bot.db.add_raid_member = AsyncMock(return_value=True)

    raid_cog.update_team_list = AsyncMock()

    mock_interaction.response.is_done.return_value = True

    with patch("discord_bot.cogs.raid_cog.discord.VoiceChannel", new=MagicMock):
        with patch("discord_bot.cogs.raid_cog.is_admin", new_callable=AsyncMock) as mock_is_admin:
            mock_is_admin.return_value = False
            await raid_cog.update_team_from_voice_channel(mock_interaction)

    # Update Team should add ALL voice members (exclusions are cleared first)
    assert raid_cog.bot.db.add_raid_member.await_count == 2
    raid_cog.bot.db.add_raid_member.assert_any_await(int(raid["id"]), int(vc_member_ok.id))
    raid_cog.bot.db.add_raid_member.assert_any_await(int(raid["id"]), int(vc_member_two.id))


@pytest.mark.asyncio
async def test_configure_timed_award_saves_to_db(raid_cog, mock_interaction, mock_thread):
    raid = {
        "id": 1,
        "guild_id": mock_interaction.guild.id,
        "leader_id": mock_interaction.user.id,
        "vc_id": 999,
    }
    raid_cog.bot.db.get_raid_by_thread = AsyncMock(return_value=raid)
    raid_cog.bot.db.set_raid_timed_award = AsyncMock()
    mock_thread.send = AsyncMock()
    mock_interaction.response.is_done.return_value = True

    with patch("discord_bot.cogs.raid_cog.is_admin", new_callable=AsyncMock) as mock_is_admin:
        mock_is_admin.return_value = False
        await raid_cog.configure_timed_award(mock_interaction, amount=5, interval_minutes=30)

    raid_cog.bot.db.set_raid_timed_award.assert_awaited_once_with(
        int(raid["id"]),
        amount=5,
        interval_minutes=30,
        is_enabled=True,
    )
    mock_thread.send.assert_awaited()


def test_parse_cutoff_datetime_input_supports_us_style(raid_cog):
    from datetime import datetime, timedelta
    sys_offset_h = datetime.now().astimezone().utcoffset().total_seconds() / 3600
    expected_utc = datetime(2026, 4, 12, 19, 0, 0) - timedelta(hours=sys_offset_h)
    expected_sql = expected_utc.strftime("%Y-%m-%d %H:%M:%S")

    parsed, sql_value = raid_cog._parse_cutoff_datetime_input("4/12/26 7:00 PM")

    assert parsed is not None
    assert sql_value == expected_sql


@pytest.mark.asyncio
async def test_preview_reverse_raid_dkp_from_cutoff_uses_closed_raid_lookup(raid_cog, mock_interaction):
    closed_raid = {
        "id": 5,
        "guild_id": mock_interaction.guild.id,
        "leader_id": mock_interaction.user.id,
        "thread_id": mock_interaction.channel.id,
        "is_active": 0,
    }
    raid_cog.bot.db.get_raid_by_thread_any_state = AsyncMock(return_value=closed_raid)
    raid_cog.bot.db.get_raid_dkp_transactions_from_cutoff = AsyncMock(
        return_value=[
            {"id": 10, "user_id": 111, "change": 5, "reason": "Award: Boss kill"},
            {"id": 11, "user_id": 222, "change": 3, "reason": "Award: Trash"},
        ]
    )

    with patch("discord_bot.cogs.raid_cog.is_admin", new_callable=AsyncMock) as mock_is_admin:
        mock_is_admin.return_value = False
        await raid_cog.preview_reverse_raid_dkp_from_cutoff(
            mock_interaction,
            confirm="CONFIRM",
            cutoff_text="4/12/26 7:00 PM +0",
            reason="cleanup",
            timed_only=False,
        )

    raid_cog.bot.db.get_raid_by_thread_any_state.assert_awaited_once_with(mock_interaction.channel.id)
    raid_cog.bot.db.get_raid_dkp_transactions_from_cutoff.assert_awaited_once_with(
        5,
        "2026-04-12 19:00:00",
        timed_only=False,
    )
    mock_interaction.response.send_message.assert_awaited_once()
    _args, kwargs = mock_interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed")
    assert isinstance(embed, discord.Embed)
    assert embed.title == "Confirm Cutoff Reversal"
    assert "Affected transactions" in (embed.description or "")


@pytest.mark.asyncio
async def test_apply_reverse_raid_dkp_from_cutoff_records_reference_transactions(raid_cog, mock_interaction, mock_thread):
    closed_raid = {
        "id": 5,
        "guild_id": mock_interaction.guild.id,
        "leader_id": mock_interaction.user.id,
        "thread_id": mock_interaction.channel.id,
        "is_active": 0,
    }
    member = MagicMock(spec=discord.Member)
    member.display_name = "RaiderOne"
    mock_interaction.guild.get_member.return_value = member
    mock_interaction.response.edit_message = AsyncMock()
    mock_thread.send = AsyncMock()

    raid_cog.bot.db.get_raid_by_thread_any_state = AsyncMock(return_value=closed_raid)
    raid_cog.bot.db.get_raid_dkp_transactions_from_cutoff = AsyncMock(
        return_value=[
            {"id": 10, "user_id": 111, "change": 5, "reason": "Timed raid award (+5 every 6m)"},
        ]
    )
    raid_cog.bot.db.apply_raid_dkp_reversal_for_user = AsyncMock()
    raid_cog.bot.db.get_user_dkp = AsyncMock(return_value=25)

    with patch("discord_bot.cogs.raid_cog.is_admin", new_callable=AsyncMock) as mock_is_admin:
        with patch("discord_bot.cogs.raid_cog.send_dkp_change_dm", new_callable=AsyncMock) as mock_send_dm:
            mock_is_admin.return_value = False
            await raid_cog.apply_reverse_raid_dkp_from_cutoff(
                mock_interaction,
                cutoff_text="4/12/26 7:00 PM",
                cutoff_sql="2026-04-12 19:00:00",
                reason="cleanup",
                timed_only=True,
            )

    raid_cog.bot.db.apply_raid_dkp_reversal_for_user.assert_awaited_once_with(
        raid_id=5,
        guild_id=mock_interaction.guild.id,
        user_id=111,
        total_delta=-5,
        reversal_reason="Reverse Raid DKP From Cutoff: cleanup",
        source_rows=[(10, 5)],
        actor_id=mock_interaction.user.id,
        username="RaiderOne",
    )
    mock_send_dm.assert_awaited_once()
    mock_thread.send.assert_awaited_once()
    mock_interaction.response.edit_message.assert_awaited_once()
    _args, kwargs = mock_interaction.response.edit_message.call_args
    embed = kwargs.get("embed")
    assert isinstance(embed, discord.Embed)
    assert embed.title == "Cutoff Reversal Complete"


@pytest.mark.asyncio
async def test_apply_reverse_raid_dkp_from_cutoff_failed_atomic_reversal_reports_no_changes(raid_cog, mock_interaction, mock_thread):
    closed_raid = {
        "id": 5,
        "guild_id": mock_interaction.guild.id,
        "leader_id": mock_interaction.user.id,
        "thread_id": mock_interaction.channel.id,
        "is_active": 0,
    }
    member = MagicMock(spec=discord.Member)
    member.display_name = "RaiderOne"
    mock_interaction.guild.get_member.return_value = member
    mock_interaction.response.edit_message = AsyncMock()
    mock_thread.send = AsyncMock()

    raid_cog.bot.db.get_raid_by_thread_any_state = AsyncMock(return_value=closed_raid)
    raid_cog.bot.db.get_raid_dkp_transactions_from_cutoff = AsyncMock(
        return_value=[
            {"id": 10, "user_id": 111, "change": 5, "reason": "Timed raid award (+5 every 6m)"},
        ]
    )
    raid_cog.bot.db.apply_raid_dkp_reversal_for_user = AsyncMock(side_effect=RuntimeError("write failed"))

    with patch("discord_bot.cogs.raid_cog.is_admin", new_callable=AsyncMock) as mock_is_admin:
        with patch("discord_bot.cogs.raid_cog.send_dkp_change_dm", new_callable=AsyncMock) as mock_send_dm:
            mock_is_admin.return_value = False
            await raid_cog.apply_reverse_raid_dkp_from_cutoff(
                mock_interaction,
                cutoff_text="4/12/26 7:00 PM",
                cutoff_sql="2026-04-12 19:00:00",
                reason="cleanup",
                timed_only=True,
            )

    raid_cog.bot.db.apply_raid_dkp_reversal_for_user.assert_awaited_once()
    mock_send_dm.assert_not_awaited()
    mock_thread.send.assert_not_awaited()
    mock_interaction.response.edit_message.assert_awaited_once()
    _args, kwargs = mock_interaction.response.edit_message.call_args
    embed = kwargs.get("embed")
    assert isinstance(embed, discord.Embed)
    assert embed.title == "Cutoff Reversal"
    assert "All reversals failed" in (embed.description or "")
