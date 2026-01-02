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
                await raid_cog.send_ephemeral_raid_panel(interaction)
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
        try:
            highest_bid = int(auction["highest_bid"] or 0)
        except Exception:
            highest_bid = 0

        desc = (
            f"Your DKP: **{user_dkp}**\n"
            f"Current high bid: **{highest_bid}**\n\n"
            "Use **Bid** to place/raise your bid, or **Withdraw Bid** to remove your current top bid."
        )
        embed = create_info_embed(f"Bid on: {auction['item_name']}", desc)
        view = AuctionBidView(self.bot, auction_id)

        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def withdraw_bid(self, interaction: discord.Interaction, auction_id: int):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        auction_details_query = """
            SELECT a.*, r.guild_id, r.thread_id
            FROM auctions a
            JOIN raids r ON a.raid_id = r.id
            WHERE a.id = ? AND a.is_active = 1
        """
        auction = await self.bot.db.fetchone(auction_details_query, (auction_id,))
        if not auction:
            return await interaction.followup.send("This auction has ended.", ephemeral=True)

        try:
            highest_bidder_id = auction["highest_bidder_id"]
        except Exception:
            highest_bidder_id = None
        if not highest_bidder_id or int(highest_bidder_id) != interaction.user.id:
            return await interaction.followup.send(
                "You don't have the current top bid to withdraw.",
                ephemeral=True,
            )

        await self.bot.db.execute(
            "UPDATE auctions SET highest_bid = 0, highest_bidder_id = NULL WHERE id = ?",
            (auction_id,),
        )

        # Note: We do not currently track full bid history, so withdrawing the
        # top bid resets the auction back to 0.
        try:
            thread = None
            try:
                thread_id = auction["thread_id"]
            except Exception:
                thread_id = None
            if thread_id:
                thread = self.bot.get_channel(int(thread_id))
                if thread is None:
                    thread = await self.bot.fetch_channel(int(thread_id))
            if thread:
                await thread.send(
                    embed=create_info_embed(
                        "Bid Withdrawn",
                        f"{interaction.user.mention} withdrew their top bid for **{auction['item_name']}**. Bidding is open again.",
                    )
                )
        except Exception:
            pass

        await interaction.followup.send(
            embed=create_success_embed(
                "Bid Withdrawn",
                "Your top bid has been removed. You may bid again at any time before the auction ends.",
            ),
            ephemeral=True,
        )

    async def process_bid(self, interaction: discord.Interaction, auction_id: int, bid_amount_str: str):
        try:
            bid_amount = int(bid_amount_str)
            if bid_amount <= 0: raise ValueError
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

        guild_id = auction['guild_id']
        user_dkp = await self.bot.db.get_user_dkp(interaction.user.id, guild_id)
        
        if bid_amount > user_dkp:
            return await interaction.followup.send(f"Your bid of **{bid_amount}** exceeds your available DKP of **{user_dkp}**.", ephemeral=True)
        
        if bid_amount <= auction['highest_bid']:
            return await interaction.followup.send(f"You must bid higher than the current top bid of **{auction['highest_bid']} DKP**.", ephemeral=True)

        # Notify previous high bidder
        previous_high_bidder_id = auction['highest_bidder_id']
        if previous_high_bidder_id and previous_high_bidder_id != interaction.user.id:
            try:
                previous_bidder = await self.bot.fetch_user(previous_high_bidder_id)
                outbid_embed = create_error_embed(
                    "You've been outbid!",
                    f"Your bid for **{auction['item_name']}** has been surpassed. The new high bid is **{bid_amount} DKP**."
                )
                await previous_bidder.send(embed=outbid_embed)
            except (discord.NotFound, discord.Forbidden):
                # Fall back to a public ping in the raid thread if DMs are disabled.
                try:
                    thread = None
                    try:
                        thread_id = auction["thread_id"]
                    except Exception:
                        thread_id = None
                    if thread_id:
                        thread = self.bot.get_channel(int(thread_id))
                        if thread is None:
                            thread = await self.bot.fetch_channel(int(thread_id))
                    if thread:
                        await thread.send(
                            embed=create_error_embed(
                                "You've been outbid!",
                                f"<@{previous_high_bidder_id}> your bid for **{auction['item_name']}** was surpassed. New high bid: **{bid_amount} DKP**.",
                            )
                        )
                except Exception:
                    pass

        # Update DB with new highest bid
        await self.bot.db.execute(
            "UPDATE auctions SET highest_bid = ?, highest_bidder_id = ? WHERE id = ?",
            (bid_amount, interaction.user.id, auction_id)
        )

        # Confirm successful bid
        await interaction.followup.send(embed=create_success_embed(
            "Bid Placed Successfully!", 
            f"Your bid of **{bid_amount} DKP** for **{auction['item_name']}** is currently the highest."
        ), ephemeral=True)

    async def end_auction_from_button(self, interaction: discord.Interaction):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send(embed=create_error_embed("Error", "This is not a raid thread."), ephemeral=True)

        auction = await self.bot.db.get_active_auction(raid['id'])
        if not auction:
            return await interaction.followup.send(embed=create_error_embed("Error", "There is no active auction to end."), ephemeral=True)

        # Deactivate auction
        await self.bot.db.execute("UPDATE auctions SET is_active = 0 WHERE id = ?", (auction['id'],))

        if not auction['highest_bidder_id']:
            embed = create_info_embed("Auction Ended", f"The auction for **{auction['item_name']}** has ended with no bids.")
            return await interaction.followup.send(embed=embed)

        winner = interaction.guild.get_member(auction['highest_bidder_id'])
        winner_name = winner.mention if winner else f"User ID: {auction['highest_bidder_id']}"

        # Deduct DKP
        if auction['highest_bidder_id']:
            await self.bot.db.modify_user_dkp(auction['highest_bidder_id'], interaction.guild.id, -auction['highest_bid'], f"Won auction for {auction['item_name']}")

        embed = create_success_embed(
            f"Auction Concluded: {auction['item_name']}",
            f"Congratulations to {winner_name} for winning with a bid of **{auction['highest_bid']} DKP**!"
        )
        # Post winner publicly in the raid thread so everyone can see the result.
        await interaction.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AuctionCog(bot))
