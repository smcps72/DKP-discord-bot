import discord
import logging
from .modals import DKPAdjustmentModal, AuctionStartModal, BidModal, RaidRulesModal
from discord.ui import UserSelect, Select
from ..utils import is_admin, is_officer, ensure_allowed_guild

class MemberSelect(Select):
    def __init__(self, bot, action: str, members: list[discord.Member]):
        self.bot = bot
        self.action = action
        # Track which members are currently in the raid voice channel so we can
        # enforce that only active raiders are selected, while still allowing
        # Discord's built-in type-to-search user picker.
        self._allowed_member_ids = {m.id for m in members}

        options = [
            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
            for m in members
        ][:25]

        super().__init__(
            placeholder=f"Select a member to {action.lower()} DKP...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        raid_cog = self.bot.get_cog("RaidCog")

        # Resolve the selected member from the stored user ID value.
        member: discord.Member | None = None
        if interaction.guild:
            try:
                selected_id = int(self.values[0])
            except (ValueError, TypeError):
                member = None
            else:
                member = interaction.guild.get_member(selected_id)

        if not member or member.id not in self._allowed_member_ids:
            await interaction.response.send_message(
                "That member is not an eligible raid member.",
                ephemeral=True,
            )
            return

        modal = DKPAdjustmentModal(
            action=self.action,
            raid_cog=raid_cog,
            member=member,
            source="raid_panel",
        )
        await interaction.response.send_modal(modal)


class DKPAdjustmentView(discord.ui.View):
    def __init__(self, bot, action: str, members: list[discord.Member]):
        super().__init__(timeout=180)
        self.bot = bot
        self.action = action
        self.add_item(MemberSelect(bot, action, members))

    @discord.ui.button(label="All Raid Members", style=discord.ButtonStyle.primary)
    async def all_in_vc(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        modal = DKPAdjustmentModal(
            action=self.action,
            raid_cog=raid_cog,
            member=None,
            source="raid_panel",
        )
        await interaction.response.send_modal(modal)


class WelcomeView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_allowed_guild(interaction)

    @discord.ui.button(label="Create Raid 🏰", style=discord.ButtonStyle.success, custom_id="welcome_create_raid")
    async def create_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            await raid_cog.create_raid_from_interaction(interaction)
        else:
            # If the cog isn't loaded, we still need to respond to the interaction.
            await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)

    @discord.ui.button(label="My DKP 💰", style=discord.ButtonStyle.secondary, custom_id="welcome_my_dkp")
    async def my_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_my_dkp(interaction)
        else:
            await interaction.followup.send("User module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Auction Help ❓", style=discord.ButtonStyle.primary, custom_id="welcome_auction_help")
    async def auction_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_auction_help(interaction)
        else:
            await interaction.followup.send("User module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Bot Status 📈", style=discord.ButtonStyle.secondary, custom_id="welcome_bot_status")
    async def bot_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        admin_cog = self.bot.get_cog("AdminCog")
        if admin_cog:
            embed = await admin_cog._create_status_embed(interaction.guild.id)
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("Admin module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Admin Panel ⚙️", style=discord.ButtonStyle.danger, custom_id="welcome_admin_panel")
    async def admin_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not await is_admin(interaction):
            return await interaction.followup.send("You must be a bot admin to use this.", ephemeral=True)

        view = AdminPanelView(self.bot)
        await interaction.followup.send("Welcome to the Admin Panel.", view=view, ephemeral=True)


# -- ADMIN VIEWS --


async def send_admin_confirmation(
    interaction: discord.Interaction,
    panel_text: str,
    ephemeral_text: str,
):
    """Small helper to keep admin confirmations consistent.

    Edits the original admin panel message with a tiny confirmation line
    and sends a separate ephemeral confirmation to the acting user.
    """
    await interaction.response.edit_message(
        content=panel_text,
        view=None,
    )
    await interaction.followup.send(
        ephemeral_text,
        ephemeral=True,
    )


class OfficerRoleSelect(discord.ui.Select):
    def __init__(self, bot: discord.Client):
        self.bot = bot

        options: list[discord.SelectOption] = []
        # The guild will be available on the interaction, not here, so we
        # build a placeholder; options are filled dynamically in callback
        # using interaction.guild.roles. Discord requires at least 1 option,
        # so we start with a dummy that will be replaced.
        options.append(discord.SelectOption(label="Loading roles...", value="dummy"))

        super().__init__(
            placeholder="Select an existing role to use as Officers",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        # If this is still the dummy option, rebuild options from guild roles
        if self.values[0] == "dummy":
            roles = [
                r for r in interaction.guild.roles
                if not r.is_default() and not r.managed
            ]
            # Sort roles alphabetically by name
            roles.sort(key=lambda role: role.name.lower())
            options = [
                discord.SelectOption(label=role.name[:100], value=str(role.id))
                for role in roles[:25]
            ]
            if not options:
                return await interaction.response.edit_message(
                    content="No configurable roles found. Please create a role in Server Settings first.",
                    view=None,
                )

            self.options = options
            # Ask the user to pick again now that real options are loaded.
            return await interaction.response.edit_message(
                content="Select an existing role to use as the Officers role:",
                view=self.view,
            )

        role_id = int(self.values[0])
        role = interaction.guild.get_role(role_id)
        if not role:
            return await interaction.response.edit_message(
                content="The selected role could not be found. Please try again.",
                view=self.view,
            )

        admin_cog = self.view.bot.get_cog("AdminCog") if hasattr(self.view, "bot") else None
        if not admin_cog:
            return await interaction.response.edit_message(
                content="Admin module is currently offline. Please try again later.",
                view=None,
            )

        # Delegate persistence to the existing AdminCog.set_role helper.
        await admin_cog.set_role(interaction, "Officer", role)

        # Use shared helper so all admin confirmations look and behave
        # the same across the panel.
        await send_admin_confirmation(
            interaction,
            panel_text=f"Officers role set to {role.mention}.",
            ephemeral_text=f"Officer role has been updated to {role.mention}.",
        )


class OfficerRoleAssignView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot
        self.add_item(OfficerRoleSelect(bot))


class AdminRoleSelect(discord.ui.Select):
    def __init__(self, bot: discord.Client):
        self.bot = bot

        options: list[discord.SelectOption] = []
        options.append(discord.SelectOption(label="Loading roles...", value="dummy"))

        super().__init__(
            placeholder="Select an existing role to use as Bot Admins",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "dummy":
            roles = [
                r for r in interaction.guild.roles
                if not r.is_default() and not r.managed
            ]
            # Sort roles alphabetically by name
            roles.sort(key=lambda role: role.name.lower())
            options = [
                discord.SelectOption(label=role.name[:100], value=str(role.id))
                for role in roles[:25]
            ]
            if not options:
                return await interaction.response.edit_message(
                    content="No configurable roles found. Please create a role in Server Settings first.",
                    view=None,
                )

            self.options = options
            return await interaction.response.edit_message(
                content="Select an existing role to use as the Bot Admin role:",
                view=self.view,
            )

        role_id = int(self.values[0])
        role = interaction.guild.get_role(role_id)
        if not role:
            return await interaction.response.edit_message(
                content="The selected role could not be found. Please try again.",
                view=self.view,
            )

        admin_cog = self.view.bot.get_cog("AdminCog") if hasattr(self.view, "bot") else None
        if not admin_cog:
            return await interaction.response.edit_message(
                content="Admin module is currently offline. Please try again later.",
                view=None,
            )

        await admin_cog.set_role(interaction, "Admin", role)

        await send_admin_confirmation(
            interaction,
            panel_text=f"Bot Admin role set to {role.mention}.",
            ephemeral_text=f"Bot Admin role has been updated to {role.mention}.",
        )


class AdminRoleAssignView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot
        self.add_item(AdminRoleSelect(bot))


class AdminPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await ensure_allowed_guild(interaction):
            return False
        if not await is_admin(interaction):
            await interaction.response.send_message("You must be a bot admin to use this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Assign Bot Admin Role", style=discord.ButtonStyle.primary, row=0)
    async def assign_bot_admin_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AdminRoleAssignView(self.bot)

        roles = [
            r for r in interaction.guild.roles
            if not r.is_default() and not r.managed
        ]

        select: AdminRoleSelect | None = None
        for child in view.children:
            if isinstance(child, AdminRoleSelect):
                select = child
                break

        if select:
            # Sort roles alphabetically by name
            roles.sort(key=lambda role: role.name.lower())
            options = [
                discord.SelectOption(label=role.name[:100], value=str(role.id))
                for role in roles[:25]
            ]
            if options:
                select.options = options
            else:
                return await interaction.response.send_message(
                    "No configurable roles found. Please create a role in Server Settings first.",
                    ephemeral=True,
                )

        await interaction.response.edit_message(
            content="Select an existing role to use as the Bot Admin role:",
            view=view,
        )

    @discord.ui.button(label="Assign Officers Role Name", style=discord.ButtonStyle.primary, row=1)
    async def assign_officers_role_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = OfficerRoleAssignView(self.bot)

        # Build initial options list from existing guild roles.
        roles = [
            r for r in interaction.guild.roles
            if not r.is_default() and not r.managed
        ]
        select: OfficerRoleSelect | None = None
        for child in view.children:
            if isinstance(child, OfficerRoleSelect):
                select = child
                break

        if select:
            # Sort roles alphabetically by name
            roles.sort(key=lambda role: role.name.lower())
            options = [
                discord.SelectOption(label=role.name[:100], value=str(role.id))
                for role in roles[:25]
            ]
            if options:
                select.options = options
            else:
                # No roles available; send a simple message instead.
                return await interaction.response.send_message(
                    "No configurable roles found. Please create a role in Server Settings first.",
                    ephemeral=True,
                )

        await interaction.response.edit_message(
            content="Select an existing role to use as the Officers role:",
            view=view,
        )


class RaidControlView(discord.ui.View):
    def __init__(self, bot, show_leader_buttons: bool = True):
        super().__init__(timeout=None)
        self.bot = bot

        # Optionally hide leader-only controls for raiders in ephemeral panels.
        # The public thread panel can still show all buttons while access is
        # enforced via interaction_check.
        self.show_leader_buttons = show_leader_buttons
        if not self.show_leader_buttons:
            leader_only_ids = {
                "raid_award_dkp",
                "raid_deduct_dkp",
                "raid_update_team",
                "raid_start_auction",
                "raid_end_auction",
                "raid_close_raid",
            }
            to_remove: list[discord.ui.Item] = []
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.custom_id in leader_only_ids:
                    to_remove.append(child)
            for child in to_remove:
                self.remove_item(child)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await ensure_allowed_guild(interaction):
            return False
        # On bot startup, interaction_check can be called with a mock interaction
        # that has no channel. We return False to prevent errors.
        if not interaction.channel:
            return False

        # Determine which button was pressed, if any.
        custom_id = None
        if getattr(interaction, "data", None) and isinstance(interaction.data, dict):
            custom_id = interaction.data.get("custom_id")

        # Defer most interactions immediately to prevent timeouts.
        # IMPORTANT: Do NOT defer for buttons that will open a modal, since
        # modals must be sent via the initial interaction response.
        if interaction.type != discord.InteractionType.modal_submit and custom_id not in (
            "raid_add_rule",
            "raid_start_auction",
            "raid_rename_thread",
        ):
            # Only defer if the interaction hasn't already been acknowledged
            # by another handler (e.g., a command or previous callback).
            if not interaction.response.is_done():
                # "Update Team" should be a public message so raiders can see
                # the current team list. Defer non-ephemerally for that button
                # while keeping other raid controls ephemeral.
                ephemeral = custom_id != "raid_update_team"
                try:
                    await interaction.response.defer(ephemeral=ephemeral)
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                    # Already responded to, expired, or otherwise invalid; safe to ignore.
                    pass

        # Allow everyone to use the raid "My DKP" button and view rules.
        if custom_id in ("raid_my_dkp", "raid_view_rules", "raid_join_raid", "raid_leave_raid"):
            return True

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)

        admin_ok = await is_admin(interaction)
        if raid and (interaction.user.id == raid['leader_id'] or admin_ok):
            return True

        if custom_id == "raid_rename_thread" and raid and await is_officer(interaction):
            return True

        # User is not the raid leader. If we haven't responded yet, send an
        # ephemeral error via the initial interaction response; otherwise use
        # a followup. This avoids generic interaction failures on buttons
        # like "Start Auction" that haven't been deferred yet.
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "You must be the raid leader or a bot admin to use this control.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "You must be the raid leader or a bot admin to use this control.",
                    ephemeral=True,
                )
        except discord.HTTPException:
            # Interaction may have expired or otherwise failed; ignore.
            pass

        return False

    @discord.ui.button(label="Join Raid", style=discord.ButtonStyle.success, custom_id="raid_join_raid", row=0)
    async def join_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        if getattr(interaction.user, "bot", False):
            return await interaction.followup.send("Bots cannot join raids.", ephemeral=True)

        raid_id = int(raid["id"])
        user_id = int(interaction.user.id)

        try:
            if await self.bot.db.is_raid_member(raid_id, user_id):
                return await interaction.followup.send("You are already part of this raid.", ephemeral=True)
        except Exception:
            pass

        admin_ok = await is_admin(interaction)
        if user_id == int(raid["leader_id"]) or admin_ok:
            try:
                inserted = await self.bot.db.add_raid_member(raid_id, user_id)
            except Exception:
                inserted = False
            if not inserted:
                return await interaction.followup.send("You are already part of this raid.", ephemeral=True)
            try:
                if isinstance(interaction.channel, discord.Thread):
                    await interaction.channel.send(f"{interaction.user.mention} joined the raid.")
            except Exception:
                logging.exception("Failed to send join message to raid thread")
            return await interaction.followup.send("You have been added to the raid.", ephemeral=True)

        try:
            existing = await self.bot.db.get_raid_join_request(raid_id, user_id)
        except Exception:
            existing = None
        if existing is not None:
            try:
                if str(existing["status"]) == "pending":
                    return await interaction.followup.send(
                        "Your join request is already pending approval.",
                        ephemeral=True,
                    )
            except Exception:
                pass

        try:
            await self.bot.db.upsert_raid_join_request(raid_id, user_id, source="button")
        except Exception:
            return await interaction.followup.send(
                "Failed to submit join request. Please try again.",
                ephemeral=True,
            )

        leader_id = int(raid["leader_id"])
        leader_mention = f"<@{leader_id}>"
        if interaction.guild:
            leader_member = interaction.guild.get_member(leader_id)
            if leader_member:
                leader_mention = leader_member.mention

        try:
            if isinstance(interaction.channel, discord.Thread):
                # Send the approval request as a DM to the raid leader only
                leader_member = interaction.guild.get_member(leader_id)
                if leader_member:
                    try:
                        await leader_member.send(
                            f"Join request from {interaction.user.mention} for raid in {interaction.channel.mention}. Approve?",
                            view=RaidJoinApprovalView(self.bot, raid_id, user_id),
                        )
                    except discord.Forbidden:
                        # If DMs are disabled, send in thread but the view will handle authorization
                        await interaction.channel.send(
                            f"{leader_mention} approve join request from {interaction.user.mention}?",
                            view=RaidJoinApprovalView(self.bot, raid_id, user_id),
                        )
                else:
                    # Leader not found, fall back to thread message
                    await interaction.channel.send(
                        f"{leader_mention} approve join request from {interaction.user.mention}?",
                        view=RaidJoinApprovalView(self.bot, raid_id, user_id),
                    )
        except Exception:
            logging.exception("Failed to send join approval request")

        return await interaction.followup.send(
            "Join request sent to the raid leader for approval.",
            ephemeral=True,
        )

    @discord.ui.button(label="My DKP 💰", style=discord.ButtonStyle.secondary, custom_id="raid_my_dkp", row=0)
    async def raid_my_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_my_dkp(interaction)
        else:
            await interaction.followup.send("User module is currently offline.", ephemeral=True)

    async def _show_dkp_adjustment_view(self, interaction: discord.Interaction, action: str):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)

        members_by_id: dict[int, discord.Member] = {}

        try:
            member_rows = await self.bot.db.get_raid_members(raid["id"])
        except Exception:
            member_rows = []

        for row in member_rows:
            # sqlite/aiosqlite rows support dict-style access but not .get()
            user_id = row["user_id"]
            if user_id in members_by_id:
                continue
            gm = interaction.guild.get_member(user_id) if interaction.guild else None
            if gm and not gm.bot:
                members_by_id[user_id] = gm

        members = list(members_by_id.values())
        if not members:
            return await interaction.followup.send(
                "No eligible raid members were found. If you are in a voice channel, click \"Update Team\" to add all members in your voice channel to the raid. Or each member can click the \"Join Raid\" button.",
                ephemeral=True,
            )

        view = DKPAdjustmentView(self.bot, action, members)
        await interaction.followup.send(f"Who do you want to {action.lower()} DKP?", view=view, ephemeral=True)

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            try:
                await raid_cog.maybe_send_control_panel_ephemeral(interaction, raid=raid)
            except Exception:
                logging.exception("Failed to re-show control panel after award DKP")

    @discord.ui.button(label="Award DKP", style=discord.ButtonStyle.success, custom_id="raid_award_dkp", row=0)
    async def award_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_dkp_adjustment_view(interaction, "Award")

    @discord.ui.button(label="Deduct DKP", style=discord.ButtonStyle.danger, custom_id="raid_deduct_dkp", row=0)
    async def deduct_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_dkp_adjustment_view(interaction, "Deduct")

    @discord.ui.button(label="Start Auction 💎", style=discord.ButtonStyle.primary, custom_id="raid_start_auction", row=1)
    async def start_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Before opening the auction modal, ensure this is an active raid
        # thread and that there is at least one raid participant (either in
        # the raid voice channel or recorded in raid_members).
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message(
                "This is not an active raid thread.",
                ephemeral=True,
            )

        participants: set[int] = set()

        try:
            member_rows = await self.bot.db.get_raid_members(raid["id"])
        except Exception:
            member_rows = []

        for row in member_rows:
            try:
                uid = int(row["user_id"])
            except (KeyError, TypeError, ValueError):
                continue
            participants.add(uid)

        if not participants:
            return await interaction.response.send_message(
                "No eligible raid members were found. If you are in a voice channel, click \"Update Team\" to add all members in your voice channel to the raid. Or each member can click the \"Join Raid\" button. Cannot start auction.",
                ephemeral=True,
            )

        # Also block if an auction is already active for this raid so the
        # leader sees the error immediately instead of only after submitting
        # the modal.
        active_auction = await self.bot.db.get_active_auction(raid["id"])
        if active_auction:
            return await interaction.response.send_message(
                "An auction is already in progress for this raid.",
                ephemeral=True,
            )

        auction_cog = self.bot.get_cog("AuctionCog")
        modal = AuctionStartModal(auction_cog=auction_cog)
        try:
            await interaction.response.send_modal(modal)
        except (discord.InteractionResponded, discord.NotFound):
            try:
                await interaction.followup.send(
                    "This interaction has expired or already received a response. Please try again.",
                    ephemeral=True,
                )
            except Exception:
                logging.exception("Failed to send expired interaction message")  # Fully expired, ignore
        except discord.HTTPException:
            # Optionally log or handle other HTTP errors
            pass

    @discord.ui.button(label="🔄 Update Team", style=discord.ButtonStyle.secondary, custom_id="raid_update_team", row=2)
    async def update_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        await raid_cog.update_team_from_voice_channel(interaction)

    @discord.ui.button(label="End Auction", style=discord.ButtonStyle.primary, custom_id="raid_end_auction", row=1)
    async def end_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        auction_cog = self.bot.get_cog("AuctionCog")
        await auction_cog.end_auction_from_button(interaction)

    @discord.ui.button(label="Close Raid ", style=discord.ButtonStyle.danger, custom_id="raid_close_raid", row=1)
    async def close_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        await raid_cog.close_raid(interaction)

    @discord.ui.button(label="Leave Raid", style=discord.ButtonStyle.secondary, custom_id="raid_leave_raid", row=0)
    async def leave_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        if getattr(interaction.user, "bot", False):
            return await interaction.followup.send("Bots cannot leave raids.", ephemeral=True)

        raid_id = int(raid["id"])
        user_id = int(interaction.user.id)

        try:
            removed = await self.bot.db.remove_raid_member(raid_id, user_id)
        except Exception:
            removed = False

        try:
            await self.bot.db.delete_raid_join_request(raid_id, user_id)
        except Exception:
            pass

        if not removed:
            return await interaction.followup.send("You are not part of this raid.", ephemeral=True)

        return await interaction.followup.send("You have left the raid.", ephemeral=True)

    @discord.ui.button(label="Rename Thread", style=discord.ButtonStyle.secondary, custom_id="raid_rename_thread", row=1)
    async def rename_thread(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open a modal to rename the raid thread (raid leaders/officers only)."""
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            if not interaction.response.is_done():
                return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        # Authorization check: raid leader, officer, or admin
        if not await is_officer(interaction) and interaction.user.id != raid["leader_id"]:
            if not interaction.response.is_done():
                return await interaction.response.send_message(
                    "You don't have permission to rename this thread.",
                    ephemeral=True,
                )
            return await interaction.followup.send("You don't have permission to rename this thread.", ephemeral=True)

        from ..ui.modals import ThreadRenameModal
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            if not interaction.response.is_done():
                return await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        modal = ThreadRenameModal(raid_cog=raid_cog, raid_id=raid["id"])
        try:
            await interaction.response.send_modal(modal)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            try:
                await interaction.followup.send("Please try again.", ephemeral=True)
            except Exception:
                pass

    # The View Rules button is temporarily disabled. To re-enable in the future,
    # uncomment the decorator and method below.
    # @discord.ui.button(label="View Rules \ud83d\udcdd", style=discord.ButtonStyle.secondary, custom_id="raid_view_rules", row=2)
    # async def raid_view_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
    #     if not raid:
    #         return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)
    #
    #     try:
    #         rules = raid["rules"]
    #     except (KeyError, TypeError):
    #         rules = None
    #
    #     if not rules:
    #         msg = "No rules have been set for this raid yet."
    #     else:
    #         msg = f"**Raid Rules:**\n{rules}"
    #
    #     await interaction.followup.send(msg, ephemeral=True)

    # The Add Rule button is temporarily disabled. To re-enable in the future,
    # uncomment the decorator and method below.
    # @discord.ui.button(label="Add Rule \u270f\ufe0f", style=discord.ButtonStyle.primary, custom_id="raid_add_rule", row=2)
    # async def raid_add_rule(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
    #     if not raid:
    #         return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)


class RaidJoinApprovalView(discord.ui.View):
    def __init__(self, bot, raid_id: int, user_id: int):
        super().__init__(timeout=3600)
        self.bot = bot
        self.raid_id = int(raid_id)
        self.user_id = int(user_id)

    async def _get_raid_row(self):
        return await self.bot.db.fetchone(
            "SELECT id, leader_id, is_active, thread_id FROM raids WHERE id = ?",
            (self.raid_id,),
        )

    async def _authorize(self, interaction: discord.Interaction, raid_row) -> bool:
        if raid_row is None:
            await interaction.response.send_message("This raid was not found.", ephemeral=True)
            return False
        try:
            if int(raid_row["is_active"]) != 1:
                await interaction.response.send_message("This raid is no longer active.", ephemeral=True)
                return False
        except Exception:
            await interaction.response.send_message("This raid is no longer active.", ephemeral=True)
            return False

        admin_ok = await is_admin(interaction)
        if int(interaction.user.id) != int(raid_row["leader_id"]) and not admin_ok:
            await interaction.response.send_message(
                "Only the raid leader (or a bot admin) can approve join requests.",
                ephemeral=True,
            )
            return False

        return True

    async def _finalize(self, interaction: discord.Interaction):
        try:
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            msg = getattr(interaction, "message", None)
            if msg:
                await msg.edit(view=self)
        except Exception:
            pass

    async def _ensure_pending(self, interaction: discord.Interaction) -> bool:
        req = await self.bot.db.get_raid_join_request(self.raid_id, self.user_id)
        if req is None:
            await interaction.response.send_message("This join request no longer exists.", ephemeral=True)
            await self._finalize(interaction)
            return False
        try:
            if str(req["status"]) != "pending":
                await interaction.response.send_message("This join request is no longer pending.", ephemeral=True)
                await self._finalize(interaction)
                return False
        except Exception:
            await interaction.response.send_message("This join request is no longer pending.", ephemeral=True)
            await self._finalize(interaction)
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_row = await self._get_raid_row()
        if not await self._authorize(interaction, raid_row):
            return
        if not await self._ensure_pending(interaction):
            return

        try:
            inserted = await self.bot.db.add_raid_member(self.raid_id, self.user_id)
        except Exception:
            inserted = False

        await self.bot.db.set_raid_join_request_status(
            self.raid_id,
            self.user_id,
            "approved",
            decided_by=int(interaction.user.id),
        )

        try:
            # Send approval result to the raid thread
            raid_row = await self._get_raid_row()
            if raid_row:
                # Get the thread ID from the raids table
                thread_id = raid_row.get("thread_id")
                if thread_id and interaction.guild:
                    thread = interaction.guild.get_thread(thread_id)
                    if thread:
                        member = interaction.guild.get_member(self.user_id)
                        mention = member.mention if member else f"<@{self.user_id}>"
                        if inserted:
                            await thread.send(f"{mention} joined the raid.")
                        else:
                            await thread.send(f"{mention} is already part of the raid.")
        except Exception:
            logging.exception("Failed to send approval result to raid thread")

        await interaction.response.send_message("Approved.", ephemeral=True)
        await self._finalize(interaction)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_row = await self._get_raid_row()
        if not await self._authorize(interaction, raid_row):
            return
        if not await self._ensure_pending(interaction):
            return

        await self.bot.db.set_raid_join_request_status(
            self.raid_id,
            self.user_id,
            "denied",
            decided_by=int(interaction.user.id),
        )

        try:
            # Send denial result to the raid thread
            raid_row = await self._get_raid_row()
            if raid_row:
                # Get the thread ID from the raids table
                thread_id = raid_row.get("thread_id")
                if thread_id and interaction.guild:
                    thread = interaction.guild.get_thread(thread_id)
                    if thread:
                        member = interaction.guild.get_member(self.user_id)
                        mention = member.mention if member else f"<@{self.user_id}>"
                        await thread.send(f"Join request denied for {mention}.")
        except Exception:
            logging.exception("Failed to send denial result to raid thread")

        await interaction.response.send_message("Denied.", ephemeral=True)
        await self._finalize(interaction)

class AuctionBidView(discord.ui.View):
    def __init__(self, bot, auction_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.auction_id = auction_id

    @discord.ui.button(label="Bid", style=discord.ButtonStyle.success, custom_id="auction_bid")
    async def bid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_allowed_guild(interaction):
            return
        auction_cog = self.bot.get_cog("AuctionCog")
        modal = BidModal(auction_cog=auction_cog, auction_id=self.auction_id)
        await interaction.response.send_modal(modal)


class AuctionOpenPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Open Bid Panel", style=discord.ButtonStyle.primary, custom_id="auction_open_panel")
    async def open_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_allowed_guild(interaction):
            return
        auction_cog = self.bot.get_cog("AuctionCog")
        if not auction_cog:
            return await interaction.response.send_message("Auction module is currently offline.", ephemeral=True)

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                pass
        msg = getattr(interaction, "message", None)
        msg_id = getattr(msg, "id", None)
        if not msg_id:
            return await interaction.followup.send("Could not resolve this auction message.", ephemeral=True)

        auction = await self.bot.db.fetchone(
            "SELECT id FROM auctions WHERE message_id = ? AND is_active = 1",
            (int(msg_id),),
        )
        if not auction:
            return await interaction.followup.send("This auction has ended.", ephemeral=True)

        await auction_cog.send_bid_panel(interaction, int(auction["id"]))
