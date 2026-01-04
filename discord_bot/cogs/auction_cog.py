import discord
from discord.ext import commands
import asyncio
import logging
from ..utils import create_info_embed, create_error_embed, create_success_embed
from ..ui.views import AuctionBidView, AuctionOpenPanelView

class AuctionCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def process_auction_start(self, interaction: discord.Interaction, item_name: str):
        await interaction.response.defer()
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send(embed=create_error_embed("Error", "This is not an active raid thread."), ephemeral=True)
        active_auction = await self.bot.db.get_active_auction(raid['id'])
        if active_auction:
            return await interaction.followup.send(embed=create_error_embed("Error", "An auction is already in progress for this raid."), ephemeral=True)
        vc = interaction.guild.get_channel(raid['vc_id'])
        if not vc or not vc.members:
            return await interaction.followup.send("Raid voice channel is empty. Cannot start auction.", ephemeral=True)
        # Create auction in DB
        auction_id = await self.bot.db.execute_insert(
            "INSERT INTO auctions (raid_id, item_name) VALUES (?, ?)",
            (raid['id'], item_name),
        )

        embed = create_info_embed(
            f"💎 Auction Started: {item_name}",
            "Bidding is now open!\n\n"
            "Click **Open Bid Panel** below to get a private (ephemeral) bidding panel."
        )
        panel_view = AuctionOpenPanelView(self.bot)
        msg = await interaction.channel.send(embed=embed, view=panel_view)

        # Always close out the deferred interaction with an ephemeral confirmation.
        try:
            await interaction.followup.send("Auction started.", ephemeral=True)
        except Exception:
            pass

        # Store the message id so future enhancements (like updating the embed)
        # can locate the canonical auction message.
        try:
            await self.bot.db.execute(
                "UPDATE auctions SET message_id = ? WHERE id = ?",
                (msg.id, auction_id),
            )
        except Exception:
            pass

        # Re-show raid control panel to the leader/admin so "End Auction" is
        # easy to reach without scrolling.
        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            try:
                await raid_cog.maybe_send_control_panel_ephemeral(interaction, raid=raid)
            except Exception:
                pass

    async def send_bid_panel(self, interaction: discord.Interaction, auction_id: int):
        """Send an ephemeral bid panel to the user."""
        # Get auction details and the associated guild_id (bids may come from DMs)
        auction_details_query = """
            SELECT a.*, r.guild_id, r.thread_id
            FROM auctions a
            JOIN raids r ON a.raid_id = r.id
            WHERE a.id = ? AND a.is_active = 1
        """
        auction = await self.bot.db.fetchone(auction_details_query, (auction_id,))
        if not auction:
            if not interaction.response.is_done():
                return await interaction.response.send_message("This auction has ended.", ephemeral=True)
            return await interaction.followup.send("This auction has ended.", ephemeral=True)

        guild_id = auction["guild_id"]
        user_dkp = await self.bot.db.get_user_dkp(interaction.user.id, guild_id)

        desc = (
            f"Your DKP: **{user_dkp}**\n\n"
            "Use **Bid** to place your single secret bid for this item. "
            "You can bid any positive amount up to your available DKP; only your first bid counts."
        )
        embed = create_info_embed(f"Bid on: {auction['item_name']}", desc)
        view = AuctionBidView(self.bot, auction_id)

        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            try:
                await raid_cog.maybe_send_control_panel_ephemeral(interaction)
            except Exception:
                pass

    async def process_bid(self, interaction: discord.Interaction, auction_id: int, bid_amount_str: str):
        try:
            bid_amount = int(bid_amount_str)
            if bid_amount <= 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("Bid must be a positive number.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # Get auction details and the associated guild_id to handle bids from DMs
        auction_details_query = """
            SELECT a.*, r.guild_id, r.thread_id
            FROM auctions a
            JOIN raids r ON a.raid_id = r.id
            WHERE a.id = ? AND a.is_active = 1
        """
        auction = await self.bot.db.fetchone(auction_details_query, (auction_id,))

        if not auction:
            return await interaction.followup.send("This auction has ended.", ephemeral=True)

        guild_id = auction["guild_id"]
        user_dkp = await self.bot.db.get_user_dkp(interaction.user.id, guild_id)

        if bid_amount > user_dkp:
            await interaction.followup.send(
                f"Your bid of **{bid_amount}** exceeds your available DKP of **{user_dkp}**.",
                ephemeral=True,
            )

            raid_cog = self.bot.get_cog("RaidCog")
            if raid_cog:
                try:
                    await raid_cog.maybe_send_control_panel_ephemeral(interaction)
                except Exception:
                    pass
            return

        # Enforce a single bid per user per auction.
        existing_bid = await self.bot.db.get_user_auction_bid(auction_id, interaction.user.id)
        if existing_bid is not None:
            await interaction.followup.send(
                embed=create_success_embed(
                    "Bid Already Placed",
                    "You have already placed a bid for this auction. "
                    "Only your first bid counts.",
                ),
                ephemeral=True,
            )

            raid_cog = self.bot.get_cog("RaidCog")
            if raid_cog:
                try:
                    await raid_cog.maybe_send_control_panel_ephemeral(interaction)
                except Exception:
                    pass
            return

        # Record the user's single bid without revealing any information about
        # other bidders or bid ordering.
        await self.bot.db.record_auction_bid(auction_id, interaction.user.id, bid_amount)

        await interaction.followup.send(
            embed=create_success_embed(
                "Bid Submitted",
                f"Your bid of **{bid_amount} DKP** for **{auction['item_name']}** has been received.",
            ),
            ephemeral=True,
        )

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            try:
                await raid_cog.maybe_send_control_panel_ephemeral(interaction)
            except Exception:
                pass

    async def end_auction_from_button(self, interaction: discord.Interaction):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send(embed=create_error_embed("Error", "This is not a raid thread."), ephemeral=True)

        auction = await self.bot.db.get_active_auction(raid['id'])
        if not auction:
            return await interaction.followup.send(embed=create_error_embed("Error", "There is no active auction to end."), ephemeral=True)

        # Deactivate auction
        await self.bot.db.execute("UPDATE auctions SET is_active = 0 WHERE id = ?", (auction['id'],))
        # Determine the winner based on recorded bids instead of a mutable
        # highest_bid field on the auction itself.
        bids = await self.bot.db.fetchall(
            "SELECT user_id, amount, created_at FROM auction_bids WHERE auction_id = ?",
            (auction["id"],),
        )

        if not bids:
            embed = create_info_embed(
                "Auction Ended",
                f"The auction for **{auction['item_name']}** has ended with no bids.",
            )
            return await interaction.followup.send(embed=embed)

        # Pick the highest bid; if there is a tie on amount, the earliest
        # created_at wins.
        bids_sorted = sorted(
            bids,
            key=lambda row: (-int(row["amount"]), row["created_at"]),
        )
        winning_bid = bids_sorted[0]
        winning_user_id = winning_bid["user_id"]
        winning_amount = int(winning_bid["amount"])

        winner = interaction.guild.get_member(winning_user_id)
        winner_name = winner.mention if winner else f"User ID: {winning_user_id}"

        # Deduct DKP from the winner.
        await self.bot.db.modify_user_dkp(
            winning_user_id,
            interaction.guild.id,
            -winning_amount,
            f"Won auction for {auction['item_name']}",
        )

        embed = create_success_embed(
            f"Auction Concluded: {auction['item_name']}",
            f"Congratulations to {winner_name} for winning with a bid of **{winning_amount} DKP**!",
        )
        # Post winner publicly in the raid thread so everyone can see the result.
        await interaction.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AuctionCog(bot))
