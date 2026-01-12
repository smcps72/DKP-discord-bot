import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timedelta
import logging
import os
from ..utils import create_error_embed, create_info_embed

class TasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if self.bot.license_check_enabled:
            self.license_check.start()
        self.cleanup_channels.start()
        self.hourly_dkp_award.start()

    def cog_unload(self):
        self.license_check.cancel()
        self.cleanup_channels.cancel()
        self.hourly_dkp_award.cancel()

    @tasks.loop(hours=24)
    async def license_check(self):
        logging.info("Running daily license check...")
        license_key = self.bot.license_key
        if not license_key:
            logging.warning("No license key found in environment. Skipping check.")
            return
        try:
            async with self.bot.http_session.post(
                f"{self.bot.license_server_url}/check_license",
                json={"license_key": license_key}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get("status")
                    logging.info(f"License check result: {status}")
                    # This would check across all guilds the bot is in
                    # For this single-guild example, we do it directly
                    guild_id = next((g.id for g in self.bot.guilds), None)
                    if not guild_id: return
                    config = await self.bot.db.get_guild_config(guild_id)
                    if not config: return
                    await self.bot.db.execute("UPDATE guilds SET license_status = ? WHERE guild_id = ?", (status, guild_id))
                    if status == "lapsed" and not config['warning_sent']:
                        dkp_channel = self.bot.get_channel(config['dkp_channel_id'])
                        if dkp_channel:
                            embed = create_error_embed(
                                "Subscription Payment Lapsed",
                                "Your guild's subscription for the DKP Bot has lapsed. The bot will be disabled in 24 hours if the issue is not resolved. Please contact the guild leader."
                            )
                            await dkp_channel.send(embed=embed)
                            await self.bot.db.execute("UPDATE guilds SET warning_sent = 1 WHERE guild_id = ?", (guild_id,))
                    elif status == "active" and config['warning_sent']:
                        await self.bot.db.execute("UPDATE guilds SET warning_sent = 0 WHERE guild_id = ?", (guild_id,))
                else:
                    logging.error(f"Failed to check license. Status: {resp.status}")
        except Exception as e:
            logging.exception(f"Error connecting to licensing server at {self.bot.license_server_url}: {e}")

    @license_check.before_loop
    async def before_license_check(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def cleanup_channels(self):
        logging.info("Running cleanup task for empty raid VCs.")
        raids = await self.bot.db.fetchall("SELECT vc_id FROM raids WHERE is_active = 1")
        for raid in raids:
            vc_id = None
            try:
                vc_id = raid["vc_id"]
            except Exception:
                vc_id = None

            if not vc_id:
                continue

            channel = self.bot.get_channel(vc_id)
            # vc_id is often the raid leader's *existing* voice channel (e.g. General),
            # so it must never be auto-deleted. Instead, when a VC is gone or empty,
            # we simply stop associating the raid with that channel.
            try:
                if channel is None:
                    await self.bot.db.execute("UPDATE raids SET vc_id = NULL WHERE vc_id = ? AND is_active = 1", (vc_id,))
                elif isinstance(channel, discord.VoiceChannel) and not channel.members:
                    await self.bot.db.execute("UPDATE raids SET vc_id = NULL WHERE vc_id = ? AND is_active = 1", (vc_id,))
            except Exception:
                logging.exception("Failed to clear stale raid vc_id during cleanup")

    @cleanup_channels.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def hourly_dkp_award(self):
        amount = 5
        for guild in list(getattr(self.bot, "guilds", []) or []):
            try:
                rows = await self.bot.db.fetchall(
                    """
                    SELECT rm.user_id
                    FROM raid_members rm
                    JOIN raids r ON r.id = rm.raid_id
                    WHERE r.guild_id = ? AND r.is_active = 1
                    """,
                    (int(guild.id),),
                )
            except Exception:
                logging.exception("Failed to load active raid members for guild_id=%s", getattr(guild, "id", None))
                continue

            user_ids: set[int] = set()
            for row in list(rows or []):
                try:
                    user_id = int(row["user_id"])
                except Exception:
                    try:
                        user_id = int(row.get("user_id"))
                    except Exception:
                        continue
                user_ids.add(user_id)

            if not user_ids:
                continue

            for user_id in user_ids:
                member = guild.get_member(int(user_id))
                if member is None or getattr(member, "bot", False):
                    continue
                try:
                    await self.bot.db.modify_user_dkp(
                        int(member.id),
                        int(guild.id),
                        int(amount),
                        "Hourly award",
                    )
                except Exception:
                    logging.exception("Failed to apply hourly DKP award for user_id=%s guild_id=%s", getattr(member, "id", None), getattr(guild, "id", None))

    @hourly_dkp_award.before_loop
    async def before_hourly_dkp_award(self):
        await self.bot.wait_until_ready()
        now = datetime.utcnow()
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        delay = (next_hour - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

async def setup(bot: commands.Bot):
    await bot.add_cog(TasksCog(bot))
