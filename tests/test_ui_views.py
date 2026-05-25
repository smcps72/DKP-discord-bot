import pytest
from unittest.mock import MagicMock, AsyncMock, PropertyMock, patch

import discord

from discord_bot.ui.views import (
    WelcomeView,
    WelcomeLegacyView,
    DkpPanelView,
    RaidGroupSignupModalView,
    RaidPopupView,
    RaidReverseDKPChoiceView,
    RaidPopupTimedDKPView,
    RaidPopupDKPSelectView,
    RaidSyncVoicePickerView,
    RaidSyncVoiceChannelSelect,
)
from discord_bot.ui.modals import RaidReverseFromCutoffModal

# Mock objects for testing
class MockGuild(MagicMock):
    def __init__(self, id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.id = id

class MockUser(MagicMock):
    def __init__(self, id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.id = id
        self.bot = False

class MockInteraction(MagicMock):
    def __init__(self, guild=None, user=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guild = guild
        self.user = user
        self.response = MagicMock()
        self.response.defer = AsyncMock()
        self.response.is_done = MagicMock(return_value=False)
        self.response.send_message = AsyncMock()
        self.response.send_modal = AsyncMock()
        self.followup = MagicMock()
        self.followup.send = AsyncMock()
        self.message = MagicMock()

@pytest.fixture
def mock_bot():
    return MagicMock()

@pytest.fixture
def mock_interaction():
    guild = MockGuild(id=123)
    user = MockUser(id=456)
    return MockInteraction(guild=guild, user=user)

@pytest.mark.asyncio
async def test_welcome_view_create_raid_button(mock_bot, mock_interaction):
    """Tests that the 'Create Raid' button delegates to the RaidCog entrypoint."""
    # Arrange
    mock_raid_cog = MagicMock()
    mock_raid_cog.create_raid_from_interaction = AsyncMock()
    mock_bot.get_cog.return_value = mock_raid_cog
    view = WelcomeLegacyView(bot=mock_bot)

    # Act
    await view.create_raid.callback(mock_interaction)

    # Assert
    mock_raid_cog.create_raid_from_interaction.assert_called_once_with(mock_interaction)
    mock_interaction.response.defer.assert_not_called()

@pytest.mark.asyncio
async def test_welcome_view_my_dkp_button(mock_bot, mock_interaction):
    """Tests that the 'My DKP' button defers and calls the correct cog method."""
    # Arrange
    mock_user_cog = MagicMock()
    mock_user_cog.show_my_dkp = AsyncMock()
    mock_bot.get_cog.return_value = mock_user_cog
    view = WelcomeLegacyView(bot=mock_bot)

    # Act
    await view.my_dkp.callback(mock_interaction)

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_user_cog.show_my_dkp.assert_called_once_with(mock_interaction)

@pytest.mark.asyncio
async def test_welcome_view_bot_status_button(mock_bot, mock_interaction):
    """Tests the bot status button."""
    # Arrange
    mock_admin_cog = MagicMock()
    mock_admin_cog._create_status_embed = AsyncMock(return_value="embed_content")
    mock_bot.get_cog.return_value = mock_admin_cog
    view = WelcomeLegacyView(bot=mock_bot)

    # Act
    await view.bot_status.callback(mock_interaction)

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_admin_cog._create_status_embed.assert_called_once_with(mock_interaction.guild.id)
    mock_interaction.followup.send.assert_called_once_with(embed="embed_content", ephemeral=True)

@patch('discord_bot.ui.views.is_admin', new_callable=AsyncMock)
@patch('discord_bot.ui.views.AdminPanelView')
@pytest.mark.asyncio
async def test_welcome_view_admin_panel_button_as_officer(mock_AdminPanelView, mock_is_admin, mock_bot, mock_interaction):
    """Tests the admin panel button for an authorized officer."""
    # Arrange
    mock_is_admin.return_value = True
    view = WelcomeLegacyView(bot=mock_bot)

    # Act
    await view.admin_panel.callback(mock_interaction)

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_is_admin.assert_called_once_with(mock_interaction)
    mock_interaction.followup.send.assert_called_once_with("Welcome to the Admin Panel.", view=mock_AdminPanelView.return_value, ephemeral=True)

@patch('discord_bot.ui.views.is_admin', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_welcome_view_admin_panel_button_as_non_officer(mock_is_admin, mock_bot, mock_interaction):
    """Tests the admin panel button for a non-officer."""
    # Arrange
    mock_is_admin.return_value = False
    view = WelcomeLegacyView(bot=mock_bot)

    # Act
    await view.admin_panel.callback(mock_interaction)

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_is_admin.assert_called_once_with(mock_interaction)
    mock_interaction.followup.send.assert_called_once_with("You must be a bot admin to use this.", ephemeral=True)


@patch('discord_bot.ui.views.discord.Member', new=MagicMock)
@patch('discord_bot.ui.views.is_officer', new_callable=AsyncMock)
@patch('discord_bot.ui.views.is_admin', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_welcome_view_open_panel_sends_ephemeral_panel(mock_is_admin, mock_is_officer, mock_bot, mock_interaction):
    mock_is_admin.return_value = False
    mock_is_officer.return_value = False

    view = WelcomeView(bot=mock_bot)
    await view.open_panel.callback(mock_interaction)

    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)

    args, kwargs = mock_interaction.followup.send.call_args
    assert kwargs.get("ephemeral") is True
    assert isinstance(kwargs.get("view"), DkpPanelView)


@pytest.mark.asyncio
async def test_dkp_panel_view_hides_admin_and_docs_for_non_admin():
    bot = MagicMock()
    view = DkpPanelView(bot=bot, admin_ok=False, officer_ok=True)
    ids = {getattr(c, "custom_id", None) for c in view.children}
    assert "dkp_panel_admin_panel" not in ids
    assert "dkp_panel_docs" not in ids


@pytest.mark.asyncio
async def test_dkp_panel_view_hides_create_raid_for_non_officer_non_admin():
    bot = MagicMock()
    view = DkpPanelView(bot=bot, admin_ok=False, officer_ok=False)
    ids = {getattr(c, "custom_id", None) for c in view.children}
    assert "dkp_panel_create_raid" not in ids


@patch("discord_bot.ui.views.ensure_allowed_guild", new_callable=AsyncMock)
@patch("discord_bot.ui.views.is_officer", new_callable=AsyncMock)
@patch("discord_bot.ui.views.is_admin", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_raid_popup_timed_dkp_opens_control_view(mock_is_admin, mock_is_officer, mock_ensure_allowed_guild):
    mock_ensure_allowed_guild.return_value = True
    mock_is_admin.return_value = True
    mock_is_officer.return_value = False

    bot = MagicMock()
    bot.db = MagicMock()
    bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "leader_id": 456})
    bot.db.get_raid_timed_award = AsyncMock(return_value={"amount": 5, "interval_minutes": 30, "is_enabled": 1})
    bot.get_cog.return_value = MagicMock()

    guild = MockGuild(id=123)
    user = MockUser(id=456)
    user.display_name = "MockUser"
    interaction = MockInteraction(guild=guild, user=user)
    interaction.channel = MagicMock()
    interaction.channel.id = 789
    interaction.response.edit_message = AsyncMock()

    view = RaidPopupView(bot=bot, mode="manage", can_manage=True, can_rename_thread=True)
    await view.timed_dkp.callback(interaction)

    interaction.response.edit_message.assert_awaited_once()
    _args, kwargs = interaction.response.edit_message.call_args
    assert isinstance(kwargs.get("view"), RaidPopupTimedDKPView)

    embed = kwargs.get("embed")
    assert isinstance(embed, discord.Embed)
    assert embed.title == "Timed DKP"
    assert "Currently enabled" in (embed.description or "")

    btn_ids = {
        getattr(c, "custom_id", None)
        for c in kwargs.get("view").children
        if isinstance(c, discord.ui.Button)
    }
    assert "raid_popup_timed_dkp_configure" in btn_ids
    assert "raid_popup_timed_dkp_stop" in btn_ids


@pytest.mark.asyncio
async def test_raid_popup_dkp_picker_is_limited_to_raid_members():
    bot = MagicMock()
    member1 = MagicMock(spec=discord.Member)
    member1.id = 111
    member1.bot = False
    member1.display_name = "Alpha"

    member2 = MagicMock(spec=discord.Member)
    member2.id = 222
    member2.bot = False
    member2.display_name = "Bravo"

    view = RaidPopupDKPSelectView(
        bot=bot,
        action="Award",
        members=[member1, member2],
        can_manage=True,
        can_rename_thread=True,
    )

    # Ensure the picker is not a guild-wide UserSelect.
    assert not any(isinstance(c, discord.ui.UserSelect) for c in view.children)

    selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
    assert len(selects) == 1
    picker = selects[0]

    option_values = {o.value for o in picker.options}
    assert option_values == {"111", "222"}


@pytest.mark.asyncio
async def test_raid_popup_dkp_picker_uses_user_select_for_more_than_25_members():
    bot = MagicMock()
    members = []
    for index in range(30):
        member = MagicMock(spec=discord.Member)
        member.id = 1000 + index
        member.bot = False
        member.display_name = f"Member {index:02d}"
        members.append(member)

    view = RaidPopupDKPSelectView(
        bot=bot,
        action="Award",
        members=members,
        can_manage=True,
        can_rename_thread=True,
    )

    picker = next(c for c in view.children if isinstance(c, discord.ui.UserSelect))
    assert picker.max_values == 25
    assert getattr(picker, "_allowed_member_ids", set()) == {member.id for member in members}


@pytest.mark.asyncio
async def test_sync_voice_channel_select_resolves_selected_channel_id_to_voice_channel(mock_bot):
    view = RaidSyncVoicePickerView(bot=mock_bot)
    select = next(c for c in view.children if isinstance(c, RaidSyncVoiceChannelSelect))

    guild = MockGuild(id=123)
    user = MockUser(id=456)
    interaction = MockInteraction(guild=guild, user=user)

    selected = MagicMock()
    selected.id = 999

    resolved_voice_channel = MagicMock(spec=discord.VoiceChannel)
    guild.get_channel = MagicMock(return_value=resolved_voice_channel)
    guild.fetch_channel = AsyncMock()
    view.run_sync = AsyncMock()

    with patch.object(RaidSyncVoiceChannelSelect, "values", new_callable=PropertyMock, return_value=[selected]):
        await select.callback(interaction)

    view.run_sync.assert_awaited_once_with(interaction, channel=resolved_voice_channel)
    interaction.response.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_voice_channel_select_rejects_non_voice_channel_selection(mock_bot):
    view = RaidSyncVoicePickerView(bot=mock_bot)
    select = next(c for c in view.children if isinstance(c, RaidSyncVoiceChannelSelect))

    guild = MockGuild(id=123)
    user = MockUser(id=456)
    interaction = MockInteraction(guild=guild, user=user)

    selected = MagicMock()
    selected.id = 999

    resolved_text_channel = MagicMock(spec=discord.TextChannel)
    guild.get_channel = MagicMock(return_value=resolved_text_channel)
    guild.fetch_channel = AsyncMock()
    view.run_sync = AsyncMock()

    with patch.object(RaidSyncVoiceChannelSelect, "values", new_callable=PropertyMock, return_value=[selected]):
        await select.callback(interaction)

    view.run_sync.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once_with(
        "Please choose a valid voice channel.",
        ephemeral=True,
    )


# Tests for RaidControlView
from discord_bot.ui.views import RaidControlView, DKPAdjustmentView
from discord_bot.ui.modals import DKPAdjustmentModal, AuctionStartModal
from discord_bot.ui.views import RaidOpenPanelView
from discord_bot.ui.modals import RaidGroupSetupModal
from discord_bot.ui.views import RaidMemberClearGroupView, RaidMemberAssignGroupView, RaidBulkAssignGroupView

@pytest.fixture
def mock_raid_control_interaction(mock_interaction): # Use the existing mock_interaction
    # Add channel mock if needed for specific tests, e.g., interaction_check
    mock_interaction.channel = MagicMock()
    mock_interaction.channel.id = 789
    mock_interaction.response.send_modal = AsyncMock() # Add send_modal mock
    return mock_interaction

@pytest.mark.asyncio
class TestRaidControlView:
    async def test_award_dkp_button(self, mock_bot, mock_raid_control_interaction):
        """Tests that the 'Award DKP' button shows the DKPAdjustmentView for raid members."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 12345, "group_count": 2})
        mock_bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": 1}, {"user_id": 2}])

        mock_vc = MagicMock()
        member1 = MagicMock()
        member1.bot = False
        member1.id = 1
        member2 = MagicMock()
        member2.bot = False
        member2.id = 2
        mock_vc.members = [member1, member2]
        mock_raid_control_interaction.guild.get_channel.return_value = mock_vc
        mock_raid_control_interaction.guild.get_member.side_effect = lambda uid: member1 if uid == 1 else (member2 if uid == 2 else None)

        # Patch discord.VoiceChannel in the views module so our MagicMock
        # instance passes the isinstance check inside _show_dkp_adjustment_view.
        with patch("discord_bot.ui.views.discord.VoiceChannel", new=MagicMock):
            # Act
            await view.award_dkp.callback(mock_raid_control_interaction)

        # Assert
        mock_raid_control_interaction.response.send_message.assert_called_once()
        args, kwargs = mock_raid_control_interaction.response.send_message.call_args
        assert "Who do you want to award DKP?" in args[0]
        assert isinstance(kwargs["view"], DKPAdjustmentView)
        assert kwargs["ephemeral"] is True

        # Group buttons should be present when group_count is configured
        view_obj = kwargs["view"]
        labels = [getattr(c, "label", None) for c in view_obj.children if hasattr(c, "label")]
        assert "Group 1" in labels
        assert "Group 2" in labels

    async def test_dkp_adjustment_view_shuffle_toggle_rebuilds_view(self):
        bot = MagicMock()

        member1 = MagicMock()
        member1.id = 1
        member1.bot = False
        member1.display_name = "Alpha"

        member2 = MagicMock()
        member2.id = 2
        member2.bot = False
        member2.display_name = "Bravo"

        view = DKPAdjustmentView(
            bot,
            action="award",
            members=[member1, member2],
            group_count=2,
            member_list_order="name",
        )

        toggle_btns = [
            c
            for c in view.children
            if isinstance(c, discord.ui.Button) and getattr(c, "label", None) == "Shuffle"
        ]
        assert len(toggle_btns) == 1
        toggle_btn = toggle_btns[0]

        interaction = MagicMock()
        interaction.response = MagicMock()
        interaction.response.edit_message = AsyncMock()

        await toggle_btn.callback(interaction)

        interaction.response.edit_message.assert_awaited_once()
        _args, kwargs = interaction.response.edit_message.call_args
        new_view = kwargs.get("view")
        assert isinstance(new_view, DKPAdjustmentView)
        assert getattr(new_view, "member_list_order", None) == "random"

        new_toggle_btns = [
            c
            for c in new_view.children
            if isinstance(c, discord.ui.Button) and getattr(c, "label", None) == "Sort A-Z"
        ]
        assert len(new_toggle_btns) == 1

    async def test_dkp_adjustment_view_uses_user_select_for_more_than_25_members(self):
        bot = MagicMock()
        members = []
        for index in range(30):
            member = MagicMock()
            member.id = 2000 + index
            member.bot = False
            member.display_name = f"Member {index:02d}"
            members.append(member)

        view = DKPAdjustmentView(
            bot,
            action="award",
            members=members,
            group_count=2,
            member_list_order="name",
        )

        picker = next(c for c in view.children if isinstance(c, discord.ui.UserSelect))
        assert picker.max_values == 25
        assert getattr(picker, "_allowed_member_ids", set()) == {member.id for member in members}
        toggle_labels = {
            getattr(c, "label", None)
            for c in view.children
            if isinstance(c, discord.ui.Button)
        }
        assert "Shuffle" not in toggle_labels
        assert "Sort A-Z" not in toggle_labels

    async def test_deduct_dkp_button(self, mock_bot, mock_raid_control_interaction):
        """Tests that the 'Deduct DKP' button shows the DKPAdjustmentView for raid members."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 12345, "group_count": 2})
        mock_bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": 1}])

        mock_vc = MagicMock()
        member = MagicMock()
        member.bot = False
        member.id = 1
        mock_vc.members = [member]
        mock_raid_control_interaction.guild.get_channel.return_value = mock_vc
        mock_raid_control_interaction.guild.get_member.side_effect = lambda uid: member if uid == 1 else None

        # Patch discord.VoiceChannel so our mocked VC passes the isinstance
        # guard inside _show_dkp_adjustment_view.
        with patch("discord_bot.ui.views.discord.VoiceChannel", new=MagicMock):
            # Act
            await view.deduct_dkp.callback(mock_raid_control_interaction)

        # Assert
        mock_raid_control_interaction.response.send_message.assert_called_once()
        args, kwargs = mock_raid_control_interaction.response.send_message.call_args
        assert "Who do you want to deduct DKP?" in args[0]
        assert isinstance(kwargs["view"], DKPAdjustmentView)
        assert kwargs["ephemeral"] is True

        view_obj = kwargs["view"]
        labels = [getattr(c, "label", None) for c in view_obj.children if hasattr(c, "label")]
        assert "Group 1" in labels
        assert "Group 2" in labels

    async def test_group_signup_modal_remove_from_group_opens_clear_group_view_for_leader(self, mock_bot, mock_raid_control_interaction):
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "leader_id": mock_raid_control_interaction.user.id, "group_count": 3})
        mock_bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": 1}, {"user_id": 2}])

        member1 = MagicMock()
        member1.bot = False
        member1.id = 1
        member2 = MagicMock()
        member2.bot = False
        member2.id = 2
        mock_raid_control_interaction.guild.get_member.side_effect = lambda uid: member1 if uid == 1 else (member2 if uid == 2 else None)

        mock_raid_control_interaction.response.edit_message = AsyncMock()

        modal_view = RaidGroupSignupModalView(mock_bot, group_count=3, can_manage=True)
        await modal_view.remove_from_group.callback(mock_raid_control_interaction)

        mock_raid_control_interaction.response.edit_message.assert_awaited_once()
        _args, kwargs = mock_raid_control_interaction.response.edit_message.call_args
        assert isinstance(kwargs.get("view"), RaidMemberClearGroupView)

    async def test_group_signup_modal_set_group_opens_assign_group_view_for_leader(self, mock_bot, mock_raid_control_interaction):
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "leader_id": mock_raid_control_interaction.user.id, "group_count": 3})
        mock_bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": 1}, {"user_id": 2}])

        member1 = MagicMock()
        member1.bot = False
        member1.id = 1
        member2 = MagicMock()
        member2.bot = False
        member2.id = 2
        mock_raid_control_interaction.guild.get_member.side_effect = lambda uid: member1 if uid == 1 else (member2 if uid == 2 else None)

        mock_raid_control_interaction.response.edit_message = AsyncMock()

        modal_view = RaidGroupSignupModalView(mock_bot, group_count=3, can_manage=True)
        await modal_view.set_group.callback(mock_raid_control_interaction)

        mock_raid_control_interaction.response.edit_message.assert_awaited_once()
        _args, kwargs = mock_raid_control_interaction.response.edit_message.call_args
        assert isinstance(kwargs.get("view"), RaidMemberAssignGroupView)

    async def test_group_signup_modal_set_group_uses_searchable_user_select(self, mock_bot, mock_raid_control_interaction):
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "leader_id": mock_raid_control_interaction.user.id, "group_count": 3})
        mock_bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": 1}, {"user_id": 2}])
        mock_bot.db.get_raid_member_groups = AsyncMock(return_value=[])

        member1 = MagicMock()
        member1.bot = False
        member1.id = 1
        member2 = MagicMock()
        member2.bot = False
        member2.id = 2
        mock_raid_control_interaction.guild.get_member.side_effect = lambda uid: member1 if uid == 1 else (member2 if uid == 2 else None)

        mock_raid_control_interaction.response.edit_message = AsyncMock()

        modal_view = RaidGroupSignupModalView(mock_bot, group_count=3, can_manage=True)
        await modal_view.set_group.callback(mock_raid_control_interaction)

        _args, kwargs = mock_raid_control_interaction.response.edit_message.call_args
        assign_view = kwargs.get("view")
        picker = next(c for c in assign_view.children if isinstance(c, discord.ui.UserSelect))
        assert picker.max_values == 1
        assert getattr(picker, "_allowed_member_ids", set()) == {1, 2}
        assert not any(
            isinstance(c, discord.ui.Select) and not isinstance(c, discord.ui.UserSelect)
            and getattr(c, "placeholder", None) == "Select a member..."
            for c in assign_view.children
        )

    async def test_group_signup_modal_bulk_set_group_keeps_picker(self, mock_bot, mock_raid_control_interaction):
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "leader_id": mock_raid_control_interaction.user.id, "group_count": 3})
        mock_bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": 1}, {"user_id": 2}])

        member1 = MagicMock()
        member1.bot = False
        member1.id = 1
        member1.display_name = "Alpha"
        member2 = MagicMock()
        member2.bot = False
        member2.id = 2
        member2.display_name = "Bravo"
        mock_raid_control_interaction.guild.get_member.side_effect = lambda uid: member1 if uid == 1 else (member2 if uid == 2 else None)

        mock_raid_control_interaction.response.edit_message = AsyncMock()

        modal_view = RaidGroupSignupModalView(mock_bot, group_count=3, can_manage=True)
        await modal_view.bulk_set_group.callback(mock_raid_control_interaction)

        _args, kwargs = mock_raid_control_interaction.response.edit_message.call_args
        bulk_view = kwargs.get("view")
        assert not any(isinstance(c, discord.ui.UserSelect) for c in bulk_view.children)
        picker = next(
            c for c in bulk_view.children
            if isinstance(c, discord.ui.Select) and getattr(c, "placeholder", None) == "Select members..."
        )
        option_values = {option.value for option in picker.options}
        assert option_values == {"1", "2"}

    async def test_bulk_assign_group_view_paginates_members(self):
        bot = MagicMock()
        members = []
        for index in range(30):
            member = MagicMock()
            member.id = 1000 + index
            member.bot = False
            member.display_name = f"Member {index:02d}"
            members.append(member)

        view = RaidBulkAssignGroupView(bot, raid_id=1, members=members, group_count=3, member_list_order="name")

        picker = next(
            c for c in view.children
            if isinstance(c, discord.ui.Select) and getattr(c, "placeholder", "").startswith("Select members...")
        )
        assert len(picker.options) == 25
        assert picker.placeholder == "Select members... (Page 1/2)"

        prev_button = next(c for c in view.children if isinstance(c, discord.ui.Button) and getattr(c, "label", None) == "Previous")
        next_button = next(c for c in view.children if isinstance(c, discord.ui.Button) and getattr(c, "label", None) == "Next")
        assert prev_button.disabled is True
        assert next_button.disabled is False

        interaction = MagicMock()
        interaction.response = MagicMock()
        interaction.response.edit_message = AsyncMock()

        await next_button.callback(interaction)

        interaction.response.edit_message.assert_awaited_once()
        _args, kwargs = interaction.response.edit_message.call_args
        new_view = kwargs.get("view")
        assert isinstance(new_view, RaidBulkAssignGroupView)
        assert getattr(new_view, "page_index", None) == 1

        new_picker = next(
            c for c in new_view.children
            if isinstance(c, discord.ui.Select) and getattr(c, "placeholder", "").startswith("Select members...")
        )
        assert len(new_picker.options) == 5
        assert new_picker.placeholder == "Select members... (Page 2/2)"
        assert {option.value for option in new_picker.options} == {str(1000 + index) for index in range(25, 30)}

    async def test_bulk_assign_group_view_preserves_selection_across_pages(self):
        bot = MagicMock()
        members = []
        for index in range(30):
            member = MagicMock()
            member.id = 2000 + index
            member.bot = False
            member.display_name = f"Member {index:02d}"
            members.append(member)

        view = RaidBulkAssignGroupView(bot, raid_id=1, members=members, group_count=3, member_list_order="name")
        picker = next(
            c for c in view.children
            if isinstance(c, discord.ui.Select) and getattr(c, "placeholder", "").startswith("Select members...")
        )

        interaction_select_page_1 = MagicMock()
        interaction_select_page_1.response = MagicMock()
        interaction_select_page_1.response.edit_message = AsyncMock()

        with patch.object(type(picker), "values", new_callable=PropertyMock, return_value=["2000", "2001"]):
            await picker.callback(interaction_select_page_1)

        _args, kwargs = interaction_select_page_1.response.edit_message.call_args
        page_one_selected_view = kwargs.get("view")
        assert getattr(page_one_selected_view, "selected_member_ids", None) == [2000, 2001]

        next_button = next(
            c for c in page_one_selected_view.children
            if isinstance(c, discord.ui.Button) and getattr(c, "label", None) == "Next"
        )
        interaction_next = MagicMock()
        interaction_next.response = MagicMock()
        interaction_next.response.edit_message = AsyncMock()

        await next_button.callback(interaction_next)

        _args, kwargs = interaction_next.response.edit_message.call_args
        page_two_view = kwargs.get("view")
        assert getattr(page_two_view, "selected_member_ids", None) == [2000, 2001]

        page_two_picker = next(
            c for c in page_two_view.children
            if isinstance(c, discord.ui.Select) and getattr(c, "placeholder", "").startswith("Select members...")
        )
        interaction_select_page_2 = MagicMock()
        interaction_select_page_2.response = MagicMock()
        interaction_select_page_2.response.edit_message = AsyncMock()

        with patch.object(type(page_two_picker), "values", new_callable=PropertyMock, return_value=["2025"]):
            await page_two_picker.callback(interaction_select_page_2)

        _args, kwargs = interaction_select_page_2.response.edit_message.call_args
        combined_view = kwargs.get("view")
        assert getattr(combined_view, "selected_member_ids", None) == [2000, 2001, 2025]
        assert kwargs.get("content") == "Selected **3** member(s). Now pick a group or continue selecting. Page **2/2**."

    async def test_start_auction_button(self, mock_bot, mock_raid_control_interaction):
        """Tests that the 'Start Auction' button opens the item-name modal when preconditions are met."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 12345})
        mock_bot.db.get_active_auction = AsyncMock(return_value=None)
        mock_bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": 456}])

        mock_vc = MagicMock()
        member = MagicMock()
        member.bot = False
        mock_vc.members = [member]
        mock_raid_control_interaction.guild.get_channel.return_value = mock_vc

        mock_auction_cog = AsyncMock()
        mock_bot.get_cog.return_value = mock_auction_cog

        # Act
        await view.start_auction.callback(mock_raid_control_interaction)

        # Assert
        mock_raid_control_interaction.response.send_modal.assert_called_once()
        modal_sent = mock_raid_control_interaction.response.send_modal.call_args[0][0]
        assert isinstance(modal_sent, AuctionStartModal)
        assert modal_sent.title == "Start New Auction"
        assert modal_sent.auction_cog == mock_auction_cog

    async def test_start_auction_button_blocks_when_vc_empty(self, mock_bot, mock_raid_control_interaction):
        """Tests that 'Start Auction' shows an error when no eligible raid members exist."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 12345})
        mock_bot.db.get_active_auction = AsyncMock(return_value=None)

        mock_bot.db.get_raid_members = AsyncMock(return_value=[])

        mock_vc = MagicMock()
        mock_vc.members = []  # Empty voice channel
        mock_raid_control_interaction.guild.get_channel.return_value = mock_vc

        # Act
        await view.start_auction.callback(mock_raid_control_interaction)

        # Assert: error message is sent and modal is not opened
        mock_raid_control_interaction.response.send_message.assert_called_once_with(
            "No eligible raid members were found. If you are in a voice channel, click \"Sync Voice\" to add all members in your voice channel to the raid. Or each member can click the \"Join Raid\" button. Cannot start auction.",
            ephemeral=True,
        )
        mock_raid_control_interaction.response.send_modal.assert_not_called()

    async def test_join_raid_button_adds_user_directly_no_exclusion(self, mock_bot, mock_raid_control_interaction):
        """Tests that 'Join Raid' auto-adds the user directly when not excluded."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 12345, "leader_id": 999})
        mock_bot.db.is_raid_member = AsyncMock(side_effect=[False, True])
        mock_bot.db.get_raid_member_exclusion_reason = AsyncMock(return_value=None)
        mock_bot.db.add_raid_member = AsyncMock(return_value=True)
        mock_bot.db.remove_raid_member_exclusion = AsyncMock()
        mock_bot.db.delete_raid_join_request = AsyncMock()

        mock_thread = MagicMock(spec=discord.Thread)
        mock_thread.send = AsyncMock()
        mock_raid_control_interaction.channel = mock_thread
        mock_raid_control_interaction.user.bot = False

        # Act: first click adds user directly
        await view.join_raid.callback(mock_raid_control_interaction)

        # Assert: user is added directly (no join request flow)
        mock_bot.db.add_raid_member.assert_called_once_with(1, mock_raid_control_interaction.user.id)
        mock_raid_control_interaction.followup.send.assert_called_with(
            "You have been added to the raid.",
            ephemeral=True,
        )

        # Reset mocks for second click
        mock_raid_control_interaction.followup.send.reset_mock()

        # Act: second click sees already member
        await view.join_raid.callback(mock_raid_control_interaction)

        # Assert: duplicate is rejected
        mock_raid_control_interaction.followup.send.assert_called_with(
            "You are already part of this raid.",
            ephemeral=True,
        )

    async def test_join_raid_button_auto_rejoins_after_inactivity_exclusion(self, mock_bot, mock_raid_control_interaction):
        """Tests that 'Join Raid' auto-adds user who was excluded for inactivity (no approval needed)."""
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 12345, "leader_id": 999})
        mock_bot.db.is_raid_member = AsyncMock(return_value=False)
        mock_bot.db.get_raid_member_exclusion_reason = AsyncMock(return_value="inactivity")
        mock_bot.db.add_raid_member = AsyncMock(return_value=True)
        mock_bot.db.remove_raid_member_exclusion = AsyncMock()
        mock_bot.db.delete_raid_join_request = AsyncMock()

        mock_thread = MagicMock(spec=discord.Thread)
        mock_thread.send = AsyncMock()
        mock_raid_control_interaction.channel = mock_thread
        mock_raid_control_interaction.user.bot = False

        await view.join_raid.callback(mock_raid_control_interaction)

        # Assert: user is added directly without approval
        mock_bot.db.add_raid_member.assert_called_once_with(1, mock_raid_control_interaction.user.id)
        mock_raid_control_interaction.followup.send.assert_called_with(
            "You have been added to the raid.",
            ephemeral=True,
        )

    async def test_join_raid_button_requires_approval_after_manual_exclusion(self, mock_bot, mock_raid_control_interaction):
        """Tests that 'Join Raid' requires approval when user was manually removed."""
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 12345, "leader_id": 999})
        mock_bot.db.is_raid_member = AsyncMock(return_value=False)
        mock_bot.db.get_raid_member_exclusion_reason = AsyncMock(return_value="manual")
        mock_bot.db.get_raid_join_request = AsyncMock(return_value=None)
        mock_bot.db.upsert_raid_join_request = AsyncMock()

        mock_thread = MagicMock(spec=discord.Thread)
        mock_thread.send = AsyncMock()
        mock_raid_control_interaction.channel = mock_thread
        mock_raid_control_interaction.user.bot = False

        leader_member = MagicMock(spec=discord.Member)
        leader_member.send = AsyncMock()
        mock_raid_control_interaction.guild.get_member.return_value = leader_member
        mock_raid_control_interaction.guild.fetch_member = AsyncMock(return_value=leader_member)

        await view.join_raid.callback(mock_raid_control_interaction)

        # Assert: join request is created, user is NOT auto-added
        mock_bot.db.upsert_raid_join_request.assert_called_once_with(1, mock_raid_control_interaction.user.id, source="button")
        mock_bot.db.add_raid_member.assert_not_called()
        mock_raid_control_interaction.followup.send.assert_called_with(
            "You were previously removed from this raid. Join request sent to the raid leader for approval.",
            ephemeral=True,
        )

    async def test_rename_thread_button_success_and_unauthorized(self, mock_bot, mock_raid_control_interaction):
        """Tests that 'Rename Thread' opens modal for leaders and rejects non-leaders."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "leader_id": 999})
        mock_bot.get_cog = MagicMock()
        mock_raid_cog = MagicMock()
        mock_bot.get_cog.return_value = mock_raid_cog

        # Simulate the interaction user is the raid leader
        mock_raid_control_interaction.user.id = 999

        # Act: leader opens modal
        await view.rename_thread.callback(mock_raid_control_interaction)

        # Assert: modal is sent
        mock_raid_control_interaction.response.send_modal.assert_called_once()

        # Arrange for unauthorized user
        mock_raid_control_interaction.user.id = 123  # Not the leader
        mock_raid_control_interaction.reset_mock()

        # Act: non-leader attempts rename
        await view.rename_thread.callback(mock_raid_control_interaction)

        # Assert: modal is not sent; error is sent
        mock_raid_control_interaction.response.send_modal.assert_not_called()
        mock_raid_control_interaction.response.send_message.assert_called_with(
            "You don't have permission to rename this thread.",
            ephemeral=True,
        )

    async def test_groups_button_opens_setup_modal_for_leader(self, mock_bot, mock_raid_control_interaction):
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "leader_id": mock_raid_control_interaction.user.id})

        mock_raid_cog = MagicMock()
        mock_bot.get_cog.return_value = mock_raid_cog

        with patch("discord_bot.ui.views.is_admin", new_callable=AsyncMock) as mock_is_admin:
            mock_is_admin.return_value = False
            mock_raid_control_interaction.response.send_modal = AsyncMock()
            await view.show_groups.callback(mock_raid_control_interaction)

        mock_raid_control_interaction.response.send_modal.assert_called_once()
        modal_sent = mock_raid_control_interaction.response.send_modal.call_args[0][0]
        assert isinstance(modal_sent, RaidGroupSetupModal)

    async def test_groups_button_shows_signup_panel_for_leader_when_groups_already_set_up(self, mock_bot, mock_raid_control_interaction):
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(
            return_value={"id": 1, "leader_id": mock_raid_control_interaction.user.id, "group_count": 3}
        )

        mock_raid_cog = MagicMock()
        mock_raid_cog._build_group_signup_embed = AsyncMock(return_value="embed_content")
        mock_bot.get_cog.return_value = mock_raid_cog

        mock_raid_control_interaction.guild = MockGuild(id=123)
        mock_raid_control_interaction.response.is_done = MagicMock(return_value=False)
        mock_raid_control_interaction.response.send_message = AsyncMock()
        mock_raid_control_interaction.followup.send = AsyncMock()
        mock_raid_control_interaction.response.send_modal = AsyncMock()

        with patch("discord_bot.ui.views.is_admin", new_callable=AsyncMock) as mock_is_admin:
            mock_is_admin.return_value = False
            await view.show_groups.callback(mock_raid_control_interaction)

        mock_raid_control_interaction.response.send_modal.assert_not_called()
        mock_raid_control_interaction.response.send_message.assert_called_once()
        _, kwargs = mock_raid_control_interaction.response.send_message.call_args
        assert kwargs.get("embed") == "embed_content"
        assert kwargs.get("ephemeral") is True
        assert isinstance(kwargs.get("view"), RaidGroupSignupModalView)

    async def test_groups_button_shows_signup_panel_for_non_leader(self, mock_bot, mock_raid_control_interaction):
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_guild_config = AsyncMock(return_value={"raid_member_list_order": "name"})
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "leader_id": 999, "group_count": 3})

        mock_raid_cog = MagicMock()
        mock_raid_cog._build_group_signup_embed = AsyncMock(return_value="embed_content")
        mock_bot.get_cog.return_value = mock_raid_cog

        # Simulate non-leader user
        mock_raid_control_interaction.user.id = 123
        mock_raid_control_interaction.guild = MockGuild(id=123)

        with patch("discord_bot.ui.views.is_admin", new_callable=AsyncMock) as mock_is_admin:
            mock_is_admin.return_value = False
            # Ensure response.is_done exists so the handler chooses response.send_message
            mock_raid_control_interaction.response.is_done = MagicMock(return_value=False)
            mock_raid_control_interaction.response.send_message = AsyncMock()
            mock_raid_control_interaction.followup.send = AsyncMock()
            mock_raid_control_interaction.response.send_modal = AsyncMock()

            await view.show_groups.callback(mock_raid_control_interaction)

        mock_raid_control_interaction.response.send_modal.assert_not_called()
        mock_raid_control_interaction.response.send_message.assert_called_once()
        _, kwargs = mock_raid_control_interaction.response.send_message.call_args
        assert kwargs.get("embed") == "embed_content"
        assert kwargs.get("ephemeral") is True
        # Validate we got the group signup modal-like view, not the raid control view
        assert isinstance(kwargs.get("view"), RaidGroupSignupModalView)


@patch('discord_bot.ui.views.ensure_allowed_guild', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_raid_open_panel_view_delegates_to_raid_cog(mock_ensure_allowed_guild, mock_bot, mock_interaction):
    mock_ensure_allowed_guild.return_value = True

    mock_raid_cog = MagicMock()
    mock_raid_cog.send_ephemeral_raid_panel = AsyncMock()
    mock_bot.db = MagicMock()
    mock_bot.db.get_raid_by_thread_any_state = AsyncMock(return_value={"id": 1, "is_active": 0})
    mock_bot.get_cog.return_value = mock_raid_cog
    mock_interaction.channel = MagicMock()
    mock_interaction.channel.id = 789

    view = RaidOpenPanelView(bot=mock_bot)
    await view.open_panel.callback(mock_interaction)

    mock_bot.db.get_raid_by_thread_any_state.assert_awaited_once_with(789)
    mock_raid_cog.send_ephemeral_raid_panel.assert_called_once_with(mock_interaction)


@patch('discord_bot.ui.views.ensure_allowed_guild', new_callable=AsyncMock)
@patch('discord_bot.ui.views.is_officer', new_callable=AsyncMock)
@patch('discord_bot.ui.views.is_admin', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_raid_popup_back_main_allows_closed_raid(mock_is_admin, mock_is_officer, mock_ensure_allowed_guild):
    mock_ensure_allowed_guild.return_value = True
    mock_is_admin.return_value = False
    mock_is_officer.return_value = False

    bot = MagicMock()
    bot.db = MagicMock()
    bot.db.get_raid_by_thread_any_state = AsyncMock(return_value={"id": 1, "leader_id": 456, "is_active": 0})

    guild = MockGuild(id=123)
    user = MockUser(id=456)
    user.display_name = "MockUser"
    interaction = MockInteraction(guild=guild, user=user)
    interaction.channel = MagicMock()
    interaction.channel.id = 789
    interaction.response.edit_message = AsyncMock()

    view = RaidPopupView(bot=bot, mode="help", can_manage=True, can_rename_thread=True, raid_is_active=False)
    await view.back_main.callback(interaction)

    bot.db.get_raid_by_thread_any_state.assert_awaited_once_with(789)
    interaction.response.edit_message.assert_awaited_once()
    _args, kwargs = interaction.response.edit_message.call_args
    assert isinstance(kwargs.get("view"), RaidPopupView)
    assert kwargs.get("view").mode == "main"
    embed = kwargs.get("embed")
    assert isinstance(embed, discord.Embed)
    assert embed.title == "Raid Panel for MockUser"


@pytest.mark.asyncio
async def test_raid_reverse_choice_cutoff_all_opens_modal(mock_bot, mock_interaction):
    mock_raid_cog = MagicMock()
    mock_bot.get_cog.return_value = mock_raid_cog
    view = RaidReverseDKPChoiceView(bot=mock_bot, source="persistent")

    await view.cutoff_all.callback(mock_interaction)

    mock_interaction.response.send_modal.assert_awaited_once()
    modal = mock_interaction.response.send_modal.call_args.args[0]
    assert isinstance(modal, RaidReverseFromCutoffModal)
    assert modal.timed_only is False


@pytest.mark.asyncio
async def test_raid_reverse_choice_cutoff_timed_opens_modal(mock_bot, mock_interaction):
    mock_raid_cog = MagicMock()
    mock_bot.get_cog.return_value = mock_raid_cog
    view = RaidReverseDKPChoiceView(bot=mock_bot, source="persistent")

    await view.cutoff_timed.callback(mock_interaction)

    mock_interaction.response.send_modal.assert_awaited_once()
    modal = mock_interaction.response.send_modal.call_args.args[0]
    assert isinstance(modal, RaidReverseFromCutoffModal)
    assert modal.timed_only is True

# Tests for AuctionBidView
from discord_bot.ui.views import AuctionBidView
from discord_bot.ui.modals import BidModal

@pytest.fixture
def mock_auction_bid_interaction(mock_interaction): # Re-use mock_interaction
    mock_interaction.response.send_modal = AsyncMock()
    return mock_interaction

@pytest.mark.asyncio
class TestAuctionBidView:
    async def test_bid_button(self, mock_bot, mock_auction_bid_interaction):
        """Tests that the 'Bid' button calls send_modal with BidModal."""
        # Arrange
        auction_id = 987
        view = AuctionBidView(bot=mock_bot, auction_id=auction_id)
        mock_auction_cog = AsyncMock()
        mock_bot.get_cog.return_value = mock_auction_cog

        # Act
        await view.bid.callback(mock_auction_bid_interaction)

        # Assert
        mock_auction_bid_interaction.response.send_modal.assert_called_once()
        modal_sent = mock_auction_bid_interaction.response.send_modal.call_args[0][0]
        assert isinstance(modal_sent, BidModal)
        assert modal_sent.title == "Place Your Bid"
        assert modal_sent.auction_id == auction_id
        assert modal_sent.auction_cog == mock_auction_cog
