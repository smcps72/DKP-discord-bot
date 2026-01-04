import discord
from discord.ext import commands
from discord import app_commands
from ..utils import create_info_embed

class UserCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def show_my_dkp(self, interaction: discord.Interaction):
        # Ensure this command is used in a guild context
        guild = getattr(interaction, "guild", None)
        if not guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "This command can only be used inside a server.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "This command can only be used inside a server.",
                    ephemeral=True,
                )
            return

        # Ensure we've acknowledged the interaction before using followups
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        dkp = await self.bot.db.get_user_dkp(interaction.user.id, guild.id)
        embed = create_info_embed(
            f"💰 Your DKP Balance",
            f"You currently have **{dkp}** DKP."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            try:
                await raid_cog.maybe_send_control_panel_ephemeral(interaction)
            except Exception:
                pass

    @app_commands.command(name="my_dkp", description="Check your DKP balance.")
    async def my_dkp_cmd(self, interaction: discord.Interaction):
        await self.show_my_dkp(interaction)

    @app_commands.command(name="my_bid", description="Check your bid in the active raid auction (if any).")
    async def my_bid_cmd(self, interaction: discord.Interaction):
        guild = getattr(interaction, "guild", None)
        if not guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "This command can only be used inside a server.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "This command can only be used inside a server.",
                    ephemeral=True,
                )
            return

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send(
                "This channel is not associated with an active raid.",
                ephemeral=True,
            )

        auction = await self.bot.db.get_active_auction(raid["id"])
        if not auction:
            return await interaction.followup.send(
                "There is no active auction for this raid.",
                ephemeral=True,
            )

        bid_row = await self.bot.db.get_user_auction_bid(auction["id"], interaction.user.id)
        if not bid_row:
            return await interaction.followup.send(
                "You have not placed a bid for this auction yet.",
                ephemeral=True,
            )

        try:
            bid_amount = int(bid_row["amount"])
        except (KeyError, TypeError, ValueError):
            bid_amount = bid_row["amount"] if isinstance(bid_row, dict) and "amount" in bid_row else "Unknown"

        desc = (
            f"Raid ID: `{raid['id']}`\n"
            f"Auction Item: **{auction['item_name']}**\n"
            f"Your Bid: **{bid_amount} DKP**"
        )
        embed = create_info_embed("Your Current Auction Bid", desc)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="my_history", description="View your recent DKP history.")
    @app_commands.describe(limit="How many transactions to show (1-25)")
    async def my_history_cmd(self, interaction: discord.Interaction, limit: int = 10):
        guild = getattr(interaction, "guild", None)
        if not guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "This command can only be used inside a server.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "This command can only be used inside a server.",
                    ephemeral=True,
                )
            return

        limit = max(1, min(int(limit), 25))

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        rows = await self.bot.db.get_user_transactions(guild.id, interaction.user.id, limit=limit)
        if not rows:
            return await interaction.followup.send("No DKP history found yet.", ephemeral=True)

        lines: list[str] = []
        for r in rows:
            change = r["change"]
            reason = (r["reason"] or "").strip()
            ts = r["timestamp"]

            sign = "+" if isinstance(change, int) and change > 0 else ""
            short_reason = reason
            if len(short_reason) > 120:
                short_reason = short_reason[:117] + "..."

            lines.append(f"`{ts}`  **{sign}{change}**  {short_reason}")

        embed = create_info_embed(
            "Your DKP History",
            "\n".join(lines),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def show_auction_help(self, interaction: discord.Interaction):
        # Ensure this command is used in a guild context
        guild = getattr(interaction, "guild", None)
        if not guild:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "This command can only be used inside a server.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "This command can only be used inside a server.",
                    ephemeral=True,
                )
            return

        # Ensure we've acknowledged the interaction before using followups
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        help_text = (
            "1. **Starting:** The Raid Leader starts an auction for an item.\n"
            "2. **Bidding:** You will receive a private message (or a hidden message in the raid thread) to bid.\n"
            "3. **Placing Bids:** Click 'Bid', enter your amount, and submit. You must have enough DKP.\n"
            "4. **Outbidding:** If someone bids higher, you'll be notified (if your DMs are open).\n"
            "5. **Winning:** The Raid Leader ends the auction. The highest bidder wins and the DKP is automatically deducted."
        )
        embed = create_info_embed("❓ Auction Help", help_text)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="auction_help", description="Explains how the auction system works.")
    async def auction_help_cmd(self, interaction: discord.Interaction):
        await self.show_auction_help(interaction)

async def setup(bot: commands.Bot):
    await bot.add_cog(UserCog(bot))
