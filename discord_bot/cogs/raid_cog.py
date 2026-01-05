import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import logging
from ..utils import create_info_embed, create_error_embed, create_success_embed, is_officer, send_dkp_change_dm
from ..ui.views import RaidControlView
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

        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != raid["leader_id"] and not is_admin:
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
        is_admin = interaction.user.guild_permissions.administrator
        can_manage = is_leader or is_admin

        title = (
            f"Raid Control Panel for {interaction.user.display_name}"
            if can_manage
            else "Raid Panel"
        )
        description = (
            "Use the buttons below to manage your raid. This panel is only visible to you."
            if can_manage
            else "Use the buttons below to view your DKP and other raid info. This panel is only visible to you."
        )

        embed = create_info_embed(title, description)
        view = RaidControlView(self.bot, show_leader_buttons=can_manage)

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
        if not await is_officer(interaction):
            return await interaction.response.send_message(
                "You must be an officer to create a raid.",
                ephemeral=True,
            )

        config = await self.bot.db.get_guild_config(interaction.guild.id)
        if not config or not config["raid_channel_id"]:
            return await interaction.response.send_message(
                embed=create_error_embed(
                    "Setup Incomplete",
                    "The bot is not fully set up. Please ask an admin to re-invite the bot.",
                ),
                ephemeral=True,
            )

        active_raids_channel = interaction.guild.get_channel(config["raid_channel_id"])
        if not active_raids_channel:
            return await interaction.response.send_message(
                embed=create_error_embed(
                    "Setup Error",
                    "Required channels are missing. Please re-invite the bot.",
                ),
                ephemeral=True,
            )

        modal = RaidCreateModal(self)
        await interaction.response.send_modal(modal)

    async def create_raid_with_name(self, interaction: discord.Interaction, raid_name: str):
        """Actually create the raid using a provided raid name from the modal."""
        if not interaction.guild:
            return

        # Defer so we can safely do followup messages from modal submission
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        config = await self.bot.db.get_guild_config(interaction.guild.id)
        if not config or not config["raid_channel_id"]:
            return await interaction.followup.send(
                embed=create_error_embed(
                    "Setup Incomplete",
                    "The bot is not fully set up. Please ask an admin to re-invite the bot.",
                ),
                ephemeral=True,
            )

        # Use the raid leader's current voice channel as the raid VC instead of
        # creating or cloning a dedicated raid voice channel. This keeps the
        # bot from modifying the guild's channel structure and lets guilds
        # manage their own voice layout.
        leader_member = interaction.user if isinstance(interaction.user, discord.Member) else None
        leader_voice = getattr(leader_member, "voice", None)
        raid_vc = getattr(leader_voice, "channel", None)

        if not isinstance(raid_vc, discord.VoiceChannel):
            return await interaction.followup.send(
                embed=create_error_embed(
                    "No Voice Channel",
                    "You must be connected to a voice channel in this server to create a raid.",
                ),
                ephemeral=True,
            )

        active_raids_channel = interaction.guild.get_channel(config["raid_channel_id"])
        if not active_raids_channel:
            return await interaction.followup.send(
                embed=create_error_embed(
                    "Setup Error",
                    "Required channels are missing. Please re-invite the bot.",
                ),
                ephemeral=True,
            )

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
            thread_name = f"{raid_name} - Raid Log - {user_display}"
            thread = await raid_message.create_thread(name=thread_name)
            await self.bot.db.execute(
                "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id) VALUES (?, ?, ?, ?)",
                (interaction.guild.id, interaction.user.id, raid_vc.id, thread.id),
            )

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

            # First control panel is public in the raid log thread
            control_embed = create_info_embed(
                f"Raid Control Panel for {interaction.user.display_name}",
                "Use the buttons below to manage your raid.",
            )
            view = RaidControlView(self.bot)
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
    @app_commands.checks.has_permissions(administrator=True)
    async def raid_create_cmd(self, interaction: discord.Interaction):
        await self.create_raid_from_interaction(interaction)

    @app_commands.command(name="raid_end", description="Ends and closes the current raid.")
    async def raid_end_cmd(self, interaction: discord.Interaction):
        if not await is_officer(interaction):
            return await interaction.response.send_message("You must be an officer or admin to end a raid.", ephemeral=True)
        await self.close_raid(interaction)

    @app_commands.command(name="raid_add_member", description="Admin only: add a member to the current raid without requiring them to be in the voice channel.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="The member to add as a participant in this raid.")
    async def raid_add_member_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )

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

        await interaction.response.send_message(
            f"{member.mention} has been added to this raid. They can now receive DKP adjustments and participate as a raid member even if they are not in the voice channel.",
            ephemeral=True,
        )

    async def member_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        raid = await self.bot.db.get_raid_by_thread(interaction.channel_id)
        if not raid or not interaction.guild:
            return []

        vc = interaction.guild.get_channel(raid["vc_id"])
        members_by_id: dict[int, discord.Member] = {}

        for m in getattr(vc, "members", []):
            if not getattr(m, "bot", False):
                members_by_id[m.id] = m

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
        if not await is_officer(interaction):
            return await interaction.response.send_message("You must be an officer to use this command.", ephemeral=True)
        target_member = await self._get_member_from_str(interaction, member)
        modal = DKPAdjustmentModal(action="Award", raid_cog=self, member=target_member)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="deduct", description="Deduct DKP from a member or the entire raid.")
    @app_commands.autocomplete(member=member_autocomplete)
    @app_commands.describe(member="(Optional) The member to deduct DKP from. Leave blank to deduct from the entire raid.")
    async def deduct_cmd(self, interaction: discord.Interaction, member: str | None = None):
        if not await is_officer(interaction):
            return await interaction.response.send_message("You must be an officer to use this command.", ephemeral=True)
        target_member = await self._get_member_from_str(interaction, member)
        modal = DKPAdjustmentModal(action="Deduct", raid_cog=self, member=target_member)
        await interaction.response.send_modal(modal)

    async def _get_member_from_str(self, interaction: discord.Interaction, member_str: str | None) -> discord.Member | None:
        if not member_str:
            return None
        try:
            member_id = int(member_str)
            return interaction.guild.get_member(member_id)
        except (ValueError, TypeError):
            return None

    async def update_team_list(self, interaction: discord.Interaction):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)
        vc = interaction.guild.get_channel(raid['vc_id']) if interaction.guild else None

        # Build the raid team from both the current voice channel (if any)
        # and the raid_members table so manually added members are included
        # even when the VC is empty or has been cleaned up.
        members_by_id: dict[int, discord.Member] = {}

        if isinstance(vc, discord.VoiceChannel):
            for m in getattr(vc, "members", []):
                if not m.bot:
                    members_by_id[m.id] = m

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

        is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator

        if amount > MAX_DKP_ADJUSTMENT and not is_admin:
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

        vc = interaction.guild.get_channel(raid["vc_id"]) if interaction.guild else None

        if member is None:
            # Mass adjustment: include all non-bot members currently in the
            # raid voice channel plus any non-bot guild members recorded in
            # the raid_members table for this raid.
            targets_by_id: dict[int, discord.Member] = {}

            if isinstance(vc, discord.VoiceChannel):
                for m in getattr(vc, "members", []):
                    if not m.bot:
                        targets_by_id[m.id] = m

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

            in_vc = member in getattr(vc, "members", [])
            raid_member_ids = set()
            try:
                member_rows = await self.bot.db.get_raid_members(raid["id"])
                raid_member_ids = {row["user_id"] for row in member_rows}
            except Exception:
                raid_member_ids = set()

            if not in_vc and member.id not in raid_member_ids:
                await interaction.followup.send(
                    embed=create_error_embed(
                        "Invalid Target",
                        "DKP can only be adjusted for members in the raid voice channel or those who have been added as raid participants.",
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
        else:
            description = (
                f"**{abs(amount)} DKP** {action_word.lower()} to **{len(targets)}** players for: *{reason}*."
            )

        embed = create_success_embed(
            f"DKP {action_word}!",
            description,
        )
        await interaction.followup.send(embed=embed)

        await self.maybe_send_control_panel_ephemeral(interaction, raid=raid)
    async def close_raid(self, interaction: discord.Interaction):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is already closed or does not exist.", ephemeral=True)
        thread = interaction.channel
        # Deactivate raid in DB
        await self.bot.db.execute("UPDATE raids SET is_active = 0 WHERE id = ?", (raid['id'],))

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

        # Mark the raid log thread as closed and archive/lock it. The
        # associated voice channel is left untouched so guilds can continue to
        # manage their own channel layout.
        try:
            await thread.send(f"Raid closed by {interaction.user.mention} at <t:{int(datetime.now().timestamp())}:F>. This thread is now locked.")
        except Exception:
            pass

        new_name = getattr(thread, "name", None)
        if isinstance(new_name, str) and "[closed]" not in new_name.lower():
            new_name = f"[Closed] {new_name}"

        try:
            await thread.edit(name=new_name, archived=True, locked=True)
        except Exception:
            # If we cannot rename/archive the thread, the DB flag still marks
            # the raid as inactive.
            pass

        # Send an explicit ephemeral confirmation to the user who closed the
        # raid so that any temporary "bot is thinking" message from the
        # deferred button interaction is replaced.
        try:
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
