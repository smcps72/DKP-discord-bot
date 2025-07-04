import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from discord_bot.ui.views import WelcomeView

# Mock objects for testing
class MockGuild(MagicMock):
    def __init__(self, id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.id = id

class MockUser(MagicMock):
    def __init__(self, id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.id = id

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
    """Tests that the 'Create Raid' button defers and calls the correct cog method."""
    # Arrange
    mock_raid_cog = MagicMock()
    mock_raid_cog.create_raid_from_interaction = AsyncMock()
    mock_bot.get_cog.return_value = mock_raid_cog
    view = WelcomeView(bot=mock_bot)

    # Act
    await view.create_raid.callback(mock_interaction)

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True, thinking=True)
    mock_raid_cog.create_raid_from_interaction.assert_called_once_with(mock_interaction)

@pytest.mark.asyncio
async def test_welcome_view_my_dkp_button(mock_bot, mock_interaction):
    """Tests that the 'My DKP' button defers and calls the correct cog method."""
    # Arrange
    mock_user_cog = MagicMock()
    mock_user_cog.show_my_dkp = AsyncMock()
    mock_bot.get_cog.return_value = mock_user_cog
    view = WelcomeView(bot=mock_bot)

    # Act
    await view.my_dkp.callback(mock_interaction)

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_user_cog.show_my_dkp.assert_called_once_with(mock_interaction)

@patch('discord_bot.ui.views.is_officer', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_welcome_view_admin_button_as_officer(mock_is_officer, mock_bot, mock_interaction):
    """Tests the admin button for an authorized officer."""
    # Arrange
    mock_is_officer.return_value = True
    mock_admin_cog = MagicMock()
    mock_admin_cog._create_status_embed = AsyncMock(return_value="embed_content")
    mock_bot.get_cog.return_value = mock_admin_cog
    view = WelcomeView(bot=mock_bot)

    # Act
    await view.admin_panel.callback(mock_interaction)

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_is_officer.assert_called_once_with(mock_interaction)
    mock_admin_cog._create_status_embed.assert_called_once_with(mock_interaction.guild.id)
    mock_interaction.followup.send.assert_called_once_with(embed="embed_content", ephemeral=True)

@patch('discord_bot.ui.views.is_officer', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_welcome_view_admin_button_as_non_officer(mock_is_officer, mock_bot, mock_interaction):
    """Tests the admin button for a non-officer."""
    # Arrange
    mock_is_officer.return_value = False
    view = WelcomeView(bot=mock_bot)

    # Act
    await view.admin_panel.callback(mock_interaction)

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_is_officer.assert_called_once_with(mock_interaction)
    mock_interaction.followup.send.assert_called_once_with("You must be an officer to use this.", ephemeral=True)


# Tests for RaidControlView
from discord_bot.ui.views import RaidControlView
from discord_bot.ui.modals import DKPAdjustmentModal, AuctionStartModal

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
        """Tests that the 'Award DKP' button calls send_modal with DKPAdjustmentModal."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_raid_cog = AsyncMock()
        mock_bot.get_cog.return_value = mock_raid_cog

        # Act
        await view.award_dkp.callback(mock_raid_control_interaction)

        # Assert
        mock_raid_control_interaction.response.send_modal.assert_called_once()
        modal_sent = mock_raid_control_interaction.response.send_modal.call_args[0][0]
        assert isinstance(modal_sent, DKPAdjustmentModal)
        assert modal_sent.title == "DKP Adjustment"
        assert modal_sent.action == "Award"
        assert modal_sent.raid_cog == mock_raid_cog

    async def test_deduct_dkp_button(self, mock_bot, mock_raid_control_interaction):
        """Tests that the 'Deduct DKP' button calls send_modal with DKPAdjustmentModal."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
        mock_raid_cog = AsyncMock()
        mock_bot.get_cog.return_value = mock_raid_cog

        # Act
        await view.deduct_dkp.callback(mock_raid_control_interaction)

        # Assert
        mock_raid_control_interaction.response.send_modal.assert_called_once()
        modal_sent = mock_raid_control_interaction.response.send_modal.call_args[0][0]
        assert isinstance(modal_sent, DKPAdjustmentModal)
        assert modal_sent.title == "DKP Adjustment"
        assert modal_sent.action == "Deduct"
        assert modal_sent.raid_cog == mock_raid_cog

    async def test_start_auction_button(self, mock_bot, mock_raid_control_interaction):
        """Tests that the 'Start Auction' button calls send_modal with AuctionStartModal."""
        # Arrange
        view = RaidControlView(bot=mock_bot)
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
