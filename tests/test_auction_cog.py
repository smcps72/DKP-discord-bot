import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord # Added import

# Assuming your cog is in a directory named 'cogs'
# and the file is 'auction_cog.py'
# Adjust the import path as necessary
from discord_bot.cogs.auction_cog import AuctionCog
from discord_bot.ui.views import AuctionOpenPanelView

# Basic test structure
class TestAuctionCog(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = AsyncMock()
        self.bot.db = AsyncMock()
        self.cog = AuctionCog(self.bot)

        # Avoid unintended side effects from AuctionCog calling other cogs.
        self.bot.get_cog = MagicMock(return_value=None)

        # Mock interaction object
        self.interaction = AsyncMock()
        self.interaction.guild = MagicMock()
        self.interaction.channel = AsyncMock()
        self.interaction.user = MagicMock()

        # Mock voice channel and members
        self.mock_vc = MagicMock()
        self.member1 = AsyncMock() # Changed to AsyncMock
        self.member1.bot = False
        self.member1.id = 123
        self.member1.mention = "<@123>"
        self.member2 = AsyncMock() # Changed to AsyncMock
        self.member2.bot = False
        self.member2.id = 456
        self.member2.mention = "<@456>"
        self.mock_vc.members = [self.member1, self.member2]
        self.interaction.guild.get_channel.return_value = self.mock_vc

        # Mock bot.fetch_user
        self.bot.fetch_user = AsyncMock()

        # Mock interaction.guild.get_member
        self.interaction.guild.get_member = MagicMock()

    async def test_process_auction_start_success(self):
        # Mock DB calls
        self.bot.db.get_raid_by_thread.return_value = {'id': 1, 'vc_id': 12345, 'guild_id': 67890}
        self.bot.db.get_active_auction.return_value = None
        self.bot.db.execute_insert.return_value = 1
        self.bot.db.get_user_dkp.return_value = 100

        item_name = "Test Item"
        await self.cog.process_auction_start(self.interaction, item_name)

        # Verify interaction response
        self.interaction.response.defer.assert_called_once()
        self.interaction.followup.send.assert_called_once_with("Auction started.", ephemeral=True)

        # Verify DB calls
        self.bot.db.get_raid_by_thread.assert_called_once_with(self.interaction.channel.id)
        self.bot.db.get_active_auction.assert_called_once_with(1) # raid_id
        self.bot.db.execute_insert.assert_called_once_with(
            "INSERT INTO auctions (raid_id, item_name) VALUES (?, ?)",
            (1, item_name),
        )

        # Verify a public auction message with an Open Bid Panel view was sent
        self.interaction.channel.send.assert_called_once()
        _args, kwargs = self.interaction.channel.send.call_args
        self.assertIn(item_name, kwargs['embed'].title)
        self.assertIsInstance(kwargs['view'], AuctionOpenPanelView)

    async def test_process_auction_start_no_raid(self):
        self.bot.db.get_raid_by_thread.return_value = None
        item_name = "Test Item"
        await self.cog.process_auction_start(self.interaction, item_name)
        self.interaction.response.defer.assert_called_once()
        self.interaction.followup.send.assert_called_once()
        embed = self.interaction.followup.send.call_args[1]['embed']
        self.assertIn("This is not an active raid thread", embed.description)

    async def test_process_auction_start_auction_already_active(self):
        self.bot.db.get_raid_by_thread.return_value = {'id': 1, 'vc_id': 12345}
        self.bot.db.get_active_auction.return_value = {'id': 1, 'item_name': 'Another Item'}
        item_name = "Test Item"
        await self.cog.process_auction_start(self.interaction, item_name)
        self.interaction.response.defer.assert_called_once()
        self.interaction.followup.send.assert_called_once()
        embed = self.interaction.followup.send.call_args[1]['embed']
        self.assertIn("An auction is already in progress", embed.description)

    async def test_process_auction_start_vc_empty(self):
        self.bot.db.get_raid_by_thread.return_value = {'id': 1, 'vc_id': 12345}
        self.bot.db.get_active_auction.return_value = None
        self.mock_vc.members = [] # Empty VC
        item_name = "Test Item"
        await self.cog.process_auction_start(self.interaction, item_name)
        self.interaction.response.defer.assert_called_once()
        self.interaction.followup.send.assert_called_with("Raid voice channel is empty. Cannot start auction.", ephemeral=True)
        self.interaction.guild.get_channel.assert_called_once_with(12345)

    async def test_process_auction_start_no_dm_required(self):
        # With the new flow, we do not DM members; we post an in-thread message
        # that allows users to open an ephemeral bid panel.
        self.bot.db.get_raid_by_thread.return_value = {'id': 1, 'vc_id': 12345, 'guild_id': 67890}
        self.bot.db.get_active_auction.return_value = None
        self.bot.db.execute_insert.return_value = 1

        item_name = "Test Item"
        await self.cog.process_auction_start(self.interaction, item_name)

        self.interaction.channel.send.assert_called_once()
        _args, kwargs = self.interaction.channel.send.call_args
        self.assertIsInstance(kwargs['view'], AuctionOpenPanelView)

    async def test_process_bid_success_new_highest_bid(self):
        auction_id = 1
        bid_amount_str = "150"
        self.interaction.user.id = 456 # member2 is bidding

        # Mock DB calls
        self.bot.db.fetchone.side_effect = [
            {'id': auction_id, 'item_name': 'Test Item', 'highest_bid': 100, 'highest_bidder_id': 123, 'is_active': 1, 'guild_id': 67890}, # auction details
        ]
        self.bot.db.get_user_dkp.return_value = 200 # member2 DKP

        await self.cog.process_bid(self.interaction, auction_id, bid_amount_str)

        self.interaction.response.defer.assert_called_once_with(ephemeral=True)
        self.bot.db.fetchone.assert_called_once()
        self.bot.db.get_user_dkp.assert_called_once_with(self.interaction.user.id, 67890)

        # Standard edition does not notify the previous high bidder.
        self.bot.fetch_user.assert_not_called()

        # Check DB update
        self.bot.db.execute.assert_called_once_with(
            "UPDATE auctions SET highest_bid = ?, highest_bidder_id = ? WHERE id = ?",
            (150, self.interaction.user.id, auction_id)
        )
        # Check bid confirmation
        self.interaction.followup.send.assert_called_once()
        args_confirm, kwargs_confirm = self.interaction.followup.send.call_args
        self.assertIn("Bid Submitted", kwargs_confirm['embed'].title)
        self.assertIn("Your bid of **150 DKP**", kwargs_confirm['embed'].description)
        self.assertTrue(kwargs_confirm['ephemeral'])

    async def test_process_bid_invalid_amount_string(self):
        await self.cog.process_bid(self.interaction, 1, "not_a_number")
        self.interaction.response.send_message.assert_called_once_with("Bid must be a positive number.", ephemeral=True)

    async def test_process_bid_invalid_amount_zero(self):
        await self.cog.process_bid(self.interaction, 1, "0")
        self.interaction.response.send_message.assert_called_once_with("Bid must be a positive number.", ephemeral=True)

    async def test_process_bid_auction_ended(self):
        self.bot.db.fetchone.return_value = None # No active auction
        await self.cog.process_bid(self.interaction, 1, "100")
        self.interaction.response.defer.assert_called_once_with(ephemeral=True)
        self.interaction.followup.send.assert_called_once_with("This auction has ended.", ephemeral=True)

    async def test_process_bid_insufficient_dkp(self):
        auction_id = 1
        self.interaction.user.id = 456
        self.bot.db.fetchone.return_value = {'id': auction_id, 'item_name': 'Test Item', 'highest_bid': 50, 'highest_bidder_id': 123, 'is_active': 1, 'guild_id': 67890}
        self.bot.db.get_user_dkp.return_value = 90 # User has 90 DKP

        await self.cog.process_bid(self.interaction, auction_id, "100") # Bids 100 DKP

        self.interaction.response.defer.assert_called_once_with(ephemeral=True)
        self.interaction.followup.send.assert_called_once()
        args_followup, kwargs_followup = self.interaction.followup.send.call_args
        self.assertIn("exceeds your available DKP of **90**", args_followup[0]) # Message is sent as positional arg
        self.assertTrue(kwargs_followup['ephemeral'])


    async def test_process_bid_too_low(self):
        auction_id = 1
        self.interaction.user.id = 456
        self.bot.db.fetchone.return_value = {'id': auction_id, 'item_name': 'Test Item', 'highest_bid': 100, 'highest_bidder_id': 123, 'is_active': 1, 'guild_id': 67890}
        self.bot.db.get_user_dkp.return_value = 200

        await self.cog.process_bid(self.interaction, auction_id, "100") # Bid is equal to current highest

        self.interaction.response.defer.assert_called_once_with(ephemeral=True)
        self.interaction.followup.send.assert_called_once()
        args_followup, kwargs_followup = self.interaction.followup.send.call_args
        self.assertIn("Bid Submitted", kwargs_followup['embed'].title)
        self.assertIn("Your bid of **100 DKP**", kwargs_followup['embed'].description)
        self.assertTrue(kwargs_followup['ephemeral'])

    async def test_end_auction_from_button_success_with_winner(self):
        # Mock DB calls
        guild_id_value = 67890
        self.interaction.guild.id = guild_id_value # Ensure guild.id is set
        self.bot.db.get_raid_by_thread.return_value = {'id': 1, 'guild_id': guild_id_value}
        auction_data = {'id': 1, 'item_name': 'Shiny Sword', 'highest_bid': 200, 'highest_bidder_id': self.member1.id, 'is_active': 1}
        self.bot.db.get_active_auction.return_value = auction_data

        # Mock guild.get_member to return the winner
        self.interaction.guild.get_member.return_value = self.member1

        await self.cog.end_auction_from_button(self.interaction)

        self.bot.db.get_raid_by_thread.assert_called_once_with(self.interaction.channel.id)
        self.bot.db.get_active_auction.assert_called_once_with(1) # raid_id

        # Verify auction deactivation
        self.bot.db.execute.assert_any_call("UPDATE auctions SET is_active = 0 WHERE id = ?", (auction_data['id'],))

        # Verify DKP deduction
        self.bot.db.modify_user_dkp.assert_called_once_with(
            self.member1.id,
            self.interaction.guild.id, # Should be interaction.guild.id
            -auction_data['highest_bid'],
            f"Won auction for {auction_data['item_name']}"
        )

        # Verify winner announcement is posted publicly in the raid thread
        self.interaction.channel.send.assert_called_once()
        args_followup, kwargs_followup = self.interaction.channel.send.call_args
        embed = kwargs_followup['embed']
        self.assertIn(f"Auction Concluded: {auction_data['item_name']}", embed.title)
        self.assertIn(f"Congratulations to {self.member1.mention}", embed.description)
        self.assertIn(f"winning with a bid of **{auction_data['highest_bid']} DKP**", embed.description)

    async def test_end_auction_from_button_no_bids(self):
        self.bot.db.get_raid_by_thread.return_value = {'id': 1}
        auction_data_no_bids = {'id': 1, 'item_name': 'Dusty Shield', 'highest_bid': 0, 'highest_bidder_id': None, 'is_active': 1}
        self.bot.db.get_active_auction.return_value = auction_data_no_bids

        await self.cog.end_auction_from_button(self.interaction)

        self.bot.db.execute.assert_called_once_with("UPDATE auctions SET is_active = 0 WHERE id = ?", (auction_data_no_bids['id'],))
        self.bot.db.modify_user_dkp.assert_not_called() # No DKP change

        self.interaction.followup.send.assert_called_once()
        args_followup, kwargs_followup = self.interaction.followup.send.call_args
        embed = kwargs_followup['embed']
        self.assertIn("Auction Ended", embed.title)
        self.assertIn(f"auction for **{auction_data_no_bids['item_name']}** has ended with no bids", embed.description)

    async def test_end_auction_from_button_no_raid(self):
        self.bot.db.get_raid_by_thread.return_value = None
        await self.cog.end_auction_from_button(self.interaction)
        self.interaction.followup.send.assert_called_once()
        embed = self.interaction.followup.send.call_args[1]['embed']
        self.assertIn("This is not a raid thread", embed.description)
        self.bot.db.get_active_auction.assert_not_called()

    async def test_end_auction_from_button_no_active_auction(self):
        self.bot.db.get_raid_by_thread.return_value = {'id': 1}
        self.bot.db.get_active_auction.return_value = None # No active auction
        await self.cog.end_auction_from_button(self.interaction)
        self.interaction.followup.send.assert_called_once()
        embed = self.interaction.followup.send.call_args[1]['embed']
        self.assertIn("There is no active auction to end", embed.description)

    async def test_end_auction_from_button_winner_not_in_guild(self):
        # This tests the scenario where the winner might have left the server
        guild_id_value = 67890
        self.interaction.guild.id = guild_id_value # Ensure guild.id is set
        self.bot.db.get_raid_by_thread.return_value = {'id': 1, 'guild_id': guild_id_value}
        winner_id_left_guild = 999
        auction_data = {'id': 1, 'item_name': 'Vanished Relic', 'highest_bid': 50, 'highest_bidder_id': winner_id_left_guild, 'is_active': 1}
        self.bot.db.get_active_auction.return_value = auction_data

        self.interaction.guild.get_member.return_value = None # Winner not found in guild

        await self.cog.end_auction_from_button(self.interaction)

        self.bot.db.modify_user_dkp.assert_called_once_with(
            winner_id_left_guild,
            self.interaction.guild.id, # Should be interaction.guild.id
            -50,
            f"Won auction for {auction_data['item_name']}"
        )
        # Winner announcement is posted publicly even if the user left the guild
        self.interaction.channel.send.assert_called_once()
        args_followup, kwargs_followup = self.interaction.channel.send.call_args
        embed = kwargs_followup['embed']
        self.assertIn(f"User ID: {winner_id_left_guild}", embed.description) # Fallback to User ID


if __name__ == '__main__':
    unittest.main()
