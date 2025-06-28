import discord
from discord.ext import commands
from discord import app_commands
from ..utils import is_officer, create_info_embed
import csv
import io

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="status", description="Check the bot's operational status.")
    @app_commands.checks.has_permissions(administrator=True)
    async def status_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.bot.db.get_guild_config(interaction.guild.id)
        license_status = config['license_status'].capitalize() if config else "Unknown"
        active_raids_count = await self.bot.db.fetchone("SELECT COUNT(*) as count FROM raids WHERE guild_id = ? AND is_active = 1", (interaction.guild.id,))
        embed = create_info_embed(
            "Bot Status",
            f"• **Discord API:** {self.bot.latency*1000:.2f}ms\n"
            f"• **Subscription:** `{license_status}`\n"
            f"• **Active Raids:** {active_raids_count['count']}"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="history", description="Downloads a CSV of the last 30 days of DKP transactions.")
    @app_commands.checks.has_permissions(administrator=True)
    async def history_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        records = await self.bot.db.fetchall(
            "SELECT user_id, change, reason, timestamp FROM transactions WHERE guild_id = ? AND timestamp >= date('now', '-30 days')",
            (interaction.guild.id,)
        )
        if not records:
            return await interaction.followup.send("No transaction history found for the last 30 days.", ephemeral=True)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Timestamp', 'User ID', 'User Name', 'DKP Change', 'Reason'])
        for rec in records:
            user = interaction.guild.get_member(rec['user_id']) or f"Unknown User ({rec['user_id']})"
            writer.writerow([rec['timestamp'], rec['user_id'], str(user), rec['change'], rec['reason']])
        output.seek(0)
        file = discord.File(io.BytesIO(output.read().encode()), filename="dkp_history.csv")
        await interaction.followup.send("Here is the DKP transaction history for the last 30 days:", file=file, ephemeral=True)

    @app_commands.command(name="list_members", description="List all members in this server (debug, forced sync)")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_members(self, interaction: discord.Interaction):
        members = interaction.guild.members
        await interaction.response.send_message(
            f"Members ({len(members)}): {', '.join([m.name for m in members])}",
            ephemeral=True
        )

    @app_commands.command(name="list_members_full", description="List all members using fetch_members (debug, forced sync)")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_members_full(self, interaction: discord.Interaction):
        members = [member async for member in interaction.guild.fetch_members(limit=None)]
        await interaction.response.send_message(
            f"Members ({len(members)}): {', '.join([m.name for m in members])}",
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
