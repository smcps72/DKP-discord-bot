import discord
from discord.ext import commands
from discord import app_commands
from ..utils import is_officer, create_info_embed
import csv
import io
from datetime import datetime

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _create_status_embed(self, guild_id: int) -> discord.Embed:
        config = await self.bot.db.get_guild_config(guild_id)
        license_status = config['license_status'].capitalize() if config else "Unknown"
        active_raids_count = await self.bot.db.fetchone("SELECT COUNT(*) as count FROM raids WHERE guild_id = ? AND is_active = 1", (guild_id,))
        return create_info_embed(
            "Bot Status",
            f"• **Discord API:** {self.bot.latency*1000:.2f}ms\n"
            f"• **Subscription:** `{license_status}`\n"
            f"• **Active Raids:** {active_raids_count['count']}"
        )

    @app_commands.command(name="status", description="Check the bot's operational status.")
    @app_commands.checks.has_permissions(administrator=True)
    async def status_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = await self._create_status_embed(interaction.guild.id)
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

    @app_commands.command(name="debug_config", description="Show DKP configuration for this server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def debug_config(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        config = await self.bot.db.get_guild_config(interaction.guild.id)
        if not config:
            return await interaction.followup.send("No guild configuration found in the database.", ephemeral=True)

        guild = interaction.guild

        def fmt_channel(channel_id):
            if not channel_id:
                return "None"
            channel = guild.get_channel(channel_id)
            return f"{channel.mention} (`{channel_id}`)" if channel else f"Missing channel (`{channel_id}`)"

        def fmt_role(role_id):
            if not role_id:
                return "None"
            role = guild.get_role(role_id)
            return f"{role.mention} (`{role_id}`)" if role else f"Missing role (`{role_id}`)"

        ts = int(datetime.utcnow().timestamp())
        description = (
            f"**Guild ID:** `{config['guild_id']}`\n"
            f"**License Status:** `{config['license_status']}`\n"
            f"**DKP Category:** {fmt_channel(config['dkp_category_id'])}\n"
            f"**DKP Channel:** {fmt_channel(config['dkp_channel_id'])}\n"
            f"**Raid Channel:** {fmt_channel(config['raid_channel_id'])}\n"
            f"**Officer Role:** {fmt_role(config['officer_role_id'])}\n"
            f"**Raider Role:** {fmt_role(config['raider_role_id'])}\n"
            f"**Raid Leader Role:** {fmt_role(config['raid_leader_role_id'])}\n"
            f"**Raid VC Template:** {fmt_channel(config['raid_vc_template_id'])}\n"
            f"**Default DKP Award:** `{config['default_dkp_award']}`\n"
            f"**Generated At:** <t:{ts}:F>"
        )

        embed = create_info_embed("Guild Configuration Debug", description)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.command(name="debug_config", help="Show DKP configuration for this server (prefix version).")
    @commands.has_permissions(administrator=True)
    async def debug_config_prefix(self, ctx: commands.Context):
        guild = ctx.guild
        if guild is None:
            return await ctx.reply("This command can only be used in a server.")

        config = await self.bot.db.get_guild_config(guild.id)
        if not config:
            return await ctx.reply("No guild configuration found in the database.")

        def fmt_channel(channel_id):
            if not channel_id:
                return "None"
            channel = guild.get_channel(channel_id)
            return f"{channel.mention} (`{channel_id}`)" if channel else f"Missing channel (`{channel_id}`)"

        def fmt_role(role_id):
            if not role_id:
                return "None"
            role = guild.get_role(role_id)
            return f"{role.mention} (`{role_id}`)" if role else f"Missing role (`{role_id}`)"

        ts = int(datetime.utcnow().timestamp())
        description = (
            f"**Guild ID:** `{config['guild_id']}`\n"
            f"**License Status:** `{config['license_status']}`\n"
            f"**DKP Category:** {fmt_channel(config['dkp_category_id'])}\n"
            f"**DKP Channel:** {fmt_channel(config['dkp_channel_id'])}\n"
            f"**Raid Channel:** {fmt_channel(config['raid_channel_id'])}\n"
            f"**Officer Role:** {fmt_role(config['officer_role_id'])}\n"
            f"**Raider Role:** {fmt_role(config['raider_role_id'])}\n"
            f"**Raid Leader Role:** {fmt_role(config['raid_leader_role_id'])}\n"
            f"**Raid VC Template:** {fmt_channel(config['raid_vc_template_id'])}\n"
            f"**Default DKP Award:** `{config['default_dkp_award']}`\n"
            f"**Generated At:** <t:{ts}:F>"
        )

        embed = create_info_embed("Guild Configuration Debug", description)
        await ctx.reply(embed=embed)

    async def set_role(self, interaction: discord.Interaction, role_type: str, role: discord.Role):
        await self.bot.db.execute(
            f"UPDATE guilds SET {role_type.lower()}_role_id = ? WHERE guild_id = ?",
            (role.id, interaction.guild.id)
        )
        await interaction.response.send_message(f"{role_type} role has been updated to {role.mention}.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
