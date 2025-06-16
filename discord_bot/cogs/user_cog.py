import discord
from discord.ext import commands
from discord import app_commands
from ..utils import create_info_embed

class UserCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def show_my_dkp(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        dkp = await self.bot.db.get_user_dkp(interaction.user.id, interaction.guild.id)
        embed = create_info_embed(
            f"💰 Your DKP Balance",
            f"You currently have **{dkp}** DKP."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="my_dkp", description="Check your DKP balance.")
    async def my_dkp_cmd(self, interaction: discord.Interaction):
        await self.show_my_dkp(interaction)

    async def show_auction_help(self, interaction: discord.Interaction):
        help_text = (
            "1. **Starting:** The Raid Leader starts an auction for an item.\n"
            "2. **Bidding:** You will receive a private message (or a hidden message in the raid thread) to bid.\n"
            "3. **Placing Bids:** Click 'Bid', enter your amount, and submit. You must have enough DKP.\n"
            "4. **Outbidding:** If someone bids higher, you'll be notified (if your DMs are open).\n"
            "5. **Winning:** The Raid Leader ends the auction. The highest bidder wins and the DKP is automatically deducted."
        )
        embed = create_info_embed("❓ Auction Help", help_text)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="auction_help", description="Explains how the auction system works.")
    async def auction_help_cmd(self, interaction: discord.Interaction):
        await self.show_auction_help(interaction)

async def setup(bot: commands.Bot):
    await bot.add_cog(UserCog(bot))
