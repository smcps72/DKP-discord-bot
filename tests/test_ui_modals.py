import pytest
from unittest.mock import MagicMock, AsyncMock

from discord_bot.ui.modals import DKPAdjustmentModal, AuctionStartModal, BidModal
from discord_bot.cogs.raid_cog import RaidCog
from discord_bot.cogs.auction_cog import AuctionCog

# Mock objects for testing
class MockInteraction(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.response = AsyncMock()
        self.followup = AsyncMock()

@pytest.fixture
def mock_interaction():
    return MockInteraction()

@pytest.fixture
def mock_raid_cog():
    cog = MagicMock(spec=RaidCog)
    cog.process_dkp_adjustment = AsyncMock()
    return cog

@pytest.fixture
def mock_auction_cog():
    cog = MagicMock(spec=AuctionCog)
    cog.process_auction_start = AsyncMock()
    cog.process_bid = AsyncMock()
    return cog

@pytest.mark.asyncio
class TestDKPAdjustmentModal:
    async def test_on_submit(self, mock_interaction, mock_raid_cog):
        # Arrange
        action = "Award"
        modal = DKPAdjustmentModal(action=action, raid_cog=mock_raid_cog)
        # Simulate user input by mocking the TextInput fields
        modal.amount = MagicMock()
        modal.amount.value = "10"
        modal.reason = MagicMock()
        modal.reason.value = "Test Reason"
        # The current implementation uses target_member_input when no member
        # is pre-selected, resolving via guild.get_member_named first.
        modal.target_member_input = MagicMock()
        modal.target_member_input.value = "TargetUser"
        mock_member = MagicMock()
        mock_interaction.guild = MagicMock()
        mock_interaction.guild.get_member_named.return_value = mock_member

        # Act
        await modal.on_submit(mock_interaction)

        # Assert
        mock_raid_cog.process_dkp_adjustment.assert_called_once_with(
            mock_interaction,
            action,
            "10",
            "Test Reason",
            mock_member,
        )

@pytest.mark.asyncio
class TestAuctionStartModal:
    async def test_on_submit(self, mock_interaction, mock_auction_cog):
        # Arrange
        modal = AuctionStartModal(auction_cog=mock_auction_cog)
        # Simulate user input by mocking the TextInput field
        modal.item_name = MagicMock()
        modal.item_name.value = "Test Item"

        # Act
        await modal.on_submit(mock_interaction)

        # Assert
        mock_auction_cog.process_auction_start.assert_called_once_with(
            mock_interaction,
            "Test Item"
        )

@pytest.mark.asyncio
class TestBidModal:
    async def test_on_submit(self, mock_interaction, mock_auction_cog):
        # Arrange
        auction_id = 123
        modal = BidModal(auction_cog=mock_auction_cog, auction_id=auction_id)
        # Simulate user input by mocking the TextInput field
        modal.bid_amount = MagicMock()
        modal.bid_amount.value = "100"

        # Act
        await modal.on_submit(mock_interaction)

        # Assert
        mock_auction_cog.process_bid.assert_called_once_with(
            mock_interaction,
            auction_id,
            "100"
        )
