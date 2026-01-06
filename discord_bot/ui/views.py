import discord
from .modals import DKPAdjustmentModal, AuctionStartModal, BidModal, RaidRulesModal
from discord.ui import UserSelect, Select
from ..utils import is_admin, ensure_allowed_guild
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
                "That member is not currently in the raid voice channel.",
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
            return await interaction.followup.send("You must be a server admin to use this.", ephemeral=True)

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


class AdminPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await ensure_allowed_guild(interaction):
            return False
        if not await is_admin(interaction):
            await interaction.response.send_message("You must be a server admin to use this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Assign Officers Role Name", style=discord.ButtonStyle.primary, row=0)
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
                "raid_update_team",
                "raid_award_dkp",
                "raid_deduct_dkp",
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
        if interaction.type != discord.InteractionType.modal_submit and custom_id not in ("raid_add_rule", "raid_start_auction"):
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
        if custom_id in ("raid_my_dkp", "raid_view_rules"):
            return True

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)

        is_admin = (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.administrator
        )
        if raid and (interaction.user.id == raid['leader_id'] or is_admin):
            return True

        # User is not the raid leader. If we haven't responded yet, send an
        # ephemeral error via the initial interaction response; otherwise use
        # a followup. This avoids generic interaction failures on buttons
        # like "Start Auction" that haven't been deferred yet.
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "You must be the raid leader or a server admin to use this control.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "You must be the raid leader or a server admin to use this control.",
                    ephemeral=True,
                )
        except discord.HTTPException:
            # Interaction may have expired or otherwise failed; ignore.
            pass

        return False

    @discord.ui.button(label="Update Team", style=discord.ButtonStyle.secondary, custom_id="raid_update_team", row=0)
    async def update_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        await raid_cog.update_team_list(interaction)

    async def _show_dkp_adjustment_view(self, interaction: discord.Interaction, action: str):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)

        vc = interaction.guild.get_channel(raid['vc_id']) if interaction.guild else None
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
            # sqlite/aiosqlite rows support dict-style access but not .get()
            user_id = row["user_id"]
            if user_id in members_by_id:
                continue
            gm = interaction.guild.get_member(user_id) if interaction.guild else None
            if gm and not gm.bot:
                members_by_id[user_id] = gm

        members = list(members_by_id.values())
        if not members:
            return await interaction.followup.send("No eligible raid members were found.", ephemeral=True)

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

        vc = interaction.guild.get_channel(raid["vc_id"]) if interaction.guild else None
        for m in getattr(vc, "members", []):
            if not getattr(m, "bot", False):
                participants.add(m.id)

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
                "Raid voice channel is empty. Cannot start auction.",
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

    @discord.ui.button(label="End Auction", style=discord.ButtonStyle.primary, custom_id="raid_end_auction", row=1)
    async def end_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        auction_cog = self.bot.get_cog("AuctionCog")
        await auction_cog.end_auction_from_button(interaction)

    @discord.ui.button(label="Close Raid ", style=discord.ButtonStyle.danger, custom_id="raid_close_raid", row=1)
    async def close_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        await raid_cog.close_raid(interaction)

    @discord.ui.button(label="My DKP ", style=discord.ButtonStyle.secondary, custom_id="raid_my_dkp", row=0)
    async def raid_my_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_my_dkp(interaction)
        else:
            await interaction.followup.send("User module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Join Raid", style=discord.ButtonStyle.success, custom_id="raid_join_raid", row=0)
    async def join_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Record the user as a raid participant without needing to be in the voice channel."""
        await interaction.response.defer(ephemeral=True)
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        # Check if the user is already recorded as a raid member
        already_joined = False
        try:
            existing_members = await self.bot.db.get_raid_members(raid["id"])
            user_ids = {int(row["user_id"]) for row in existing_members}
            if interaction.user.id in user_ids:
                already_joined = True
        except Exception:
            # If we can't check, we'll proceed and let the DB's INSERT OR IGNORE handle duplicates
            logging.exception("Failed to check existing raid members for duplicate join")

        if already_joined:
            return await interaction.followup.send("You are already part of this raid.", ephemeral=True)

        # Record the user only if not already present
        try:
            await self.bot.db.add_raid_member(raid["id"], interaction.user.id)
            await interaction.followup.send("You have been added to the raid.", ephemeral=True)
        except Exception:
            await interaction.followup.send("Could not join the raid. Please try again.", ephemeral=True)

    @discord.ui.button(label="Rename Thread", style=discord.ButtonStyle.secondary, custom_id="raid_rename_thread", row=1)
    async def rename_thread(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open a modal to rename the raid thread (raid leaders/officers only)."""
        await interaction.response.defer(ephemeral=True)
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        # Authorization check: raid leader, officer, or admin
        from ..utils import is_officer
        if not await is_officer(interaction) and interaction.user.id != raid["leader_id"]:
            return await interaction.followup.send("You don't have permission to rename this thread.", ephemeral=True)

        from ..ui.modals import ThreadRenameModal
        raid_cog = self.bot.get_cog("RaidCog")
        modal = ThreadRenameModal(raid_cog=raid_cog, raid_id=raid["id"])
        try:
            await interaction.response.send_modal(modal)
        except discord.InteractionResponded:
            # If already deferred (as we did above), use followup
            await interaction.followup.send("Please try again.", ephemeral=True)

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
    #
    #     try:
    #         existing_rules = raid["rules"]
    #     except (KeyError, TypeError):
    #         existing_rules = None
    #
    #     modal = RaidRulesModal(bot=self.bot, raid_id=raid["id"], existing_rules=existing_rules)
    #     await interaction.response.send_modal(modal)

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
