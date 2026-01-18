import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import logging
import re
import io
from ..utils import create_info_embed, create_error_embed, create_success_embed, is_admin, is_officer, send_dkp_change_dm
from ..ui.views import RaidControlView, RaidOpenPanelView, RaidGroupSignupView
from ..ui.modals import DKPAdjustmentModal, RaidCreateModal

MAX_DKP_ADJUSTMENT = 100000


class RaidCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Tracks how many DKP adjustments have been made per raid thread
        # so we can re-show the control panel only after every 4th change
        # instead of after every single award/deduct.
        # Key: (guild_id, thread_id, leader_id) -> int count
        self._dkp_adjust_counts: dict[tuple[int, int, int], int] = {}

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        if not isinstance(after, discord.Thread):
            return
        if after.guild is None:
            return
        try:
            raid = await self.bot.db.fetchone(
                "SELECT * FROM raids WHERE thread_id = ?",
                (after.id,),
            )
        except Exception:
            return

        if not raid:
            return

        try:
            await self.ensure_raid_thread_name(after, raid, requested_name=after.name)
        except Exception:
            logging.exception("Failed to enforce raid thread name on thread update")

    def _format_raid_log_thread_name(self, guild: discord.Guild, raid: dict, requested_name: str) -> str:
        leader_id = None
        try:
            leader_id = raid["leader_id"]
        except Exception:
            leader_id = raid.get("leader_id") if isinstance(raid, dict) else None
        leader_member = guild.get_member(int(leader_id)) if leader_id and guild else None
        leader_display = (
            leader_member.display_name
            if isinstance(leader_member, discord.Member)
            else str(leader_id) if leader_id else "Unknown"
        )

        suffix_prefix = " - Raid Log - "
        max_len = 100
        max_display = max_len - len(suffix_prefix)
        if max_display < 1:
            max_display = 1
        if len(leader_display) > max_display:
            leader_display = leader_display[:max_display]

        suffix = f"{suffix_prefix}{leader_display}"

        base = (requested_name or "").strip()
        base = re.sub(r"\s*-\s*Raid Log\s*-\s*.*$", "", base, flags=re.IGNORECASE).strip()
        if not base:
            base = "Raid"

        allowed_base_len = max_len - len(suffix)
        if allowed_base_len < 1:
            allowed_base_len = 1
        if len(base) > allowed_base_len:
            base = base[:allowed_base_len].rstrip()

        full = f"{base}{suffix}"
        if len(full) > max_len:
            full = full[:max_len]
        return full

    async def ensure_raid_thread_name(self, thread: discord.Thread, raid: dict, requested_name: str | None = None):
        if not thread.guild:
            return
        desired = self._format_raid_log_thread_name(thread.guild, raid, requested_name or thread.name)
        if thread.name == desired:
            return
        try:
            await thread.edit(name=desired)
        except Exception:
            logging.exception("Failed to enforce raid thread name")

    async def maybe_send_control_panel_ephemeral(
        self,
        interaction: discord.Interaction,
        raid: dict | None = None,
    ):
        if not interaction.guild:
            return

        if not isinstance(interaction.user, discord.Member):
            return

        thread = interaction.channel if isinstance(interaction.channel, discord.Thread) else None
        if not isinstance(thread, discord.Thread):
            channel_id = getattr(interaction, "channel_id", None)
            if channel_id:
                try:
                    resolved = self.bot.get_channel(int(channel_id))
                    if resolved is None:
                        resolved = await self.bot.fetch_channel(int(channel_id))
                    if isinstance(resolved, discord.Thread):
                        thread = resolved
                except Exception:
                    return

        if not isinstance(thread, discord.Thread):
            return

        if raid is None:
            raid = await self.bot.db.get_raid_by_thread(thread.id)
        if not raid:
            return

        admin_ok = await is_admin(interaction)
        if interaction.user.id != raid["leader_id"] and not admin_ok:
            return

        key = (interaction.guild.id, thread.id, interaction.user.id)
        current = self._dkp_adjust_counts.get(key, 0) + 1
        self._dkp_adjust_counts[key] = current

        if current % 4 == 0:
            await self._send_control_panel_ephemeral(interaction, thread)

    async def _send_control_panel_ephemeral(self, interaction: discord.Interaction, thread: discord.Thread):
        """Send the raid control panel as an ephemeral message to the raid leader.

        The raid log thread itself remains clean history ("Raid started by...",
        DKP changes, team updates). The control panel is only visible to the
        leader and can be re-sent after actions to keep it near the bottom of
        their view.
        """
        if not isinstance(interaction.user, discord.Member):
            return
        control_embed = create_info_embed(
            f"Raid Control Panel for {interaction.user.display_name}",
            "Use the buttons below to manage your raid. This panel is only visible to you.",
        )
        view = RaidControlView(self.bot, show_leader_buttons=True)
        await interaction.followup.send(
            f"Manage the raid in {thread.mention}.",
            embed=control_embed,
            view=view,
            ephemeral=True,
        )

    async def send_ephemeral_raid_panel(self, interaction: discord.Interaction):
        """Send an ephemeral raid panel adjusted for the current user.

        - If the user is the raid leader, they see the full control panel.
        - If they are a raider/non-leader, they see only the buttons they can use
          (e.g., My DKP, any other non-leader actions in the future).

        This is used after certain interactions (like checking "My DKP") so that
        the raid panel keeps reappearing near the bottom of their chat.
        """
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            return

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return

        is_leader = interaction.user.id == raid["leader_id"]
        admin_ok = await is_admin(interaction)
        can_manage = is_leader or admin_ok

        officer_ok = await is_officer(interaction)
        can_rename_thread = can_manage or officer_ok

        title = f"Raid Control Panel for {interaction.user.display_name}"
        description = (
            "Use the buttons below to manage your raid. This panel is only visible to you."
            if can_manage
            else "Use the buttons below to view your DKP and other raid info. This panel is only visible to you."
        )

        embed = create_info_embed(title, description)
        view = RaidControlView(
            self.bot,
            show_leader_buttons=can_manage,
            show_rename_thread_button=can_rename_thread,
        )

        # If the original interaction has not been responded to yet, send via
        # the initial response; otherwise use a followup.
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=embed,
                    view=view,
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    embed=embed,
                    view=view,
                    ephemeral=True,
                )
        except discord.HTTPException:
            # Interaction may have expired or otherwise failed; safe to ignore.
            return

    async def create_raid_from_interaction(self, interaction: discord.Interaction):
        """Entry point from commands/buttons: checks, then opens the raid-name modal."""
        modal = RaidCreateModal(self)
        try:
            await interaction.response.send_modal(modal)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            try:
                await interaction.followup.send(
                    "This interaction expired. Please try /raid_create again.",
                    ephemeral=True,
                )
            except Exception:
                pass

    async def create_raid_with_name(self, interaction: discord.Interaction, raid_name: str):
        """Actually create the raid using a provided raid name from the modal."""
        if not interaction.guild:
            return

        # Defer so we can safely do followup messages from modal submission
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                pass

        # Allow either officers or bot admins (DKP Admin / server admins) to create raids.
        admin_ok = await is_admin(interaction)
        officer_ok = await is_officer(interaction)
        if not (admin_ok or officer_ok):
            try:
                message = "You must be an officer or bot admin to create a raid."
                if interaction.response.is_done():
                    return await interaction.followup.send(
                        message,
                        ephemeral=True,
                    )
                return await interaction.response.send_message(
                    message,
                    ephemeral=True,
                )
            except Exception:
                return

        config = await self.bot.db.get_guild_config(interaction.guild.id)
        if not config or not config["raid_channel_id"]:
            try:
                return await interaction.followup.send(
                    embed=create_error_embed(
                        "Setup Incomplete",
                        "The bot is not fully set up. Please ask an admin to re-invite the bot.",
                    ),
                    ephemeral=True,
                )
            except Exception:
                return

        # Optionally associate the raid with the leader's current voice channel.
        # Raids can be started even if the leader is not connected to voice.
        leader_member = interaction.user if isinstance(interaction.user, discord.Member) else None
        leader_voice = getattr(leader_member, "voice", None)
        raid_vc = getattr(leader_voice, "channel", None)
        raid_vc_id = raid_vc.id if isinstance(raid_vc, discord.VoiceChannel) else None

        active_raids_channel = interaction.guild.get_channel(config["raid_channel_id"])
        if not active_raids_channel:
            try:
                return await interaction.followup.send(
                    embed=create_error_embed(
                        "Setup Error",
                        "Required channels are missing. Please re-invite the bot.",
                    ),
                    ephemeral=True,
                )
            except Exception:
                return

        # Basic sanitisation/trim to keep within Discord limits
        raid_name = raid_name.strip()
        if not raid_name:
            raid_name = "Raid"

        try:
            raid_date = datetime.now().strftime("%Y-%m-%d")
            user_display = (
                interaction.user.display_name
                if isinstance(interaction.user, discord.Member)
                else str(interaction.user)
            )
            # Assign raid leader role if configured (no channel permission
            # overrides are applied here so existing voice channel permissions
            # remain under guild control).
            raid_leader_role_id = config["raid_leader_role_id"] if "raid_leader_role_id" in config else None
            if raid_leader_role_id:
                raid_leader_role = interaction.guild.get_role(raid_leader_role_id)
                if raid_leader_role:
                    await interaction.user.add_roles(raid_leader_role, reason="Started a raid.")
                else:
                    await interaction.followup.send(
                        "The configured Raid-Leader role was not found. Please have an admin set a new one.",
                        ephemeral=True,
                    )

            # Create the main raid announcement message and thread.
            start_timestamp = int(datetime.now().timestamp())
            base_content = f"Raid '{raid_name}' started by {interaction.user.mention} on <t:{start_timestamp}:F>"
            raid_message = await active_raids_channel.send(base_content)
            thread_name = self._format_raid_log_thread_name(
                interaction.guild,
                {"leader_id": interaction.user.id},
                raid_name,
            )
            thread = await raid_message.create_thread(name=thread_name)
            await self.bot.db.execute(
                "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, announcement_message_id) VALUES (?, ?, ?, ?, ?)",
                (interaction.guild.id, interaction.user.id, raid_vc_id, thread.id, raid_message.id),
            )

            try:
                raid_row = await self.bot.db.fetchone("SELECT * FROM raids WHERE thread_id = ?", (thread.id,))
                if raid_row and raid_vc_id:
                    try:
                        await self.bot.db.add_raid_voice_channel(int(raid_row["id"]), int(raid_vc_id))
                    except Exception:
                        pass
                if raid_row:
                    await self.ensure_raid_thread_name(thread, raid_row)
            except Exception:
                logging.exception("Failed to enforce initial raid thread name")

            # After the thread exists, edit the original raid message to ping
            # raiders (if configured) and include a direct jump link to the
            # raid log thread so everyone can easily navigate there.
            raider_mention_prefix = ""
            raider_role_id = config["raider_role_id"] if "raider_role_id" in config else None
            if raider_role_id:
                raider_role = interaction.guild.get_role(raider_role_id)
                if raider_role:
                    raider_mention_prefix = f"{raider_role.mention} "

            updated_content = (
                f"{raider_mention_prefix}{base_content}\n\n"
                f"Jump to the current raid log thread: {thread.mention}"
            )
            try:
                await raid_message.edit(content=updated_content)
            except discord.HTTPException:
                # If we cannot edit the message, we still continue with raid
                # creation; users can reach the thread via the channel UI.
                pass

            # Keep the raid log thread clean: show only a single public button
            # that opens an ephemeral, per-user control panel.
            control_embed = create_info_embed(
                "Raid Control Panel",
                "Click the button below to open your control panel (ephemeral).",
            )
            view = RaidOpenPanelView(self.bot)
            await thread.send(embed=control_embed, view=view)

            # Also send a short ephemeral confirmation back to the raid leader
            # so that any temporary "bot is thinking" indicator from the
            # deferred modal submission is replaced with a clear success
            # message.
            try:
                await interaction.followup.send(
                    f"Raid '{raid_name}' has been created. Use the control panel in {thread.mention} to manage it.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                # Interaction may have expired; the public thread/log still exists
                # so we can safely ignore this.
                pass
        except Exception as e:
            logging.error(f"Failed to create raid: {e}")
            await interaction.followup.send(embed=create_error_embed("Error", "Could not create the raid. Check my permissions."))

    @app_commands.command(name="raid_create", description="Creates a new raid channel and control thread.")
    @app_commands.check(is_admin)
    async def raid_create_cmd(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        await self.create_raid_from_interaction(interaction)

    @app_commands.command(name="raid_end", description="Ends and closes the current raid.")
    async def raid_end_cmd(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        if not await is_officer(interaction):
            return await interaction.response.send_message("You must be an officer or admin to end a raid.", ephemeral=True)
        await self.close_raid(interaction)

    @app_commands.command(name="raid_add_member", description="Admin only: add a member to the current raid without requiring them to be in the voice channel.")
    @app_commands.check(is_admin)
    @app_commands.describe(member="The member to add as a participant in this raid.")
    async def raid_add_member_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message(
                "This channel is not associated with an active raid.",
                ephemeral=True,
            )

        if member.bot:
            return await interaction.response.send_message(
                "Bots cannot be added as raid members.",
                ephemeral=True,
            )

        await self.bot.db.add_raid_member(raid["id"], member.id)

        try:
            await self.bot.db.remove_raid_member_exclusion(int(raid["id"]), int(member.id))
        except Exception:
            pass

        await interaction.response.send_message(
            f"{member.mention} has been added to this raid. They can now receive DKP adjustments and participate as a raid member even if they are not in the voice channel.",
            ephemeral=True,
        )

    @app_commands.command(name="raid_remove_member", description="Remove a member from the current raid (prevents them from receiving raid DKP).")
    @app_commands.describe(member="The member to remove from this raid.")
    async def raid_remove_member_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        if not await is_officer(interaction):
            return await interaction.response.send_message(
                "You must be an officer or admin to remove raid members.",
                ephemeral=True,
            )

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message(
                "This channel is not associated with an active raid.",
                ephemeral=True,
            )

        if member.bot:
            return await interaction.response.send_message("Bots cannot be raid members.", ephemeral=True)

        raid_id = int(raid["id"])

        try:
            removed = await self.bot.db.remove_raid_member(raid_id, int(member.id))
        except Exception:
            removed = False

        try:
            await self.bot.db.add_raid_member_exclusion(raid_id, int(member.id))
        except Exception:
            pass

        try:
            await self.bot.db.delete_raid_join_request(raid_id, int(member.id))
        except Exception:
            pass

        if not removed:
            return await interaction.response.send_message(
                f"{member.mention} is not part of this raid.",
                ephemeral=True,
            )

        try:
            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(f"{member.mention} was removed from the raid.")
        except Exception:
            logging.exception("Failed to send removal message to raid thread")

        return await interaction.response.send_message(
            f"Removed {member.mention} from the raid.",
            ephemeral=True,
        )

    @app_commands.command(name="raid_set_group", description="Assign a raid member to a group number.")
    @app_commands.describe(member="The member to assign.", group_number="Group number (e.g. 1, 2, 3)")
    async def raid_set_group_cmd(self, interaction: discord.Interaction, member: discord.Member, group_number: int):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        if not await is_officer(interaction):
            return await interaction.response.send_message(
                "You must be an officer or admin to manage raid groups.",
                ephemeral=True,
            )

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

        if group_number < 1:
            return await interaction.response.send_message("Group number must be 1 or higher.", ephemeral=True)

        if member.bot:
            return await interaction.response.send_message("Bots cannot be assigned to groups.", ephemeral=True)

        raid_id = int(raid["id"])
        if not await self.bot.db.is_raid_member(raid_id, int(member.id)):
            return await interaction.response.send_message(
                "That member is not currently part of this raid.",
                ephemeral=True,
            )

        await self.bot.db.set_raid_member_group(raid_id, int(member.id), int(group_number))
        await interaction.response.send_message(
            f"Assigned {member.mention} to group **{group_number}**.",
            ephemeral=True,
        )

    @app_commands.command(name="raid_clear_group", description="Remove a raid member from any group.")
    @app_commands.describe(member="The member to clear.")
    async def raid_clear_group_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        if not await is_officer(interaction):
            return await interaction.response.send_message(
                "You must be an officer or admin to manage raid groups.",
                ephemeral=True,
            )

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

        await self.bot.db.set_raid_member_group(int(raid["id"]), int(member.id), None)
        await interaction.response.send_message(f"Cleared group assignment for {member.mention}.", ephemeral=True)

    async def member_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        raid = await self.bot.db.get_raid_by_thread(interaction.channel_id)
        if not raid or not interaction.guild:
            return []

        members_by_id: dict[int, discord.Member] = {}

        try:
            member_rows = await self.bot.db.get_raid_members(raid["id"])
        except Exception:
            member_rows = []

        for row in member_rows:
            user_id = row["user_id"]
            if user_id in members_by_id:
                continue
            gm = interaction.guild.get_member(user_id)
            if gm and not gm.bot:
                members_by_id[user_id] = gm

        lowered = current.lower()
        return [
            app_commands.Choice(name=m.display_name, value=str(m.id))
            for m in members_by_id.values()
            if lowered in m.display_name.lower()
        ][:25]

    @app_commands.command(name="award", description="Award DKP to a member or the entire raid.")
    @app_commands.autocomplete(member=member_autocomplete)
    @app_commands.describe(member="(Optional) The member to award DKP to. Leave blank to award to the entire raid.")
    async def award_cmd(self, interaction: discord.Interaction, member: str | None = None):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        if not await is_officer(interaction):
            return await interaction.response.send_message("You must be an officer to use this command.", ephemeral=True)
        target_member = await self._get_member_from_str(interaction, member)
        modal = DKPAdjustmentModal(action="Award", raid_cog=self, member=target_member, group_number=None)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="deduct", description="Deduct DKP from a member or the entire raid.")
    @app_commands.autocomplete(member=member_autocomplete)
    @app_commands.describe(member="(Optional) The member to deduct DKP from. Leave blank to deduct from the entire raid.")
    async def deduct_cmd(self, interaction: discord.Interaction, member: str | None = None):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        if not await is_officer(interaction):
            return await interaction.response.send_message("You must be an officer to use this command.", ephemeral=True)
        target_member = await self._get_member_from_str(interaction, member)
        modal = DKPAdjustmentModal(action="Deduct", raid_cog=self, member=target_member, group_number=None)
        await interaction.response.send_modal(modal)

    async def _get_member_from_str(self, interaction: discord.Interaction, member_str: str | None) -> discord.Member | None:
        if not member_str:
            return None
        try:
            member_id = int(member_str)
            return interaction.guild.get_member(member_id)
        except (ValueError, TypeError):
            return None

    async def _get_linked_voice_channels(self, guild: discord.Guild, raid: dict) -> list[discord.VoiceChannel]:
        vc_ids: set[int] = set()

        primary = None
        try:
            primary = raid["vc_id"]
        except Exception:
            try:
                primary = raid.get("vc_id") if isinstance(raid, dict) else None
            except Exception:
                primary = None

        if primary:
            try:
                vc_ids.add(int(primary))
            except Exception:
                pass

        try:
            rows = await self.bot.db.get_raid_voice_channels(int(raid["id"]))
        except Exception:
            rows = []

        for row in list(rows or []):
            try:
                vc_ids.add(int(row["vc_id"]))
            except Exception:
                continue

        channels: list[discord.VoiceChannel] = []
        for vc_id in vc_ids:
            ch = guild.get_channel(int(vc_id))
            if isinstance(ch, discord.VoiceChannel):
                channels.append(ch)

        return channels

    async def update_team_from_voice_channel(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.followup.send(
                "This command can only be used inside a server.",
                ephemeral=True,
            )

        # Ensure we can safely use followups even when called outside the raid
        # panel (e.g., future slash commands).
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=False)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                pass

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)

        admin_ok = await is_admin(interaction)
        if int(interaction.user.id) != int(raid["leader_id"]) and not admin_ok:
            return await interaction.followup.send(
                "You must be the raid leader or a bot admin to update the team.",
                ephemeral=True,
            )

        leader_member = interaction.guild.get_member(int(raid["leader_id"]))
        if not leader_member:
            return await interaction.followup.send(
                "Raid leader not found in this server.",
                ephemeral=True,
            )

        leader_voice = getattr(leader_member, "voice", None)
        vc = getattr(leader_voice, "channel", None)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.followup.send(
                "You must be connected to a voice channel to use Update Team.",
                ephemeral=True,
            )

        raid_id = int(raid["id"])

        try:
            await self.bot.db.execute(
                "UPDATE raids SET vc_id = ? WHERE id = ?",
                (vc.id, raid_id),
            )
        except Exception:
            pass

        try:
            await self.bot.db.add_raid_voice_channel(raid_id, int(vc.id))
        except Exception:
            pass

        linked_vcs = await self._get_linked_voice_channels(interaction.guild, raid)
        if not linked_vcs:
            return await interaction.followup.send(
                "This raid is not currently associated with any voice channels.",
                ephemeral=True,
            )

        voice_members_by_id: dict[int, discord.Member] = {}
        for linked_vc in linked_vcs:
            for member in list(getattr(linked_vc, "members", []) or []):
                if getattr(member, "bot", False):
                    continue
                voice_members_by_id[int(member.id)] = member

        added = 0
        for member in list(voice_members_by_id.values()):
            try:
                if await self.bot.db.is_raid_member_excluded(raid_id, int(member.id)):
                    continue
            except Exception:
                pass
            try:
                inserted = await self.bot.db.add_raid_member(raid_id, int(member.id))
            except Exception:
                inserted = False
            if inserted:
                added += 1

        if added:
            vc_mentions = ", ".join([v.mention for v in linked_vcs])
            await interaction.followup.send(
                f"Added **{added}** member(s) from linked voice channels to the raid: {vc_mentions}",
            )

        await self.update_team_list(interaction)

    async def show_voice_roster(self, interaction: discord.Interaction):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)

        if not interaction.guild:
            return await interaction.followup.send("This command can only be used inside a server.", ephemeral=True)

        linked_vcs = await self._get_linked_voice_channels(interaction.guild, raid)
        if not linked_vcs:
            return await interaction.followup.send(
                "This raid is not currently associated with any voice channels.",
                ephemeral=True,
            )

        per_vc: list[tuple[discord.VoiceChannel, list[discord.Member]]] = []
        all_members_by_id: dict[int, discord.Member] = {}
        for vc in linked_vcs:
            members = [m for m in list(getattr(vc, "members", []) or []) if not getattr(m, "bot", False)]
            per_vc.append((vc, members))
            for m in members:
                all_members_by_id[int(m.id)] = m

        if not all_members_by_id:
            vc_mentions = ", ".join([v.mention for v in linked_vcs])
            return await interaction.followup.send(
                f"No players are currently in linked raid voice channels: {vc_mentions}.",
            )

        vc_mentions = ", ".join([v.mention for v in linked_vcs])
        lines: list[str] = [f"Voice channels: {vc_mentions}", f"Total players in voice (**{len(all_members_by_id)}**):"]

        for vc, members in per_vc:
            if not members:
                continue
            mentions = ", ".join([m.mention for m in members])
            lines.append(f"**{vc.mention}** (**{len(members)}**): {mentions}")

        description = "\n".join(lines)
        if len(description) > 4096:
            description = description[:4090] + "..."

        embed = create_info_embed("Voice Channel Roster", description)
        await interaction.followup.send(embed=embed)

    async def sync_raid_with_voice_channels(
        self,
        interaction: discord.Interaction,
        remove_missing: bool = False,
        confirm: bool = False,
    ):
        if not interaction.guild:
            return await interaction.followup.send(
                "This command can only be used inside a server.",
                ephemeral=True,
            )

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=False)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                pass

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)

        admin_ok = await is_admin(interaction)
        officer_ok = await is_officer(interaction)
        if int(interaction.user.id) != int(raid["leader_id"]) and not admin_ok and not officer_ok:
            return await interaction.followup.send(
                "You must be the raid leader, an officer, or a bot admin to sync raid members.",
                ephemeral=True,
            )

        raid_id = int(raid["id"])

        linked_vcs = await self._get_linked_voice_channels(interaction.guild, raid)
        if not linked_vcs:
            return await interaction.followup.send(
                "This raid is not currently associated with any voice channels.",
                ephemeral=True,
            )

        voice_members_by_id: dict[int, discord.Member] = {}
        for vc in linked_vcs:
            for member in list(getattr(vc, "members", []) or []):
                if getattr(member, "bot", False):
                    continue
                voice_members_by_id[int(member.id)] = member

        try:
            member_rows = await self.bot.db.get_raid_members(raid_id)
        except Exception:
            member_rows = []

        raid_member_ids: set[int] = set()
        for row in list(member_rows or []):
            try:
                raid_member_ids.add(int(row["user_id"]))
            except Exception:
                continue

        added = 0
        for member in list(voice_members_by_id.values()):
            try:
                if await self.bot.db.is_raid_member_excluded(raid_id, int(member.id)):
                    continue
            except Exception:
                pass
            try:
                inserted = await self.bot.db.add_raid_member(raid_id, int(member.id))
            except Exception:
                inserted = False
            if inserted:
                added += 1

        missing_from_voice: list[int] = []
        if remove_missing:
            for uid in sorted(raid_member_ids):
                if uid in voice_members_by_id:
                    continue
                # Don't auto-remove excluded users here; exclusion is for preventing
                # re-add. If they're still present in raid_members, that's already
                # an inconsistency and should be handled explicitly.
                missing_from_voice.append(uid)

        if remove_missing and missing_from_voice and not confirm:
            preview_mentions = ", ".join([f"<@{uid}>" for uid in missing_from_voice[:20]])
            if len(missing_from_voice) > 20:
                preview_mentions += f" … and {len(missing_from_voice) - 20} more"
            vc_mentions = ", ".join([v.mention for v in linked_vcs])
            return await interaction.followup.send(
                "Sync preview:\n"
                f"- Linked voice channels: {vc_mentions}\n"
                f"- Would remove **{len(missing_from_voice)}** raid member(s) not in those channels.\n"
                f"- Preview: {preview_mentions}\n\n"
                "Re-run with `confirm: true` to remove them.",
                ephemeral=True,
            )

        removed = 0
        if remove_missing and missing_from_voice and confirm:
            for uid in missing_from_voice:
                try:
                    did_remove = await self.bot.db.remove_raid_member(raid_id, int(uid))
                except Exception:
                    did_remove = False
                if did_remove:
                    removed += 1

        vc_mentions = ", ".join([v.mention for v in linked_vcs])
        summary_parts: list[str] = [f"Linked voice channels: {vc_mentions}"]
        summary_parts.append(f"Added: **{added}**")
        if remove_missing:
            summary_parts.append(f"Removed: **{removed}**")
        await interaction.followup.send("Sync Voice complete. " + " | ".join(summary_parts))

        await self.update_team_list(interaction)

    @app_commands.command(name="raid_sync_voice", description="Sync raid membership with linked voice channels.")
    @app_commands.describe(remove_missing="Also remove raid members who are not in linked voice channels.")
    @app_commands.describe(confirm="Required when remove_missing is true (safety confirmation).")
    async def raid_sync_voice_cmd(
        self,
        interaction: discord.Interaction,
        remove_missing: bool = False,
        confirm: bool = False,
    ):
        await self.sync_raid_with_voice_channels(interaction, remove_missing=remove_missing, confirm=confirm)

    @app_commands.command(name="raid_add_voice_channel", description="Link an additional voice channel to the current raid.")
    @app_commands.describe(channel="The voice channel to link to this raid.")
    async def raid_add_voice_channel_cmd(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

        admin_ok = await is_admin(interaction)
        officer_ok = await is_officer(interaction)
        if int(interaction.user.id) != int(raid["leader_id"]) and not admin_ok and not officer_ok:
            return await interaction.response.send_message(
                "You must be the raid leader, an officer, or a bot admin to link voice channels.",
                ephemeral=True,
            )

        raid_id = int(raid["id"])
        await self.bot.db.add_raid_voice_channel(raid_id, int(channel.id))

        try:
            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(f"Linked voice channel {channel.mention} to this raid.")
        except Exception:
            logging.exception("Failed to announce linked voice channel")

        return await interaction.response.send_message(
            f"Linked voice channel {channel.mention} to this raid.",
            ephemeral=True,
        )

    @app_commands.command(name="raid_remove_voice_channel", description="Unlink a voice channel from the current raid.")
    @app_commands.describe(channel="The voice channel to unlink from this raid.")
    async def raid_remove_voice_channel_cmd(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

        admin_ok = await is_admin(interaction)
        officer_ok = await is_officer(interaction)
        if int(interaction.user.id) != int(raid["leader_id"]) and not admin_ok and not officer_ok:
            return await interaction.response.send_message(
                "You must be the raid leader, an officer, or a bot admin to unlink voice channels.",
                ephemeral=True,
            )

        raid_id = int(raid["id"])
        await self.bot.db.remove_raid_voice_channel(raid_id, int(channel.id))

        try:
            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(f"Unlinked voice channel {channel.mention} from this raid.")
        except Exception:
            logging.exception("Failed to announce unlinked voice channel")

        return await interaction.response.send_message(
            f"Unlinked voice channel {channel.mention} from this raid.",
            ephemeral=True,
        )

    @app_commands.command(name="raid_list_voice_channels", description="List voice channels linked to the current raid.")
    async def raid_list_voice_channels_cmd(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        linked_vcs = await self._get_linked_voice_channels(interaction.guild, raid)
        if not linked_vcs:
            return await interaction.followup.send("No voice channels are currently linked to this raid.", ephemeral=True)

        vc_mentions = "\n".join([f"- {vc.mention} (`{vc.id}`)" for vc in linked_vcs])
        embed = create_info_embed("Linked Raid Voice Channels", vc_mentions)
        return await interaction.followup.send(embed=embed, ephemeral=True)

    async def show_raid_groups(self, interaction: discord.Interaction):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)

        members_by_id: dict[int, discord.Member] = {}
        try:
            member_rows = await self.bot.db.get_raid_members(raid["id"])
        except Exception:
            member_rows = []

        for row in member_rows:
            user_id = row["user_id"]
            if user_id in members_by_id:
                continue
            gm = interaction.guild.get_member(user_id) if interaction.guild else None
            if gm and not gm.bot:
                members_by_id[user_id] = gm

        if not members_by_id:
            return await interaction.followup.send("No raid members were found.", ephemeral=True)

        try:
            group_rows = await self.bot.db.get_raid_member_groups(int(raid["id"]))
        except Exception:
            group_rows = []

        member_to_group: dict[int, int] = {}
        for row in group_rows:
            try:
                member_to_group[int(row["user_id"])] = int(row["group_number"])
            except Exception:
                continue

        groups: dict[str, list[str]] = {}
        for uid, member in members_by_id.items():
            grp = member_to_group.get(uid)
            key = f"Group {grp}" if grp is not None else "Ungrouped"
            groups.setdefault(key, []).append(member.mention)

        lines: list[str] = []
        for key in sorted(groups.keys(), key=lambda k: (k == "Ungrouped", k)):
            lines.append(f"**{key}**: {', '.join(groups[key])}")

        embed = create_info_embed("Raid Groups", "\n".join(lines))
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _build_group_signup_embed(self, raid: dict, guild: discord.Guild) -> discord.Embed:
        try:
            group_count = int(raid["group_count"])
        except Exception:
            try:
                group_count = int(dict(raid).get("group_count") or 0)
            except Exception:
                group_count = 0

        members_by_id: dict[int, discord.Member] = {}
        try:
            member_rows = await self.bot.db.get_raid_members(int(raid["id"]))
        except Exception:
            member_rows = []

        for row in member_rows:
            user_id = row.get("user_id") if isinstance(row, dict) else row["user_id"]
            try:
                uid = int(user_id)
            except Exception:
                continue
            if uid in members_by_id:
                continue
            gm = guild.get_member(uid)
            if gm and not gm.bot:
                members_by_id[uid] = gm

        try:
            group_rows = await self.bot.db.get_raid_member_groups(int(raid["id"]))
        except Exception:
            group_rows = []

        member_to_group: dict[int, int] = {}
        for row in group_rows:
            try:
                uid = int(row["user_id"])
                grp = int(row["group_number"])
            except Exception:
                continue
            member_to_group[uid] = grp

        groups: dict[str, list[str]] = {}
        for i in range(1, max(group_count, 0) + 1):
            groups[f"Group {i}"] = []
        groups["Ungrouped"] = []

        for uid, member in members_by_id.items():
            grp = member_to_group.get(uid)
            if grp is not None and 1 <= int(grp) <= group_count:
                groups.setdefault(f"Group {int(grp)}", []).append(member.mention)
            else:
                groups.setdefault("Ungrouped", []).append(member.mention)

        lines: list[str] = []
        if group_count > 0:
            for i in range(1, group_count + 1):
                mentions = ", ".join(groups.get(f"Group {i}") or [])
                lines.append(f"**Group {i}**: {mentions if mentions else '—'}")
        ungrouped = ", ".join(groups.get("Ungrouped") or [])
        lines.append(f"**Ungrouped**: {ungrouped if ungrouped else '—'}")

        description = "\n".join(lines)
        if len(description) > 4096:
            description = description[:4090] + "..."
        return create_info_embed("Group Signups", description)

    async def _ensure_group_panel_message(self, thread: discord.Thread, raid: dict, embed: discord.Embed) -> int:
        raid_id = int(raid["id"])
        msg_id = None
        try:
            msg_id = raid.get("group_panel_message_id")
        except Exception:
            msg_id = None
        try:
            msg_id = int(msg_id) if msg_id else None
        except Exception:
            msg_id = None

        group_count = None
        try:
            group_count = int(raid["group_count"])
        except Exception:
            try:
                if isinstance(raid, dict):
                    group_count = int(raid.get("group_count") or 0)
            except Exception:
                group_count = None
        if group_count is not None and group_count <= 0:
            group_count = None

        view = RaidGroupSignupView(self.bot, group_count=group_count)
        if msg_id:
            try:
                msg = await thread.fetch_message(msg_id)
                await msg.edit(embed=embed, view=view)
                return msg.id
            except Exception:
                msg_id = None

        msg = await thread.send(embed=embed, view=view)
        await self.bot.db.execute(
            "UPDATE raids SET group_panel_message_id = ? WHERE id = ?",
            (int(msg.id), raid_id),
        )
        return int(msg.id)

    async def setup_raid_groups(self, interaction: discord.Interaction, group_count: int):
        if interaction.guild is None:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
                else:
                    await interaction.followup.send("This command cannot be used in DMs.", ephemeral=True)
            except discord.HTTPException:
                pass
            return

        if not isinstance(interaction.channel, discord.Thread):
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("This must be run inside a raid log thread.", ephemeral=True)
                else:
                    await interaction.followup.send("This must be run inside a raid log thread.", ephemeral=True)
            except discord.HTTPException:
                pass
            return

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                pass

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)

        admin_ok = await is_admin(interaction)
        if int(interaction.user.id) != int(raid["leader_id"]) and not admin_ok:
            return await interaction.followup.send(
                "You must be the raid leader or a bot admin to set up groups.",
                ephemeral=True,
            )

        raid_id = int(raid["id"])
        await self.bot.db.execute(
            "UPDATE raids SET group_count = ? WHERE id = ?",
            (int(group_count), raid_id),
        )
        await self.bot.db.execute(
            "DELETE FROM raid_member_groups WHERE raid_id = ?",
            (raid_id,),
        )

        raid_dict = dict(raid)
        raid_dict["group_count"] = int(group_count)
        embed = await self._build_group_signup_embed(raid_dict, interaction.guild)
        msg_id = await self._ensure_group_panel_message(interaction.channel, raid_dict, embed)
        raid_dict["group_panel_message_id"] = int(msg_id)

        await interaction.followup.send("Group signups are ready.", ephemeral=True)

    async def handle_group_signup(self, interaction: discord.Interaction, selected_value: str | None):
        if interaction.guild is None:
            return

        if not isinstance(interaction.channel, discord.Thread):
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("This must be used inside a raid log thread.", ephemeral=True)
                else:
                    await interaction.followup.send("This must be used inside a raid log thread.", ephemeral=True)
            except discord.HTTPException:
                pass
            return

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                pass

        if getattr(interaction.user, "bot", False):
            return await interaction.followup.send("Bots cannot join groups.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)

        raid_id = int(raid["id"])
        user_id = int(interaction.user.id)

        try:
            is_member = await self.bot.db.is_raid_member(raid_id, user_id)
        except Exception:
            is_member = False

        if not is_member:
            return await interaction.followup.send("Join the raid first (click **Join Raid**) before selecting a group.", ephemeral=True)

        try:
            group_count = int(raid["group_count"])
        except Exception:
            try:
                group_count = int(dict(raid).get("group_count") or 0)
            except Exception:
                group_count = 0

        if group_count < 1:
            return await interaction.followup.send("Groups have not been set up for this raid yet.", ephemeral=True)

        group_number: int | None
        if selected_value in (None, "", "0"):
            group_number = None
        else:
            try:
                group_number = int(selected_value)
            except ValueError:
                return await interaction.followup.send("Invalid group selection.", ephemeral=True)
            if group_number < 1 or group_number > group_count:
                return await interaction.followup.send(f"Please select a group between 1 and {group_count}.", ephemeral=True)

        await self.bot.db.set_raid_member_group(raid_id, user_id, group_number)

        raid_dict = dict(raid)
        embed = await self._build_group_signup_embed(raid_dict, interaction.guild)
        msg_id = await self._ensure_group_panel_message(interaction.channel, raid_dict, embed)

        if msg_id and (raid_dict.get("group_panel_message_id") != msg_id):
            try:
                await self.bot.db.execute(
                    "UPDATE raids SET group_panel_message_id = ? WHERE id = ?",
                    (int(msg_id), raid_id),
                )
            except Exception:
                pass

        if group_number is None:
            return await interaction.followup.send("You have left your group.", ephemeral=True)
        return await interaction.followup.send(f"You joined **Group {group_number}**.", ephemeral=True)

    async def update_team_list(self, interaction: discord.Interaction):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)

        members_by_id: dict[int, discord.Member] = {}

        try:
            member_rows = await self.bot.db.get_raid_members(raid["id"])
        except Exception:
            member_rows = []

        for row in member_rows:
            user_id = row["user_id"]
            if user_id in members_by_id:
                continue
            gm = interaction.guild.get_member(user_id) if interaction.guild else None
            if gm and not gm.bot:
                members_by_id[user_id] = gm

        members = list(members_by_id.values())
        members.sort(key=lambda m: (m.display_name or "").lower())
        if not members:
            return await interaction.followup.send("No raid members were found for this raid.")

        member_list = "\n".join([f"- {member.mention} ({member.display_name})" for member in members])
        embed = create_info_embed(
            "Current Raid Team",
            f"Last updated: <t:{int(datetime.now().timestamp())}:R>\n\n{member_list}"
        )
        await interaction.followup.send(embed=embed)

        # Refresh the ephemeral control panel for the raid leader
        thread = interaction.channel if isinstance(interaction.channel, discord.Thread) else None
        if isinstance(thread, discord.Thread):
            await self.maybe_send_control_panel_ephemeral(interaction, raid=raid)

    async def process_dkp_adjustment(
        self,
        interaction: discord.Interaction,
        action: str,
        amount_str: str,
        reason: str,
        member: discord.Member | None = None,
        group_number: int | None = None,
        source: str | None = None,
    ):
        # Defer if not already deferred
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            amount = int(amount_str)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await interaction.followup.send(
                embed=create_error_embed("Invalid Amount", "DKP amount must be a positive number."),
                ephemeral=True,
            )
            if source == "raid_panel":
                await self.send_ephemeral_raid_panel(interaction)
            return

        admin_ok = await is_admin(interaction)

        if amount > MAX_DKP_ADJUSTMENT and not admin_ok:
            await interaction.followup.send(
                embed=create_error_embed(
                    "Invalid Amount",
                    f"DKP amount must be a positive number up to {MAX_DKP_ADJUSTMENT}.",
                ),
                ephemeral=True,
            )
            if source == "raid_panel":
                await self.send_ephemeral_raid_panel(interaction)
            return

        if action == "Deduct":
            amount = -amount

        if group_number is not None and member is not None:
            await interaction.followup.send(
                embed=create_error_embed(
                    "Invalid Target",
                    "Choose either a member or a group (not both).",
                ),
                ephemeral=True,
            )
            if source == "raid_panel":
                await self.send_ephemeral_raid_panel(interaction)
            return

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            await interaction.followup.send(
                embed=create_error_embed(
                    "No Active Raid",
                    "This channel is not associated with an active raid. DKP changes can only be made from a raid log thread.",
                ),
                ephemeral=True,
            )
            if source == "raid_panel":
                await self.send_ephemeral_raid_panel(interaction)
            return

        if group_number is not None:
            try:
                group_number = int(group_number)
            except Exception:
                group_number = None

        if group_number is not None:
            group_count = 0
            try:
                group_count = int(raid["group_count"])
            except Exception:
                try:
                    group_count = int(dict(raid).get("group_count") or 0)
                except Exception:
                    group_count = 0

            if group_count <= 0:
                await interaction.followup.send(
                    embed=create_error_embed(
                        "Groups Not Set Up",
                        "Groups have not been set up for this raid yet.",
                    ),
                    ephemeral=True,
                )
                if source == "raid_panel":
                    await self.send_ephemeral_raid_panel(interaction)
                return

            if group_number < 1 or group_number > group_count:
                await interaction.followup.send(
                    embed=create_error_embed(
                        "Invalid Group",
                        f"Group number must be between 1 and {group_count}.",
                    ),
                    ephemeral=True,
                )
                if source == "raid_panel":
                    await self.send_ephemeral_raid_panel(interaction)
                return

        vc = interaction.guild.get_channel(raid["vc_id"]) if interaction.guild else None

        if member is None:
            # Mass adjustment: include all non-bot guild members recorded in
            # raid_members table for this raid.
            targets_by_id: dict[int, discord.Member] = {}

            try:
                member_rows = await self.bot.db.get_raid_members(raid["id"])
            except Exception:
                member_rows = []

            for row in member_rows:
                user_id = row["user_id"]
                if user_id in targets_by_id:
                    continue
                gm = interaction.guild.get_member(user_id) if interaction.guild else None
                if gm and not gm.bot:
                    targets_by_id[user_id] = gm

            if group_number is not None:
                try:
                    group_rows = await self.bot.db.get_raid_member_groups(int(raid["id"]))
                except Exception:
                    group_rows = []

                member_to_group: dict[int, int] = {}
                for row in group_rows:
                    try:
                        uid = int(row["user_id"])
                        grp = int(row["group_number"])
                    except Exception:
                        continue
                    member_to_group[uid] = grp

                targets = [
                    m
                    for uid, m in targets_by_id.items()
                    if member_to_group.get(int(uid)) == int(group_number)
                ]
            else:
                targets = list(targets_by_id.values())
        else:
            if member.bot:
                await interaction.followup.send(
                    embed=create_error_embed(
                        "Invalid Target",
                        "DKP cannot be adjusted for bot accounts.",
                    ),
                    ephemeral=True,
                )
                if source == "raid_panel":
                    await self.send_ephemeral_raid_panel(interaction)
                return
            raid_member_ids = set()
            try:
                member_rows = await self.bot.db.get_raid_members(raid["id"])
                raid_member_ids = {row["user_id"] for row in member_rows}
            except Exception:
                raid_member_ids = set()

            if member.id not in raid_member_ids:
                await interaction.followup.send(
                    embed=create_error_embed(
                        "Invalid Target",
                        "DKP can only be adjusted for approved raid members.",
                    ),
                    ephemeral=True,
                )
                if source == "raid_panel":
                    await self.send_ephemeral_raid_panel(interaction)
                return
            targets = [member]

        if not targets:
            await interaction.followup.send(
                embed=create_error_embed(
                    "No Eligible Targets",
                    "No eligible raid members were found to adjust DKP for.",
                ),
                ephemeral=True,
            )
            if source == "raid_panel":
                await self.send_ephemeral_raid_panel(interaction)
            return

        for m in targets:
            await self.bot.db.modify_user_dkp(
                m.id,
                interaction.guild.id,
                amount,
                f"{action}: {reason} (Raid)",
            )
            await send_dkp_change_dm(
                m,
                interaction.guild,
                amount,
                f"{action}: {reason} (Raid)",
            )

        action_word = "Awarded" if action == "Award" else "Deducted"
        if member:
            description = f"**{abs(amount)} DKP** {action_word.lower()} to {member.mention} for: *{reason}*."
        elif group_number is not None:
            mentions = ", ".join([m.mention for m in targets])
            description = (
                f"**{abs(amount)} DKP** {action_word.lower()} to **Group {int(group_number)}** "
                f"(**{len(targets)}** players) for: *{reason}*.\n{mentions}"
            )
        else:
            mentions = ", ".join([m.mention for m in targets])
            description = f"**{abs(amount)} DKP** {action_word.lower()} to **{len(targets)}** players for: *{reason}*.\n{mentions}"

        if len(description) > 4096:
            description = description[:4090] + "..."

        if action == "Deduct":
            embed = create_error_embed(f"DKP {action_word}!", description)
        else:
            embed = create_success_embed(f"DKP {action_word}!", description)
        await interaction.followup.send(embed=embed)

        await self.maybe_send_control_panel_ephemeral(interaction, raid=raid)

    async def rename_raid_thread(self, interaction: discord.Interaction, raid_id: int, new_name: str):
        """Rename the raid thread if the user is authorized and the raid is still active."""
        await interaction.response.defer(ephemeral=True)
        raid = await self.bot.db.fetchone("SELECT * FROM raids WHERE id = ?", (raid_id,))
        if not raid or not raid["is_active"]:
            return await interaction.followup.send("This raid is no longer active.", ephemeral=True)

        # Authorization: raid leader, officer, or admin
        if not await is_officer(interaction) and interaction.user.id != raid["leader_id"]:
            return await interaction.followup.send("You don't have permission to rename this thread.", ephemeral=True)

        thread = interaction.guild.get_thread(raid["thread_id"])
        if not thread:
            return await interaction.followup.send("Raid thread not found.", ephemeral=True)

        try:
            desired = self._format_raid_log_thread_name(interaction.guild, raid, new_name)
            await thread.edit(name=desired)
            await interaction.followup.send("Thread renamed successfully.", ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("Failed to rename the thread. Check my permissions.", ephemeral=True)

    async def _copy_thread_to_completed_channel(
        self,
        guild: discord.Guild,
        source_thread: discord.Thread,
        raid: dict,
        completed_channel: discord.TextChannel,
        desired_thread_name: str | None = None,
    ) -> discord.Thread | None:
        try:
            seed = await completed_channel.send("Raid log moved here: (creating thread...)")
            desired_name = self._format_raid_log_thread_name(
                guild,
                raid,
                desired_thread_name or source_thread.name,
            )
            dest_thread = await seed.create_thread(name=desired_name)
            try:
                await seed.edit(content=f"Raid log moved here: {dest_thread.mention}")
            except Exception:
                pass
        except Exception:
            logging.exception("Failed to create completed raid thread")
            return None

        export_cog = self.bot.get_cog("ExportCog")
        session = getattr(self.bot, "http_session", None)

        async for msg in source_thread.history(limit=None, oldest_first=True):
            raw_content = (getattr(msg, "content", None) or msg.clean_content or "")
            try:
                extracted = (
                    export_cog._extract_message_content(msg)  # type: ignore[attr-defined]
                    if export_cog is not None
                    else raw_content
                )
            except Exception:
                extracted = raw_content

            author_name = getattr(msg.author, "display_name", None) or getattr(msg.author, "name", None) or "Unknown"
            ts = msg.created_at.isoformat()
            is_bot = bool(getattr(msg.author, "bot", False))
            embeds = list(getattr(msg, "embeds", []) or [])

            # If the message contains embeds, avoid flattening embed content into
            # text because we will re-send the embed objects themselves.
            body_source = raw_content if embeds else extracted
            body = (body_source or "").strip()
            text = ""
            if is_bot or embeds:
                # For bot/embedded messages, prefer preserving the original look.
                # We cannot impersonate authors, but embeds retain most of the UI.
                text = body
            else:
                prefix = f"[{ts}] {author_name}:\n"
                text = (prefix + body).strip()

            if len(text) > 1900:
                text = text[:1900] + "..."

            attachments = list(getattr(msg, "attachments", []) or [])

            if not text and not attachments and not embeds:
                continue

            # Discord limits a single message to 10 attachments.
            batches = [attachments[i : i + 10] for i in range(0, len(attachments), 10)] or [[]]

            for idx, batch in enumerate(batches):
                files: list[discord.File] = []
                for a in batch:
                    if session is None:
                        continue
                    try:
                        async with session.get(a.url) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.read()
                        files.append(discord.File(io.BytesIO(data), filename=a.filename))
                    except Exception:
                        continue

                send_text = text if idx == 0 else ""
                send_embeds = embeds if idx == 0 else []

                if not send_text and not files and not send_embeds:
                    continue

                try:
                    await dest_thread.send(content=send_text or None, embeds=send_embeds or None, files=files)
                except Exception:
                    logging.exception("Failed to copy a message into completed raid thread")
                    continue

        try:
            await dest_thread.edit(locked=True)
        except Exception:
            logging.exception("Failed to lock completed raid thread")

        return dest_thread

    async def close_raid(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                pass

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is already closed or does not exist.", ephemeral=True)
        thread = interaction.channel
        # Deactivate raid in DB
        await self.bot.db.execute("UPDATE raids SET is_active = 0 WHERE id = ?", (raid['id'],))

        # Remove the raid announcement from the active raids channel so closed
        # raids do not linger (and don't become #unknown once the thread is deleted).
        try:
            config_for_announcement = await self.bot.db.get_guild_config(interaction.guild.id)
            active_channel_id = (
                config_for_announcement["raid_channel_id"]
                if config_for_announcement and "raid_channel_id" in config_for_announcement.keys()
                else None
            )
            announcement_message_id = None
            try:
                announcement_message_id = raid["announcement_message_id"]
            except Exception:
                announcement_message_id = None

            active_channel = (
                interaction.guild.get_channel(active_channel_id)
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
                    logging.exception("Failed to delete raid announcement message")

            # Backward compatibility: older raids may not have
            # announcement_message_id persisted. In that case, search recent bot
            # messages that mention this thread and delete the first match.
            if isinstance(active_channel, discord.TextChannel) and not isinstance(announcement_message_id, int):
                try:
                    bot_user = getattr(self.bot, "user", None)
                    needle = thread.mention
                    if bot_user is not None and needle:
                        async for msg in active_channel.history(limit=200, oldest_first=False):
                            if getattr(msg.author, "id", None) != getattr(bot_user, "id", None):
                                continue
                            if needle in (msg.content or ""):
                                try:
                                    await msg.delete()
                                except (discord.NotFound, discord.Forbidden):
                                    pass
                                except Exception:
                                    logging.exception("Failed to delete legacy raid announcement message")
                                break
                except Exception:
                    logging.exception("Failed while attempting legacy raid announcement cleanup")
        except Exception:
            logging.exception("Failed while attempting to remove raid announcement from active raids")

        # Remove raid leader role
        config = await self.bot.db.get_guild_config(interaction.guild.id)
        raid_leader_role_id = config['raid_leader_role_id'] if 'raid_leader_role_id' in config else None
        if raid_leader_role_id:
            raid_leader_role = interaction.guild.get_role(raid_leader_role_id)
            leader = interaction.guild.get_member(raid['leader_id'])
            if raid_leader_role and leader:
                try:
                    await leader.remove_roles(raid_leader_role, reason="Raid ended.")
                except discord.HTTPException:
                    pass # Ignore if user left or role is gone

        # Mark the raid log thread as closed and archive/lock it.
        try:
            await thread.send(f"Raid closed by {interaction.user.mention} at <t:{int(datetime.now().timestamp())}:F>. This thread is now locked.")
        except Exception:
            logging.exception("Failed to send raid closure message to thread")

        new_name = getattr(thread, "name", None)
        if isinstance(new_name, str) and "[closed]" not in new_name.lower():
            new_name = f"[Closed] {new_name}"

        try:
            if interaction.guild and isinstance(new_name, str):
                new_name = self._format_raid_log_thread_name(interaction.guild, raid, new_name)
        except Exception:
            pass

        completed_thread: discord.Thread | None = None
        config = await self.bot.db.get_guild_config(interaction.guild.id)
        completed_channel_id = (
            config["completed_raid_channel_id"]
            if config and "completed_raid_channel_id" in config
            else None
        )
        completed_channel: discord.TextChannel | None = None
        move_error: str | None = None

        if interaction.guild:
            if completed_channel_id:
                ch = interaction.guild.get_channel(completed_channel_id)
                if isinstance(ch, discord.TextChannel):
                    completed_channel = ch

            # If config wasn't set, fall back to finding a channel named
            # "completed-raids" and persist it for next time.
            if completed_channel is None:
                try:
                    for ch in interaction.guild.text_channels:
                        if (ch.name or "").lower() == "completed-raids":
                            completed_channel = ch
                            completed_channel_id = ch.id
                            try:
                                await self.bot.db.execute(
                                    "UPDATE guilds SET completed_raid_channel_id = ? WHERE guild_id = ?",
                                    (ch.id, interaction.guild.id),
                                )
                            except Exception:
                                logging.exception("Failed to persist completed_raid_channel_id")
                            break
                except Exception:
                    pass

        if completed_channel is not None and interaction.guild:
            try:
                bot_member = interaction.guild.me
                if bot_member is None and self.bot.user is not None:
                    bot_member = interaction.guild.get_member(self.bot.user.id)

                if bot_member is not None:
                    perms = completed_channel.permissions_for(bot_member)
                    missing: list[str] = []
                    if not perms.view_channel:
                        missing.append("View Channel")
                    if not perms.send_messages:
                        missing.append("Send Messages")
                    if not getattr(perms, "create_public_threads", False):
                        missing.append("Create Public Threads")
                    if not getattr(perms, "send_messages_in_threads", False):
                        missing.append("Send Messages in Threads")

                    if missing and move_error is None:
                        move_error = "Missing permissions in #completed-raids: " + ", ".join(missing)

                if move_error is None:
                    completed_thread = await self._copy_thread_to_completed_channel(
                        interaction.guild,
                        thread,
                        raid,
                        completed_channel,
                        desired_thread_name=new_name,
                    )

                if completed_thread is None and move_error is None:
                    move_error = (
                        "Could not create the completed raid thread. "
                        "Make sure I can Send Messages and Create Public Threads in #completed-raids."
                    )
            except Exception:
                logging.exception("Failed to move raid log to completed channel")
                move_error = "Failed to move raid log to the completed raids channel. Check my permissions there."
        elif interaction.guild:
            move_error = "Completed raids channel is not configured (or could not be found)."

        raid_id_for_log = None
        try:
            raid_id_for_log = raid["id"]
        except Exception:
            raid_id_for_log = None

        logging.info(
            "close_raid move_attempt guild_id=%s raid_id=%s completed_channel_id=%s completed_thread=%s move_error=%s",
            interaction.guild.id,
            raid_id_for_log,
            completed_channel_id,
            bool(completed_thread),
            move_error,
        )

        if move_error:
            try:
                await thread.send(f"Could not move raid log to completed raids. {move_error}")
            except Exception:
                pass

        if completed_thread is not None:
            try:
                await self.bot.db.execute(
                    "UPDATE raids SET thread_id = ? WHERE id = ?",
                    (completed_thread.id, raid["id"]),
                )
            except Exception:
                logging.exception("Failed to update raid thread_id after move to completed channel")

        original_deleted = False
        if completed_thread is not None and interaction.guild:
            try:
                await thread.delete()
                original_deleted = True
            except Exception:
                logging.exception("Failed to delete original raid thread after move")

        if not original_deleted:
            try:
                await thread.edit(name=new_name, archived=True, locked=True)
            except Exception:
                # If we cannot rename/archive the thread, the DB flag still marks
                # the raid as inactive.
                logging.exception("Failed to archive/rename raid thread")

        # Post a summary with a link in the completed raids channel
        if completed_channel_id and interaction.guild:
            completed_channel = interaction.guild.get_channel(completed_channel_id)
            if completed_channel:
                target_thread = completed_thread or thread
                embed = create_info_embed(
                    "Raid Completed",
                    f"Raid log thread: {target_thread.mention}\n"
                    f"Closed by: {interaction.user.mention} at <t:{int(datetime.now().timestamp())}:F>"
                )
                try:
                    await completed_channel.send(embed=embed)
                except Exception:
                    logging.exception("Failed to post raid completion summary to completed channel")

        # Send an explicit ephemeral confirmation to the user who closed the
        # raid so that any temporary "bot is thinking" message from the
        # deferred button interaction is replaced.
        try:
            if move_error:
                await interaction.followup.send(
                    f"Raid has been closed, but it was not moved to completed raids. {move_error}",
                    ephemeral=True,
                )
            elif completed_thread is not None:
                await interaction.followup.send(
                    f"Raid has been closed and moved to {completed_thread.mention}.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Raid has been closed and the raid log thread has been archived.",
                    ephemeral=True,
                )
        except discord.HTTPException:
            # If the interaction has expired or the followup webhook is gone,
            # the public log message above is still sufficient feedback.
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(RaidCog(bot))
