import pytest
from unittest.mock import MagicMock, AsyncMock

from discord_bot.ui.modals import DKPAdjustmentModal, AuctionStartModal, BidModal, RaidGroupSetupModal, RaidTimedAwardModal
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
    cog.configure_timed_award = AsyncMock()
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
            members=None,
            group_number=None,
            source=None,
            include_group_numbers=None,
            exclude_member_ids=None,
            exclude_group_numbers=None,
            popup_message=None,
        )

    async def test_on_submit_parses_exclusions(self, mock_interaction, mock_raid_cog):
        action = "Award"
        modal = DKPAdjustmentModal(action=action, raid_cog=mock_raid_cog)

        modal.amount = MagicMock()
        modal.amount.value = "10"
        modal.reason = MagicMock()
        modal.reason.value = "Test Reason"

        modal.target_member_input = MagicMock()
        modal.target_member_input.value = ""

        modal.exclude_groups_input = MagicMock()
        modal.exclude_groups_input.value = "1, 2"

        modal.include_groups_input = MagicMock()
        modal.include_groups_input.value = ""

        modal.exclude_members_input = MagicMock()
        modal.exclude_members_input.value = "<@123>, 456"

        mock_interaction.guild = MagicMock()

        await modal.on_submit(mock_interaction)

        mock_raid_cog.process_dkp_adjustment.assert_called_once_with(
            mock_interaction,
            action,
            "10",
            "Test Reason",
            None,
            members=None,
            group_number=None,
            source=None,
            include_group_numbers=None,
            exclude_member_ids={123, 456},
            exclude_group_numbers={1, 2},
            popup_message=None,
        )

    async def test_on_submit_parses_included_groups(self, mock_interaction, mock_raid_cog):
        action = "Award"
        modal = DKPAdjustmentModal(action=action, raid_cog=mock_raid_cog)

        modal.amount = MagicMock()
        modal.amount.value = "10"
        modal.reason = MagicMock()
        modal.reason.value = "Test Reason"

        modal.target_member_input = MagicMock()
        modal.target_member_input.value = ""

        modal.include_groups_input = MagicMock()
        modal.include_groups_input.value = "1, 2"

        modal.exclude_groups_input = MagicMock()
        modal.exclude_groups_input.value = ""

        modal.exclude_members_input = MagicMock()
        modal.exclude_members_input.value = ""

        mock_interaction.guild = MagicMock()

        await modal.on_submit(mock_interaction)

        mock_raid_cog.process_dkp_adjustment.assert_called_once_with(
            mock_interaction,
            action,
            "10",
            "Test Reason",
            None,
            members=None,
            group_number=None,
            source=None,
            include_group_numbers={1, 2},
            exclude_member_ids=None,
            exclude_group_numbers=None,
            popup_message=None,
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
            "Test Item",
            source=None,
            popup_can_manage=False,
            popup_can_rename_thread=False,
            popup_message=None,
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


@pytest.mark.asyncio
class TestRaidGroupSetupModal:
    async def test_on_submit_delegates_to_raid_cog(self, mock_interaction):
        raid_cog = MagicMock()
        raid_cog.setup_raid_groups = AsyncMock()

        modal = RaidGroupSetupModal(raid_cog=raid_cog)
        modal.group_count = MagicMock()
        modal.group_count.value = "4"

        await modal.on_submit(mock_interaction)

        raid_cog.setup_raid_groups.assert_called_once_with(mock_interaction, 4)


@pytest.mark.asyncio
class TestRaidTimedAwardModal:
    async def test_on_submit_delegates_to_raid_cog(self, mock_interaction, mock_raid_cog):
        modal = RaidTimedAwardModal(raid_cog=mock_raid_cog)
        modal.amount = MagicMock()
        modal.amount.value = "5"
        modal.interval_minutes = MagicMock()
        modal.interval_minutes.value = "30"

        await modal.on_submit(mock_interaction)

        mock_raid_cog.configure_timed_award.assert_called_once_with(
            mock_interaction,
            amount=5,
            interval_minutes=30,
            source=None,
            popup_message=None,
        )
