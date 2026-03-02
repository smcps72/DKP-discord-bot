import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from typing import Literal
import os
from pathlib import Path
from .. import __version__
from ..utils import is_admin, is_officer, create_info_embed
from ..ui.modals import AdminDKPAdjustModal
import csv
import io
from datetime import datetime

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._history_cooldowns: dict[int, float] = {}

    async def _create_status_basic_embed(self, guild_id: int) -> discord.Embed:
        config = await self.bot.db.get_guild_config(guild_id)
        license_status = config['license_status'].capitalize() if config else "Unknown"
        active_raids_count = await self.bot.db.fetchone("SELECT COUNT(*) as count FROM raids WHERE guild_id = ? AND is_active = 1", (guild_id,))
        return create_info_embed(
            "Bot Status",
            f"• **Version:** `{__version__}`\n"
            f"• **Discord API:** {self.bot.latency*1000:.2f}ms\n"
            f"• **Subscription:** `{license_status}`\n"
            f"• **Active Raids:** {active_raids_count['count']}"
        )

    async def _create_status_embed(self, guild_id: int) -> discord.Embed:
        return await self._create_status_basic_embed(guild_id)
    async def _create_status_env_embed(self) -> discord.Embed:
        bot_user = getattr(self.bot, "user", None)
        bot_user_id = getattr(bot_user, "id", None)

        db_file = getattr(getattr(self.bot, "db", None), "db_file", None)
        resolved_db = None
        if db_file:
            try:
                resolved_db = str(Path(str(db_file)).expanduser().resolve())
            except Exception:
                resolved_db = str(db_file)

        railway_env = os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("RAILWAY_ENVIRONMENT")
        railway_service = os.getenv("RAILWAY_SERVICE_NAME")

        env_lines: list[str] = []
        if bot_user_id:
            env_lines.append(f"• **Bot User ID:** `{bot_user_id}`")
        if db_file:
            env_lines.append(f"• **DB File:** `{db_file}`")
        if resolved_db and resolved_db != str(db_file):
            env_lines.append(f"• **DB File (resolved):** `{resolved_db}`")
        if railway_env:
            env_lines.append(f"• **Railway Env:** `{railway_env}`")
        if railway_service:
            env_lines.append(f"• **Railway Service:** `{railway_service}`")

        return create_info_embed("Bot Status (Admin)", "\n".join(env_lines))

    @app_commands.command(name="status", description="Check the bot's operational status.")
    async def status_cmd(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        ephemeral_basic = True
        try:
            channel = getattr(interaction, "channel", None)
            me = interaction.guild.get_member(getattr(self.bot.user, "id", 0)) if self.bot.user else None
            if channel is not None and me is not None and hasattr(channel, "permissions_for"):
                perms = channel.permissions_for(me)
                if isinstance(channel, discord.Thread):
                    ephemeral_basic = not bool(getattr(perms, "send_messages_in_threads", False))
                else:
                    ephemeral_basic = not bool(getattr(perms, "send_messages", False))
        except Exception:
            ephemeral_basic = True

        await interaction.response.defer(ephemeral=True)

        basic_embed = await self._create_status_embed(interaction.guild.id)
        await interaction.followup.send(embed=basic_embed, ephemeral=ephemeral_basic)

        if await is_admin(interaction):
            env_embed = await self._create_status_env_embed()
            await interaction.followup.send(embed=env_embed, ephemeral=True)

    @app_commands.command(name="history", description="Downloads a CSV of the last 30 days of DKP transactions.")
    @app_commands.check(is_admin)
    async def history_cmd(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        now = datetime.utcnow().timestamp()
        guild_id = interaction.guild.id
        last = self._history_cooldowns.get(guild_id, 0)
        if now - last < 60:
            remaining = int(60 - (now - last))
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"This command can only be used once every 60 seconds per server. Please try again in {remaining} seconds.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"This command can only be used once every 60 seconds per server. Please try again in {remaining} seconds.",
                    ephemeral=True,
                )
            return

        self._history_cooldowns[guild_id] = now

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

    @app_commands.command(name="raid_points", description="Show DKP for all members in the current raid.")
    @app_commands.describe(member="(Optional) Show DKP for a single member in this raid.")
    @app_commands.describe(public="Post the results publicly in this channel.")
    @app_commands.describe(sort="Sort order for the list (dkp or name).")
    async def raid_points_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        public: bool = False,
        sort: Literal["dkp", "name"] = "dkp",
    ):
        if interaction.guild is None:
            if not interaction.response.is_done():
                await interaction.response.send_message("This command can only be used inside a server.", ephemeral=True)
            else:
                await interaction.followup.send("This command can only be used inside a server.", ephemeral=True)
            return

        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog or not hasattr(raid_cog, "show_raid_points"):
            ephemeral = not public
            if not interaction.response.is_done():
                await interaction.response.send_message("Raid module is currently offline.", ephemeral=ephemeral)
            else:
                await interaction.followup.send("Raid module is currently offline.", ephemeral=ephemeral)
            return

        if member is not None:
            ephemeral = not public
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Member-specific raid points are now shown via the raid panel. Use the Raid Points button.",
                    ephemeral=ephemeral,
                )
            else:
                await interaction.followup.send(
                    "Member-specific raid points are now shown via the raid panel. Use the Raid Points button.",
                    ephemeral=ephemeral,
                )
            return

        # Default: show raid-scoped points via shared implementation.
        await raid_cog.show_raid_points(
            interaction,
            scope="raid",
            sort=str(sort),
        )

    @app_commands.command(name="raid_status", description="Show status of the current raid and any active auction.")
    @app_commands.check(is_admin)
    async def raid_status_cmd(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send(
                "This channel is not associated with an active raid.",
                ephemeral=True,
            )

        auction = await self.bot.db.get_active_auction(raid["id"])
        auction_summary = "No active auction for this raid."
        if auction:
            stats = await self.bot.db.fetchone(
                "SELECT COUNT(*) AS bid_count, MAX(amount) AS max_bid FROM auction_bids WHERE auction_id = ?",
                (auction["id"],),
            )
            bid_count = stats["bid_count"] if stats and "bid_count" in stats.keys() else 0
            max_bid = stats["max_bid"] if stats and "max_bid" in stats.keys() and stats["max_bid"] is not None else 0
            auction_summary = (
                f"Auction ID: `{auction['id']}`\n"
                f"Item: **{auction['item_name']}**\n"
                f"Bids: `{bid_count}`\n"
                f"Highest Bid: `{max_bid}`"
            )

        desc = (
            f"**Raid ID:** `{raid['id']}`\n"
            f"**Guild ID:** `{raid['guild_id']}`\n"
            f"**Leader ID:** `{raid['leader_id']}`\n"
            f"**Voice Channel ID:** `{raid['vc_id']}`\n"
            f"**Thread ID:** `{raid['thread_id']}`\n"
            f"**Created At:** `{raid['created_at']}`\n\n"
            f"{auction_summary}"
        )
        embed = create_info_embed("Raid Status", desc)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="server_points", description="Show DKP for all members in this server.")
    @app_commands.describe(member="(Optional) Show DKP for a single member in this server.")
    async def server_points_cmd(self, interaction: discord.Interaction, member: discord.Member | None = None):
        # Ensure this command is used in a guild context
        if not interaction.guild:
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

        await interaction.response.defer()

        # If a specific member is requested, just show their DKP
        if member is not None:
            if member.bot:
                return await interaction.followup.send("Bots do not have DKP.")

            dkp = await self.bot.db.get_user_dkp(member.id, interaction.guild.id, username=member.display_name)
            description = f"{member.mention}  **{dkp} DKP**"
            embed = create_info_embed("Server DKP (Member)", description)
            return await interaction.followup.send(embed=embed)

        # Otherwise, show DKP for all users with entries in this guild
        rows = await self.bot.db.fetchall(
            "SELECT user_id, dkp, username FROM users WHERE guild_id = ? ORDER BY dkp DESC",
            (interaction.guild.id,)
        )

        if not rows:
            return await interaction.followup.send("No DKP data found for this server.")

        lines = []
        backfill = []
        for row in rows:
            member = interaction.guild.get_member(row["user_id"])
            if member:
                display = f"@{member.display_name}"
                if row["username"] != member.display_name:
                    backfill.append((member.display_name, row["user_id"], interaction.guild.id))
            elif row["username"]:
                display = f"@{row['username']}"
            else:
                display = f"Unknown User ({row['user_id']})"
            lines.append(f"{display}  **{row['dkp']} DKP**")

        if backfill:
            async def _do_backfill(rows):
                for uname, uid, gid in rows:
                    await self.bot.db.execute(
                        "UPDATE users SET username = ? WHERE user_id = ? AND guild_id = ? AND (username IS NULL OR username != ?)",
                        (uname, uid, gid, uname),
                    )
            asyncio.create_task(_do_backfill(backfill))

        description = "\n".join(lines)
        embed = create_info_embed("Server DKP", description)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="admin_adjust_dkp", description="Manually adjust a member's DKP (admin only).")
    @app_commands.check(is_admin)
    @app_commands.describe(member="The member whose DKP will be adjusted.")
    async def admin_adjust_dkp_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        modal = AdminDKPAdjustModal(self, member)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="list_members", description="List members who participated in this raid log thread.")
    @app_commands.check(is_admin)
    async def list_members(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        # This command is intended to be used inside a raid log thread under
        # the Active Raids channel. It lists unique, non-bot users who have
        # ever joined the raid's voice channel, for both active and closed raids.

        # Ensure we are in a thread channel
        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            return await interaction.response.send_message(
                "This command can only be used inside a raid log thread.",
                ephemeral=True,
            )

        # Verify this thread is associated with a raid (active or closed)
        raid = await self.bot.db.fetchone(
            "SELECT * FROM raids WHERE thread_id = ?",
            (thread.id,),
        )
        if not raid:
            return await interaction.response.send_message(
                "This thread is not associated with a raid log.",
                ephemeral=True,
            )

        # Fetch all members who have ever joined the associated raid voice channel.
        member_rows = await self.bot.db.get_raid_members(raid["id"])
        if not member_rows:
            return await interaction.response.send_message(
                "No raid members were found for this raid voice channel.",
                ephemeral=True,
            )

        # Build a sorted list of members by display name. If a user has left the
        # guild, fall back to an "Unknown User" label so the historical record is
        # still visible.
        entries: list[tuple[str, str, str]] = []
        for row in member_rows:
            user_id = row["user_id"]
            member = interaction.guild.get_member(user_id)

            if member is not None:
                display_name = getattr(member, "display_name", getattr(member, "name", str(user_id)))
                mention = getattr(member, "mention", display_name)
            else:
                display_name = f"Unknown User ({user_id})"
                mention = display_name

            entries.append((display_name.lower(), mention, display_name))

        if not entries:
            return await interaction.response.send_message(
                "No raid members were found for this raid voice channel.",
                ephemeral=True,
            )

        entries.sort(key=lambda e: e[0])
        lines = [f"- {mention} ({display_name})" for _, mention, display_name in entries]
        description = "\n".join(lines)

        embed = create_info_embed("Raid Members", description)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="debug_config", description="Show DKP configuration for this server.")
    @app_commands.check(is_admin)
    async def debug_config(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
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
        default_award = config.get('default_dkp_award', 10) or 10
        default_interval = config.get('default_dkp_interval', 1) or 1
        guild_bank_category_id = config.get('guild_bank_category_id')
        guild_bank_ch_id = config.get('guild_bank_channel_id')
        guild_bank_inventory_ch_id = config.get('guild_bank_inventory_channel_id')
        guild_bank_transactions_ch_id = config.get('guild_bank_transactions_channel_id')
        description = (
            f"**Guild ID:** `{config['guild_id']}`\n"
            f"**License Status:** `{config['license_status']}`\n"
            f"**DKP Category:** {fmt_channel(config['dkp_category_id'])}\n"
            f"**DKP Channel:** {fmt_channel(config['dkp_channel_id'])}\n"
            f"**Raid Channel:** {fmt_channel(config['raid_channel_id'])}\n"
            f"**Guild Bank Category:** {fmt_channel(guild_bank_category_id)}\n"
            f"**Guild Bank Channel:** {fmt_channel(guild_bank_ch_id)}\n"
            f"**Guild Bank Inventory Channel:** {fmt_channel(guild_bank_inventory_ch_id)}\n"
            f"**Guild Bank Transactions Channel:** {fmt_channel(guild_bank_transactions_ch_id)}\n"
            f"**Bot Admin Role:** {fmt_role(config['admin_role_id'])}\n"
            f"**Officer Role:** {fmt_role(config['officer_role_id'])}\n"
            f"**Raider Role:** {fmt_role(config['raider_role_id'])}\n"
            f"**Raid Leader Role:** {fmt_role(config['raid_leader_role_id'])}\n"
            f"**Raid VC Template:** {fmt_channel(config['raid_vc_template_id'])}\n"
            f"**Default Timed DKP:** `{default_award}` per `{default_interval}` minute(s)\n"
            f"**Generated At:** <t:{ts}:F>"
        )

        embed = create_info_embed("Guild Configuration Debug", description)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="raid_member_list_order",
        description="Configure the default ordering for raid member lists (dropdowns/team list).",
    )
    @app_commands.check(is_admin)
    @app_commands.describe(order="name = alphabetical, random = shuffled")
    async def raid_member_list_order_cmd(
        self,
        interaction: discord.Interaction,
        order: Literal["name", "random"] = "name",
    ):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)",
                (int(interaction.guild.id),),
            )
        except Exception:
            pass

        await self.bot.db.execute(
            "UPDATE guilds SET raid_member_list_order = ? WHERE guild_id = ?",
            (str(order), int(interaction.guild.id)),
        )

        await interaction.followup.send(f"Raid member list order set to `{order}`.", ephemeral=True)

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
        default_award = config.get('default_dkp_award', 10) or 10
        default_interval = config.get('default_dkp_interval', 1) or 1
        description = (
            f"**Guild ID:** `{config['guild_id']}`\n"
            f"**License Status:** `{config['license_status']}`\n"
            f"**DKP Category:** {fmt_channel(config['dkp_category_id'])}\n"
            f"**DKP Channel:** {fmt_channel(config['dkp_channel_id'])}\n"
            f"**Raid Channel:** {fmt_channel(config['raid_channel_id'])}\n"
            f"**Bot Admin Role:** {fmt_role(config['admin_role_id'])}\n"
            f"**Officer Role:** {fmt_role(config['officer_role_id'])}\n"
            f"**Raider Role:** {fmt_role(config['raider_role_id'])}\n"
            f"**Raid Leader Role:** {fmt_role(config['raid_leader_role_id'])}\n"
            f"**Raid VC Template:** {fmt_channel(config['raid_vc_template_id'])}\n"
            f"**Default Timed DKP:** `{default_award}` per `{default_interval}` minute(s)\n"
            f"**Generated At:** <t:{ts}:F>"
        )

        embed = create_info_embed("Guild Configuration Debug", description)
        await ctx.reply(embed=embed)

    async def set_role(self, interaction: discord.Interaction, role_type: str, role: discord.Role):
        # Validate role_type to prevent SQL injection
        valid_columns = {"admin", "officer", "raider", "raid_leader"}
        if role_type.lower() not in valid_columns:
            await interaction.followup.send("Invalid role type.", ephemeral=True)
            return
        column = f"{role_type.lower()}_role_id"
        await self.bot.db.execute(
            f"UPDATE guilds SET {column} = ? WHERE guild_id = ?",  # nosec B608
            (role.id, interaction.guild.id)
        )

    @app_commands.command(
        name="backfill_raid_dkp",
        description="Backfill missing timed DKP awards into raid_dkp_transactions for the current raid.",
    )
    @app_commands.check(is_admin)
    async def backfill_raid_dkp_cmd(self, interaction: discord.Interaction):
        """One-time fix: backfill timed raid awards that were recorded in transactions but not raid_dkp_transactions."""
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        raid_id = int(raid["id"])
        guild_id = int(raid["guild_id"])

        # Get raid start time
        raid_started_at = None
        try:
            raw = raid.get("started_at") or raid.get("created_at")
            if raw:
                from datetime import datetime
                raid_started_at = datetime.fromisoformat(str(raw))
        except Exception:
            pass

        # Find timed award transactions for this guild that match the pattern
        # and occurred after the raid started
        query = """
            SELECT user_id, change, reason, timestamp
            FROM transactions
            WHERE guild_id = ?
              AND reason LIKE 'Timed raid award%'
        """
        params = [guild_id]
        if raid_started_at:
            query += " AND timestamp >= ?"
            params.append(raid_started_at.isoformat())

        try:
            rows = await self.bot.db.fetchall(query, tuple(params))
        except Exception as e:
            return await interaction.followup.send(f"Failed to query transactions: {e}", ephemeral=True)

        if not rows:
            return await interaction.followup.send("No timed raid award transactions found to backfill.", ephemeral=True)

        # Get existing raid_dkp_transactions to avoid duplicates
        existing = set()
        try:
            existing_rows = await self.bot.db.fetchall(
                "SELECT user_id, change, reason FROM raid_dkp_transactions WHERE raid_id = ?",
                (raid_id,),
            )
            for er in list(existing_rows or []):
                existing.add((int(er["user_id"]), int(er["change"]), str(er["reason"])))
        except Exception:
            pass

        inserted = 0
        for row in list(rows or []):
            try:
                user_id = int(row["user_id"])
                change = int(row["change"])
                reason = str(row["reason"])
            except Exception:
                continue

            # Skip if already exists
            if (user_id, change, reason) in existing:
                continue

            try:
                await self.bot.db.record_raid_dkp_transaction(
                    raid_id,
                    guild_id,
                    user_id,
                    change,
                    reason,
                    actor_id=None,
                )
                inserted += 1
                existing.add((user_id, change, reason))
            except Exception:
                continue

        await interaction.followup.send(
            f"Backfilled **{inserted}** timed DKP award(s) into raid_dkp_transactions for this raid.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
