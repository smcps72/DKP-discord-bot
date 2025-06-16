import discord
from discord.ext import commands
import asyncio
import logging
from ..utils import create_info_embed, create_error_embed, create_success_embed
from ..ui.views import AuctionBidView

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
        await self.bot.db.execute(
            "INSERT INTO auctions (raid_id, item_name) VALUES (?, ?)",
            (raid['id'], item_name)
        )
        auction_row = await self.bot.db.fetchone("SELECT id FROM auctions WHERE raid_id = ? AND is_active = 1", (raid['id'],))
        auction_id = auction_row['id']
        embed = create_info_embed(
            f"💎 Auction Started: {item_name}",
            "Bidding is now open! Check your DMs or look for a private message from me to bid."
        )
        await interaction.followup.send(embed=embed)
        # Send private bid invites
        for member in vc.members:
            if member.bot: continue
            dkp = await self.bot.db.get_user_dkp(member.id, interaction.guild.id)
            bid_embed = create_info_embed(
                f"Bid on: {item_name}",
                f"Your current DKP: **{dkp}**\n\nUse the buttons below to place your bid."
            )
            view = AuctionBidView(self.bot, auction_id)
            try:
                await member.send(embed=bid_embed, view=view)
            except discord.Forbidden:
                await interaction.channel.send(f"{member.mention}, I can't DM you! Please enable DMs or use this private message to bid.", embed=bid_embed, view=view, ephemeral=True)

    async def process_bid(self, interaction: discord.Interaction, auction_id: int, bid_amount_str: str):
        try:
            bid_amount = int(bid_amount_str)
            if bid_amount <= 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("Bid must be a positive number.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        auction = await self.bot.db.fetchone("SELECT * FROM auctions WHERE id = ? AND is_active = 1", (auction_id,))
        if not auction:
            return await interaction.followup.send("This auction has ended.", ephemeral=True)
        user_dkp = await self.bot.db.get_user_dkp(interaction.user.id, interaction.guild.id)
        if bid_amount > user_dkp:
            return await interaction.followup.send(f"Your bid of **{bid_amount}** exceeds your available DKP of **{user_dkp}**.", ephemeral=True)
        if bid_amount <= auction['highest_bid']:
            return await interaction.followup.send(f"You must bid higher than the current top bid of **{auction['highest_bid']} DKP**.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AuctionCog(bot))
