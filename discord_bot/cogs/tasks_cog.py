import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timedelta
import logging
import os
from ..utils import create_error_embed, create_info_embed

LEADER_ABSENCE_THRESHOLD_MINUTES = 10
MEMBER_ABSENCE_THRESHOLD_MINUTES = 5

class TasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if self.bot.license_check_enabled:
            self.license_check.start()
        self.cleanup_channels.start()
        self.raid_timed_awards.start()
        self.enforce_raid_voice_absences.start()

    def cog_unload(self):
        self.license_check.cancel()
        self.cleanup_channels.cancel()
        self.raid_timed_awards.cancel()
        self.enforce_raid_voice_absences.cancel()

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
        raids = await self.bot.db.fetchall("SELECT id, vc_id FROM raids WHERE is_active = 1")
        for raid in list(raids or []):
            raid_id = None
            primary_vc_id = None
            try:
                raid_id = int(raid["id"])
            except Exception:
                raid_id = None
            try:
                primary_vc_id = raid["vc_id"]
            except Exception:
                primary_vc_id = None

            # Backward compatibility for tests/mocks (or older code paths)
            # that only provide vc_id.
            if raid_id is None:
                if not primary_vc_id:
                    continue

                channel = self.bot.get_channel(int(primary_vc_id))
                # vc_id is often the raid leader's *existing* voice channel (e.g. General),
                # so it must never be auto-deleted. Instead, when a VC is gone or empty,
                # we simply stop associating the raid with that channel.
                try:
                    if channel is None:
                        await self.bot.db.execute(
                            "UPDATE raids SET vc_id = NULL WHERE vc_id = ? AND is_active = 1",
                            (int(primary_vc_id),),
                        )
                    elif isinstance(channel, discord.VoiceChannel) and not channel.members:
                        await self.bot.db.execute(
                            "UPDATE raids SET vc_id = NULL WHERE vc_id = ? AND is_active = 1",
                            (int(primary_vc_id),),
                        )
                except Exception:
                    logging.exception("Failed to clear stale raid vc_id during cleanup")
                continue

            vc_ids: set[int] = set()
            if primary_vc_id:
                try:
                    vc_ids.add(int(primary_vc_id))
                except Exception:
                    pass

            try:
                linked_rows = await self.bot.db.get_raid_voice_channels(raid_id)
            except Exception:
                linked_rows = []
            for row in list(linked_rows or []):
                try:
                    vc_ids.add(int(row["vc_id"]))
                except Exception:
                    continue

            for vc_id in list(vc_ids):
                channel = self.bot.get_channel(int(vc_id))

                # vc_id is often the raid leader's *existing* voice channel (e.g. General),
                # so it must never be auto-deleted. Instead, when a VC is gone or empty,
                # we simply stop associating the raid with that channel.
                try:
                    if channel is None:
                        try:
                            await self.bot.db.remove_raid_voice_channel(raid_id, int(vc_id))
                        except Exception:
                            pass
                        if primary_vc_id and int(primary_vc_id) == int(vc_id):
                            await self.bot.db.execute(
                                "UPDATE raids SET vc_id = NULL WHERE id = ? AND is_active = 1",
                                (raid_id,),
                            )
                    elif (
                        primary_vc_id
                        and int(primary_vc_id) == int(vc_id)
                        and isinstance(channel, discord.VoiceChannel)
                        and not channel.members
                    ):
                        await self.bot.db.execute(
                            "UPDATE raids SET vc_id = NULL WHERE id = ? AND is_active = 1",
                            (raid_id,),
                        )
                except Exception:
                    logging.exception("Failed to clear stale raid vc_id during cleanup")

    @cleanup_channels.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def raid_timed_awards(self):
        now = datetime.utcnow()
        try:
            rows = await self.bot.db.fetchall(
                """
                SELECT r.id AS raid_id, r.guild_id, r.thread_id, r.leader_id,
                       ta.amount, ta.interval_minutes, ta.last_awarded_at
                FROM raids r
                JOIN raid_timed_awards ta ON ta.raid_id = r.id
                WHERE r.is_active = 1 AND ta.is_enabled = 1
                """,
            )
        except Exception:
            return

        for row in list(rows or []):
            try:
                raid_id = int(row["raid_id"])
                guild_id = int(row["guild_id"])
                thread_id = int(row["thread_id"])
                amount = int(row["amount"])
                interval_minutes = int(row["interval_minutes"])
                leader_id = int(row["leader_id"])
            except Exception:
                continue

            if amount <= 0:
                continue
            if interval_minutes <= 0:
                continue

            last_awarded_at = None
            try:
                raw = row["last_awarded_at"]
                if raw:
                    last_awarded_at = datetime.fromisoformat(str(raw))
            except Exception:
                last_awarded_at = None

            if last_awarded_at is None:
                try:
                    await self.bot.db.execute(
                        "UPDATE raid_timed_awards SET last_awarded_at = CURRENT_TIMESTAMP WHERE raid_id = ?",
                        (raid_id,),
                    )
                except Exception:
                    pass
                continue

            if (now - last_awarded_at) < timedelta(minutes=interval_minutes):
                continue

            # Run update_team logic before awarding DKP - sync members from voice channels
            try:
                guild = self.bot.get_guild(guild_id)
                vc_ids: set[int] = set()
                primary_vc = row.get("vc_id") if isinstance(row, dict) else None
                if primary_vc:
                    try:
                        vc_ids.add(int(primary_vc))
                    except Exception:
                        pass
                try:
                    linked_rows = await self.bot.db.get_raid_voice_channels(raid_id)
                except Exception:
                    linked_rows = []
                for lr in list(linked_rows or []):
                    try:
                        vc_ids.add(int(lr["vc_id"]))
                    except Exception:
                        continue

                # Add members from voice channels to raid
                for vc_id in list(vc_ids):
                    ch = guild.get_channel(int(vc_id))
                    if not isinstance(ch, discord.VoiceChannel):
                        continue
                    for m in list(getattr(ch, "members", []) or []):
                        if getattr(m, "bot", False):
                            continue
                        try:
                            if await self.bot.db.is_raid_member_excluded(raid_id, int(m.id)):
                                continue
                        except Exception:
                            pass
                        try:
                            await self.bot.db.add_raid_member(raid_id, int(m.id))
                        except Exception:
                            pass
            except Exception:
                logging.exception("Failed to update team before timed award for raid_id=%s", raid_id)

            try:
                member_rows = await self.bot.db.get_raid_members(raid_id)
            except Exception:
                member_rows = []

            group_zero_ids: set[int] = set()
            try:
                group_rows = await self.bot.db.get_raid_member_groups(int(raid_id))
            except Exception:
                group_rows = []
            for gr in list(group_rows or []):
                try:
                    uid = int(gr["user_id"])
                    grp = int(gr["group_number"])
                except Exception:
                    continue
                if grp == 0:
                    group_zero_ids.add(uid)

            user_ids: set[int] = set()
            for mr in list(member_rows or []):
                try:
                    uid = int(mr["user_id"])
                except Exception:
                    continue
                if uid in group_zero_ids:
                    continue
                if uid == leader_id:
                    user_ids.add(uid)
                else:
                    user_ids.add(uid)

            if not user_ids:
                try:
                    await self.bot.db.execute(
                        "UPDATE raid_timed_awards SET last_awarded_at = CURRENT_TIMESTAMP WHERE raid_id = ?",
                        (raid_id,),
                    )
                except Exception:
                    pass
                continue

            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue

            awarded = 0
            for uid in list(user_ids):
                member = guild.get_member(int(uid))
                if member is None or getattr(member, "bot", False):
                    continue
                try:
                    if await self.bot.db.is_raid_member_excluded(raid_id, int(uid)):
                        continue
                except Exception:
                    pass
                try:
                    await self.bot.db.modify_user_dkp(
                        int(uid),
                        int(guild_id),
                        int(amount),
                        f"Timed raid award (+{amount} every {interval_minutes}m)",
                        username=member.display_name,
                    )
                    await self.bot.db.record_raid_dkp_transaction(
                        int(raid_id),
                        int(guild_id),
                        int(uid),
                        int(amount),
                        f"Timed raid award (+{amount} every {interval_minutes}m)",
                        actor_id=None,
                    )
                    awarded += 1
                except Exception:
                    logging.exception("Failed timed raid award for user_id=%s raid_id=%s", uid, raid_id)

            try:
                await self.bot.db.execute(
                    "UPDATE raid_timed_awards SET last_awarded_at = CURRENT_TIMESTAMP WHERE raid_id = ?",
                    (raid_id,),
                )
            except Exception:
                pass

            try:
                thread = None
                try:
                    thread = guild.get_thread(thread_id)
                except Exception:
                    thread = None
                if thread is None:
                    try:
                        resolved = self.bot.get_channel(thread_id)
                        if isinstance(resolved, discord.Thread):
                            thread = resolved
                    except Exception:
                        thread = None
                if thread is not None:
                    await thread.send(
                        f"Timed award: **+{amount} DKP** to **{awarded}** raid member(s) (every {interval_minutes} minutes)."
                    )
            except Exception:
                logging.exception("Failed to announce timed raid award for raid_id=%s", raid_id)

    @raid_timed_awards.before_loop
    async def before_raid_timed_awards(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def enforce_raid_voice_absences(self):
        now = datetime.utcnow()
        try:
            raids = await self.bot.db.fetchall(
                "SELECT id, guild_id, leader_id, thread_id, vc_id, announcement_message_id FROM raids WHERE is_active = 1",
            )
        except Exception:
            return

        for raid in list(raids or []):
            try:
                raid_id = int(raid["id"])
                guild_id = int(raid["guild_id"])
                leader_id = int(raid["leader_id"])
                thread_id = int(raid["thread_id"])
            except Exception:
                continue

            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue

            vc_ids: set[int] = set()
            try:
                primary = raid["vc_id"]
                if primary:
                    vc_ids.add(int(primary))
            except Exception:
                pass
            try:
                linked = await self.bot.db.get_raid_voice_channels(raid_id)
            except Exception:
                linked = []
            for row in list(linked or []):
                try:
                    vc_ids.add(int(row["vc_id"]))
                except Exception:
                    continue

            if not vc_ids:
                try:
                    await self.bot.db.execute(
                        "DELETE FROM raid_voice_absences WHERE raid_id = ?",
                        (raid_id,),
                    )
                except Exception:
                    pass
                try:
                    await self.bot.db.execute(
                        "DELETE FROM raid_leader_absences WHERE raid_id = ?",
                        (raid_id,),
                    )
                except Exception:
                    pass
                continue

            voice_ids: set[int] = set()
            has_valid_voice_channel = False
            for vc_id in list(vc_ids):
                ch = guild.get_channel(int(vc_id))
                if not isinstance(ch, discord.VoiceChannel):
                    continue
                has_valid_voice_channel = True
                for m in list(getattr(ch, "members", []) or []):
                    if getattr(m, "bot", False):
                        continue
                    voice_ids.add(int(m.id))

            if not has_valid_voice_channel:
                try:
                    await self.bot.db.execute(
                        "DELETE FROM raid_voice_absences WHERE raid_id = ?",
                        (raid_id,),
                    )
                except Exception:
                    pass
                try:
                    await self.bot.db.execute(
                        "DELETE FROM raid_leader_absences WHERE raid_id = ?",
                        (raid_id,),
                    )
                except Exception:
                    pass
                continue

            # --- Raid Leader Absence Check (10-minute auto-close) ---
            leader_in_voice = leader_id in voice_ids
            if leader_in_voice:
                # Leader is in voice - clear any absence record
                try:
                    await self.bot.db.execute(
                        "DELETE FROM raid_leader_absences WHERE raid_id = ?",
                        (raid_id,),
                    )
                except Exception:
                    pass
            else:
                # Leader is NOT in any linked voice channel - track absence
                try:
                    await self.bot.db.execute(
                        "INSERT OR IGNORE INTO raid_leader_absences (raid_id) VALUES (?)",
                        (raid_id,),
                    )
                except Exception:
                    pass

                # Check how long the leader has been absent
                leader_absent_since = None
                try:
                    row = await self.bot.db.fetchone(
                        "SELECT absent_since FROM raid_leader_absences WHERE raid_id = ?",
                        (raid_id,),
                    )
                    if row and row["absent_since"]:
                        leader_absent_since = datetime.fromisoformat(str(row["absent_since"]))
                except Exception:
                    leader_absent_since = None

                if leader_absent_since is not None and (now - leader_absent_since) >= timedelta(minutes=LEADER_ABSENCE_THRESHOLD_MINUTES):
                    # Auto-close the raid due to leader absence
                    try:
                        thread = None
                        try:
                            thread = guild.get_thread(thread_id)
                        except Exception:
                            thread = None
                        if thread is None:
                            try:
                                resolved = self.bot.get_channel(thread_id)
                                if isinstance(resolved, discord.Thread):
                                    thread = resolved
                            except Exception:
                                thread = None

                        if thread is not None:
                            await thread.send(
                                f"**Raid auto-closed:** The raid leader <@{leader_id}> has been out of the raid voice channel(s) for more than {LEADER_ABSENCE_THRESHOLD_MINUTES} minutes."
                            )

                        # Close the raid
                        await self._auto_close_raid(guild, raid, thread, reason="leader_absence")
                        logging.info(
                            "Auto-closed raid_id=%s due to leader absence (leader_id=%s)",
                            raid_id,
                            leader_id,
                        )
                    except Exception:
                        logging.exception(
                            "Failed to auto-close raid_id=%s due to leader absence",
                            raid_id,
                        )
                    continue  # Skip member absence checks for this raid since it's now closed

            try:
                member_rows = await self.bot.db.get_raid_members(raid_id)
            except Exception:
                member_rows = []

            raid_member_ids: set[int] = set()
            for mr in list(member_rows or []):
                try:
                    raid_member_ids.add(int(mr["user_id"]))
                except Exception:
                    continue

            # Members in group 0 ("Not in Raid") are watchers — skip
            # them from voice-absence tracking entirely.
            group_zero_ids: set[int] = set()
            try:
                group_rows = await self.bot.db.get_raid_member_groups(raid_id)
            except Exception:
                group_rows = []
            for gr in list(group_rows or []):
                try:
                    _uid = int(gr["user_id"])
                    _grp = int(gr["group_number"])
                except Exception:
                    continue
                if _grp == 0:
                    group_zero_ids.add(_uid)

            for uid in list(raid_member_ids):
                if uid in group_zero_ids:
                    continue
                try:
                    if await self.bot.db.is_raid_member_excluded(raid_id, int(uid)):
                        continue
                except Exception:
                    pass

                if uid in voice_ids:
                    try:
                        await self.bot.db.execute(
                            "DELETE FROM raid_voice_absences WHERE raid_id = ? AND user_id = ?",
                            (raid_id, int(uid)),
                        )
                    except Exception:
                        pass
                    continue

                try:
                    await self.bot.db.execute(
                        "INSERT OR IGNORE INTO raid_voice_absences (raid_id, user_id) VALUES (?, ?)",
                        (raid_id, int(uid)),
                    )
                except Exception:
                    pass

                absent_since = None
                try:
                    row = await self.bot.db.fetchone(
                        "SELECT absent_since FROM raid_voice_absences WHERE raid_id = ? AND user_id = ?",
                        (raid_id, int(uid)),
                    )
                    if row and row["absent_since"]:
                        absent_since = datetime.fromisoformat(str(row["absent_since"]))
                except Exception:
                    absent_since = None

                if absent_since is None:
                    continue
                if (now - absent_since) < timedelta(minutes=MEMBER_ABSENCE_THRESHOLD_MINUTES):
                    continue

                removed = False
                try:
                    removed = await self.bot.db.remove_raid_member(raid_id, int(uid))
                except Exception:
                    removed = False

                try:
                    await self.bot.db.add_raid_member_exclusion(raid_id, int(uid), reason="inactivity")
                except Exception:
                    pass
                try:
                    await self.bot.db.delete_raid_join_request(raid_id, int(uid))
                except Exception:
                    pass
                try:
                    await self.bot.db.execute(
                        "DELETE FROM raid_member_groups WHERE raid_id = ? AND user_id = ?",
                        (raid_id, int(uid)),
                    )
                except Exception:
                    pass
                try:
                    await self.bot.db.execute(
                        "DELETE FROM raid_voice_absences WHERE raid_id = ? AND user_id = ?",
                        (raid_id, int(uid)),
                    )
                except Exception:
                    pass

                if not removed:
                    continue

                try:
                    thread = None
                    try:
                        thread = guild.get_thread(thread_id)
                    except Exception:
                        thread = None
                    if thread is None:
                        try:
                            resolved = self.bot.get_channel(thread_id)
                            if isinstance(resolved, discord.Thread):
                                thread = resolved
                        except Exception:
                            thread = None
                    if thread is not None:
                        mention = f"<@{uid}>"
                        try:
                            member = guild.get_member(int(uid))
                            if member is not None:
                                mention = member.mention
                        except Exception:
                            pass
                        await thread.send(
                            f"{mention} was removed from the raid for being out of voice for more than {MEMBER_ABSENCE_THRESHOLD_MINUTES} minutes. They must rejoin the raid to participate again."
                        )
                except Exception:
                    logging.exception("Failed to announce voice absence removal for raid_id=%s user_id=%s", raid_id, uid)

    @enforce_raid_voice_absences.before_loop
    async def before_enforce_raid_voice_absences(self):
        await self.bot.wait_until_ready()

    async def _auto_close_raid(
        self,
        guild: discord.Guild,
        raid: dict,
        thread: discord.Thread | None,
        *,
        reason: str = "auto",
    ):
        """Auto-close a raid from a background task (no interaction context)."""
        try:
            raid_id = int(raid["id"])
            leader_id = int(raid["leader_id"])
        except Exception:
            return

        # Deactivate raid in DB
        try:
            await self.bot.db.execute(
                "UPDATE raids SET is_active = 0 WHERE id = ?",
                (raid_id,),
            )
        except Exception:
            logging.exception("Failed to deactivate raid_id=%s during auto-close", raid_id)

        # Disable timed DKP
        try:
            await self.bot.db.set_raid_timed_award_enabled(raid_id, False)
        except Exception:
            logging.exception("Failed to disable timed DKP during auto-close for raid_id=%s", raid_id)

        # Clean up absence tracking tables
        try:
            await self.bot.db.execute(
                "DELETE FROM raid_voice_absences WHERE raid_id = ?",
                (raid_id,),
            )
        except Exception:
            pass
        try:
            await self.bot.db.execute(
                "DELETE FROM raid_leader_absences WHERE raid_id = ?",
                (raid_id,),
            )
        except Exception:
            pass

        # Fetch guild config once for role removal and announcement deletion
        config = None
        try:
            config = await self.bot.db.get_guild_config(guild.id)
        except Exception:
            logging.exception("Failed to fetch guild config during auto-close for raid_id=%s", raid_id)

        # Remove raid leader role
        try:
            raid_leader_role_id = (
                config["raid_leader_role_id"]
                if config and "raid_leader_role_id" in config.keys()
                else None
            )
            if raid_leader_role_id:
                raid_leader_role = guild.get_role(raid_leader_role_id)
                leader = guild.get_member(leader_id)
                if raid_leader_role and leader:
                    try:
                        await leader.remove_roles(raid_leader_role, reason=f"Raid auto-closed ({reason}).")
                    except discord.HTTPException:
                        pass
        except Exception:
            logging.exception("Failed to remove raid leader role during auto-close for raid_id=%s", raid_id)

        # Remove the raid announcement from the active raids channel
        try:
            active_channel_id = (
                config["raid_channel_id"]
                if config and "raid_channel_id" in config.keys()
                else None
            )
            announcement_message_id = None
            try:
                announcement_message_id = raid["announcement_message_id"]
            except Exception:
                announcement_message_id = None

            active_channel = (
                guild.get_channel(active_channel_id)
                if isinstance(active_channel_id, int)
                else None
            )
            if isinstance(active_channel, discord.TextChannel) and isinstance(announcement_message_id, int):
                try:
                    msg = await active_channel.fetch_message(announcement_message_id)
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass
                except Exception:
                    logging.exception("Failed to delete raid announcement message during auto-close")
        except Exception:
            logging.exception("Failed to remove raid announcement during auto-close for raid_id=%s", raid_id)

        # Archive/lock the thread
        if thread is not None:
            new_name = getattr(thread, "name", None)
            if isinstance(new_name, str) and "[closed]" not in new_name.lower():
                new_name = f"[Closed] {new_name}"

            try:
                await thread.edit(name=new_name, archived=True, locked=True)
            except Exception:
                logging.exception("Failed to archive/rename raid thread during auto-close for raid_id=%s", raid_id)

async def setup(bot: commands.Bot):
    await bot.add_cog(TasksCog(bot))
