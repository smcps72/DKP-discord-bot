import pytest
from unittest.mock import MagicMock, AsyncMock, patch

import discord

from discord_bot.ui.views import WelcomeView, WelcomeLegacyView, DkpPanelView

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
    def __init__(self, guild, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guild = guild
        self.user = user
        self.response = MagicMock()
        self.response.defer = AsyncMock()
        self.response.send_message = AsyncMock()
        self.followup = MagicMock()
        self.followup.send = AsyncMock()

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


# Tests for RaidControlView
from discord_bot.ui.views import RaidControlView, DKPAdjustmentView
from discord_bot.ui.modals import DKPAdjustmentModal, AuctionStartModal
from discord_bot.ui.views import RaidOpenPanelView

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
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 12345})
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
        mock_raid_control_interaction.followup.send.assert_called_once()
        args, kwargs = mock_raid_control_interaction.followup.send.call_args
        assert "Who do you want to award DKP?" in args[0]
        assert isinstance(kwargs["view"], DKPAdjustmentView)
        assert kwargs["ephemeral"] is True

    async def test_deduct_dkp_button(self, mock_bot, mock_raid_control_interaction):
        """Tests that the 'Deduct DKP' button shows the DKPAdjustmentView for raid members."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 12345})
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
        mock_raid_control_interaction.followup.send.assert_called_once()
        args, kwargs = mock_raid_control_interaction.followup.send.call_args
        assert "Who do you want to deduct DKP?" in args[0]
        assert isinstance(kwargs["view"], DKPAdjustmentView)
        assert kwargs["ephemeral"] is True

    async def test_start_auction_button(self, mock_bot, mock_raid_control_interaction):
        """Tests that the 'Start Auction' button opens the item-name modal when preconditions are met."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
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
            "No eligible raid members were found. If you are in a voice channel, click \"Update Team\" to add all members in your voice channel to the raid. Or each member can click the \"Join Raid\" button. Cannot start auction.",
            ephemeral=True,
        )
        mock_raid_control_interaction.response.send_modal.assert_not_called()

    async def test_join_raid_button_adds_user_and_handles_duplicate(self, mock_bot, mock_raid_control_interaction):
        """Tests that 'Join Raid' submits a pending join request and prevents duplicates."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
        mock_bot.db.get_raid_by_thread = AsyncMock(return_value={"id": 1, "vc_id": 12345, "leader_id": 999})
        mock_bot.db.is_raid_member = AsyncMock(return_value=False)
        mock_bot.db.get_raid_join_request = AsyncMock(side_effect=[None, {"status": "pending"}])
        mock_bot.db.upsert_raid_join_request = AsyncMock()

        mock_thread = MagicMock(spec=discord.Thread)
        mock_thread.send = AsyncMock()
        mock_raid_control_interaction.channel = mock_thread
        mock_raid_control_interaction.user.bot = False

        # Act: first click submits request
        await view.join_raid.callback(mock_raid_control_interaction)

        # Assert: join request is created and user sees pending message
        mock_bot.db.upsert_raid_join_request.assert_called_once_with(1, mock_raid_control_interaction.user.id, source="button")
        mock_raid_control_interaction.followup.send.assert_called_with(
            "Join request sent to the raid leader for approval.",
            ephemeral=True,
        )

        # Reset only the followup.send mock to check the new message; keep add_raid_member calls intact
        mock_raid_control_interaction.followup.send.reset_mock()

        # Act: second click sees pending
        await view.join_raid.callback(mock_raid_control_interaction)

        # Assert: duplicate is rejected, no new upsert
        assert mock_bot.db.upsert_raid_join_request.call_count == 1
        mock_raid_control_interaction.followup.send.assert_called_with(
            "Your join request is already pending approval.",
            ephemeral=True,
        )

    async def test_rename_thread_button_success_and_unauthorized(self, mock_bot, mock_raid_control_interaction):
        """Tests that 'Rename Thread' opens modal for leaders and rejects non-leaders."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_bot.db = MagicMock()
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

        # Assert: modal is not sent; error followup is sent
        mock_raid_control_interaction.response.send_modal.assert_not_called()
        mock_raid_control_interaction.followup.send.assert_called_with("You don't have permission to rename this thread.", ephemeral=True)


@patch('discord_bot.ui.views.ensure_allowed_guild', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_raid_open_panel_view_delegates_to_raid_cog(mock_ensure_allowed_guild, mock_bot, mock_interaction):
    mock_ensure_allowed_guild.return_value = True

    mock_raid_cog = MagicMock()
    mock_raid_cog.send_ephemeral_raid_panel = AsyncMock()
    mock_bot.get_cog.return_value = mock_raid_cog

    view = RaidOpenPanelView(bot=mock_bot)
    await view.open_panel.callback(mock_interaction)

    mock_raid_cog.send_ephemeral_raid_panel.assert_called_once_with(mock_interaction)

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
