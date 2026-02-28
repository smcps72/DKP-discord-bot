import discord
from discord.ui import Modal, TextInput
from discord.ext import commands
from ..utils import send_dkp_change_dm


class DKPAdjustmentModal(Modal, title="DKP Adjustment"):
    def __init__(
        self,
        action: str,
        raid_cog,
        member: discord.Member | None = None,
        members: list[discord.Member] | None = None,
        group_number: int | None = None,
        source: str | None = None,
        popup_message: discord.Message | None = None,
    ):
        super().__init__()
        self.action = action
        self.raid_cog = raid_cog
        self.target_member_obj = member  # The member passed from the command
        self.group_number = group_number
        self.target_members = list(members) if members else None
        self.source = source
        self.popup_message = popup_message

        self.amount = TextInput(
            label="Amount of DKP",
            placeholder="e.g., 5 or 10",
            style=discord.TextStyle.short,
            required=True
        )
        self.reason = TextInput(
            label="Reason",
            placeholder="e.g., Boss kill, Raid participation",
            style=discord.TextStyle.long,
            required=True,
            max_length=300,
        )
        self.add_item(self.amount)
        self.add_item(self.reason)

        # Only add the text input if no member was pre-selected
        self.target_member_input = None
        if member is None and source not in ("raid_panel", "raid_popup"):
            self.target_member_input = TextInput(
                label="Target Member Name (optional)",
                placeholder="Leave blank to adjust everyone in raid",
                style=discord.TextStyle.short,
                required=False,
                max_length=100,
            )
            self.add_item(self.target_member_input)

        self.include_groups_input = None
        self.exclude_groups_input = None
        self.exclude_members_input = None
        if member is None and group_number is None:
            if source in ("raid_panel", "raid_popup"):
                self.include_groups_input = TextInput(
                    label="Include group number(s) (optional)",
                    placeholder="e.g., 1, 2",
                    style=discord.TextStyle.short,
                    required=False,
                    max_length=50,
                )
            self.exclude_groups_input = TextInput(
                label="Exclude group number(s) (optional)",
                placeholder="e.g., 1, 2",
                style=discord.TextStyle.short,
                required=False,
                max_length=50,
            )
            self.exclude_members_input = TextInput(
                label="Exclude member(s) (optional)",
                placeholder="@mentions or IDs, comma-separated",
                style=discord.TextStyle.short,
                required=False,
                max_length=200,
            )
            if self.include_groups_input is not None:
                self.add_item(self.include_groups_input)
            self.add_item(self.exclude_groups_input)
            self.add_item(self.exclude_members_input)

    async def on_submit(self, interaction: discord.Interaction):
        member = self.target_member_obj
        target_members = self.target_members
        
        # If no member was passed, get it from the text input
        if member is None and target_members is None and self.target_member_input:
            target_value = self.target_member_input.value
            if target_value:
                # First, try to find by name/nickname
                member = interaction.guild.get_member_named(target_value)

                # If not found, try to parse as an ID or mention
                if member is None:
                    member_id = None
                    digits = [c for c in target_value if c.isdigit()]
                    if digits:
                        try:
                            member_id = int("".join(digits))
                        except ValueError:
                            pass
                    if member_id:
                        member = interaction.guild.get_member(member_id)

                if member is None:
                    if self.source == "raid_popup" and self.popup_message is not None:
                        try:
                            if not interaction.response.is_done():
                                await interaction.response.defer(ephemeral=True)
                        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                            pass
                        try:
                            embed = discord.Embed(
                                title="DKP Adjustment",
                                description=(
                                    f"Member '{target_value}' not found. Please use their exact Discord name, nickname, or ID."
                                ),
                                color=discord.Color.red(),
                            )
                            await self.popup_message.edit(embed=embed)
                            try:
                                if interaction.type == discord.InteractionType.modal_submit:
                                    await interaction.delete_original_response()
                            except Exception:
                                pass
                        except Exception:
                            pass
                        return

                    return await interaction.response.send_message(
                        f"Member '{target_value}' not found. Please use their exact Discord name, nickname, or ID.",
                        ephemeral=True,
                    )

        include_group_numbers: set[int] | None = None
        if self.include_groups_input is not None:
            raw = (self.include_groups_input.value or "").strip()
            if raw:
                include_group_numbers = set()
                for token in raw.replace(";", ",").replace(" ", ",").split(","):
                    token = token.strip()
                    if not token:
                        continue
                    try:
                        include_group_numbers.add(int(token))
                    except ValueError:
                        continue
                if not include_group_numbers:
                    include_group_numbers = None

        exclude_group_numbers: set[int] | None = None
        if self.exclude_groups_input is not None:
            raw = (self.exclude_groups_input.value or "").strip()
            if raw:
                exclude_group_numbers = set()
                for token in raw.replace(";", ",").replace(" ", ",").split(","):
                    token = token.strip()
                    if not token:
                        continue
                    try:
                        exclude_group_numbers.add(int(token))
                    except ValueError:
                        continue
                if not exclude_group_numbers:
                    exclude_group_numbers = None

        exclude_member_ids: set[int] | None = None
        if self.exclude_members_input is not None:
            raw = (self.exclude_members_input.value or "").strip()
            if raw:
                exclude_member_ids = set()
                for part in raw.replace(";", ",").split(","):
                    part = part.strip()
                    if not part:
                        continue
                    digits = [c for c in part if c.isdigit()]
                    if not digits:
                        continue
                    try:
                        exclude_member_ids.add(int("".join(digits)))
                    except ValueError:
                        continue
                if not exclude_member_ids:
                    exclude_member_ids = None
        reason = (self.reason.value or "").strip()
        if not reason:
            reason = "No reason provided"
        if len(reason) > 300:
            reason = reason[:300]

        await self.raid_cog.process_dkp_adjustment(
            interaction,
            self.action,
            self.amount.value,
            reason,
            member,
            members=target_members,
            group_number=self.group_number,
            source=self.source,
            include_group_numbers=include_group_numbers,
            exclude_member_ids=exclude_member_ids,
            exclude_group_numbers=exclude_group_numbers,
            popup_message=self.popup_message,
        )


class RaidTimedAwardModal(Modal, title="Timed Raid DKP"):
    def __init__(
        self,
        raid_cog,
        *,
        source: str | None = None,
        popup_message: discord.Message | None = None,
    ):
        super().__init__()
        self.raid_cog = raid_cog
        self.source = source
        self.popup_message = popup_message

        self.amount = TextInput(
            label="DKP per interval",
            placeholder="e.g., 5",
            style=discord.TextStyle.short,
            required=True,
            max_length=6,
        )
        self.interval_minutes = TextInput(
            label="Interval (minutes)",
            placeholder="e.g., 30",
            style=discord.TextStyle.short,
            required=True,
            max_length=4,
        )

        self.add_item(self.amount)
        self.add_item(self.interval_minutes)

    async def on_submit(self, interaction: discord.Interaction):
        async def respond_error(message: str):
            if self.source == "raid_popup" and self.popup_message is not None:
                try:
                    if not interaction.response.is_done():
                        await interaction.response.defer(ephemeral=True)
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                    pass

                try:
                    embed = discord.Embed(title="Timed DKP", description=message, color=discord.Color.red())
                    await self.popup_message.edit(embed=embed)
                    try:
                        if interaction.type == discord.InteractionType.modal_submit:
                            await interaction.delete_original_response()
                    except Exception:
                        pass
                except Exception:
                    pass
                return

            try:
                if not interaction.response.is_done():
                    return await interaction.response.send_message(message, ephemeral=True)
                return await interaction.followup.send(message, ephemeral=True)
            except Exception:
                return

        raw_amount = (self.amount.value or "").strip()
        raw_interval = (self.interval_minutes.value or "").strip()
        try:
            amount = int(raw_amount)
        except ValueError:
            return await respond_error("Amount must be a whole number.")
        try:
            interval = int(raw_interval)
        except ValueError:
            return await respond_error("Interval must be a whole number.")

        if amount <= 0:
            return await respond_error("Amount must be greater than 0.")
        if interval <= 0:
            return await respond_error("Interval must be greater than 0.")

        await self.raid_cog.configure_timed_award(
            interaction,
            amount=amount,
            interval_minutes=interval,
            source=self.source,
            popup_message=self.popup_message,
        )


class RaidPointsModal(Modal, title="Raid Points"):
    def __init__(self, raid_cog, *, source: str | None = None):
        super().__init__()
        self.raid_cog = raid_cog
        self.source = source

        self.scope = TextInput(
            label="Scope (raid or total)",
            placeholder="raid",
            style=discord.TextStyle.short,
            required=True,
            max_length=10,
        )
        self.sort = TextInput(
            label="Sort (name or dkp)",
            placeholder="dkp",
            style=discord.TextStyle.short,
            required=True,
            max_length=10,
        )

        self.add_item(self.scope)
        self.add_item(self.sort)

    async def on_submit(self, interaction: discord.Interaction):
        scope = (self.scope.value or "").strip().lower()
        sort = (self.sort.value or "").strip().lower()
        await self.raid_cog.show_raid_points(
            interaction,
            scope=scope,
            sort=sort,
        )


class RaidReverseDKPModal(Modal, title="Reverse Raid DKP"):
    def __init__(self, raid_cog):
        super().__init__()
        self.raid_cog = raid_cog

        self.confirm = TextInput(
            label="Type CONFIRM to reverse raid DKP",
            placeholder="CONFIRM",
            style=discord.TextStyle.short,
            required=True,
            max_length=20,
        )
        self.reason = TextInput(
            label="Reason",
            placeholder="This will remove all DKP given during the raid. e.g., Raid payout used DKP; reversing awards",
            style=discord.TextStyle.long,
            required=True,
            max_length=300,
        )

        self.add_item(self.confirm)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        confirm = (self.confirm.value or "").strip()
        reason = (self.reason.value or "").strip()
        await self.raid_cog.reverse_raid_dkp(
            interaction,
            confirm=confirm,
            reason=reason,
        )


class AdminDKPAdjustModal(Modal, title="Admin DKP Adjustment"):
    def __init__(self, admin_cog, member: discord.Member):
        super().__init__()
        self.admin_cog = admin_cog
        self.member = member

        self.amount_input = TextInput(
            label="Amount of DKP (signed integer)",
            placeholder="e.g., 50 or -25",
            style=discord.TextStyle.short,
            required=True,
        )
        self.reason_input = TextInput(
            label="Reason for adjustment",
            placeholder="Explain why you are changing DKP.",
            style=discord.TextStyle.long,
            required=True,
            max_length=300,
        )
        self.confirm_input = TextInput(
            label="Type YES to confirm",
            placeholder="Type YES exactly (all caps) to run this.",
            style=discord.TextStyle.short,
            required=True,
        )

        self.add_item(self.amount_input)
        self.add_item(self.reason_input)
        self.add_item(self.confirm_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild = getattr(interaction, "guild", None)
        if not guild:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        # Basic confirmation to prevent accidental misuse
        if self.confirm_input.value != "YES":
            await interaction.response.send_message(
                "This is a powerful admin-only DKP adjustment. "
                "To proceed, reopen the modal and type `YES` exactly (all caps) in the confirm field.",
                ephemeral=True,
            )
            return

        # Parse amount
        amount_raw = self.amount_input.value.strip()
        try:
            amount = int(amount_raw)
        except ValueError:
            await interaction.response.send_message(
                "Amount must be a whole number (e.g., 50 or -25).",
                ephemeral=True,
            )
            return

        if amount == 0:
            await interaction.response.send_message(
                "Amount must be non-zero. Use a positive or negative integer to adjust DKP.",
                ephemeral=True,
            )
            return

        # Use the pre-selected member from the slash command
        member = self.member

        # Sanity check in case something changed between command and modal submit
        if member is None or member.guild != guild:
            await interaction.response.send_message(
                "Could not resolve the selected member in this server. Please try again.",
                ephemeral=True,
            )
            return

        if member.bot:
            await interaction.response.send_message(
                "Bots do not have DKP.",
                ephemeral=True,
            )
            return

        reason = self.reason_input.value.strip() or "No reason provided"
        if len(reason) > 300:
            reason = reason[:300]

        await self.admin_cog.bot.db.modify_user_dkp(
            member.id,
            guild.id,
            amount,
            f"ADMIN MANUAL ADJUST: {reason}",
        )

        new_dkp = await self.admin_cog.bot.db.get_user_dkp(member.id, guild.id)
        await send_dkp_change_dm(
            member,
            guild,
            amount,
            f"ADMIN MANUAL ADJUST: {reason}",
            new_total=new_dkp,
        )
        await interaction.response.send_message(
            f"Adjusted {member.mention} by {amount} DKP for: {reason}\nNew DKP balance: {new_dkp}",
            ephemeral=True,
        )


class RaidCreateModal(Modal, title="Create New Raid"):
    def __init__(self, raid_cog):
        super().__init__()
        self.raid_cog = raid_cog

        self.raid_name = TextInput(
            label="Raid Name",
            placeholder="e.g., MC Progression, Weekly PUG",
            style=discord.TextStyle.short,
            required=True,
            max_length=100,
        )
        self.add_item(self.raid_name)

    async def on_submit(self, interaction: discord.Interaction):
        raid_name = (self.raid_name.value or "").strip()
        if not raid_name:
            raid_name = "Raid"
        if len(raid_name) > 100:
            raid_name = raid_name[:100]
        await self.raid_cog.create_raid_with_name(interaction, raid_name)


class RaidGroupCountModal(Modal, title="Set Raid Groups"):
    def __init__(self, raid_cog):
        super().__init__()
        self.raid_cog = raid_cog

        self.group_count = TextInput(
            label="How many groups?",
            placeholder="e.g., 2",
            style=discord.TextStyle.short,
            required=True,
            max_length=2,
        )
        self.add_item(self.group_count)

    async def on_submit(self, interaction: discord.Interaction):
        raw = (self.group_count.value or "").strip()
        try:
            count = int(raw)
        except ValueError:
            return await interaction.response.send_message(
                "Group count must be a whole number.",
                ephemeral=True,
            )

        if count < 1 or count > 20:
            return await interaction.response.send_message(
                "Group count must be between 1 and 20.",
                ephemeral=True,
            )

        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        await self.raid_cog.configure_raid_groups(interaction, count)


class AuctionStartModal(Modal, title="Start New Auction"):
    def __init__(
        self,
        auction_cog,
        *,
        source: str | None = None,
        popup_can_manage: bool = False,
        popup_can_rename_thread: bool = False,
        popup_message: discord.Message | None = None,
    ):
        super().__init__()
        self.auction_cog = auction_cog
        self.source = source
        self.popup_can_manage = bool(popup_can_manage)
        self.popup_can_rename_thread = bool(popup_can_rename_thread)
        self.popup_message = popup_message
        self.item_name = TextInput(
            label="Item Name to Auction",
            placeholder="e.g., Thunderfury, Blessed Blade of the Windseeker",
            style=discord.TextStyle.short,
            required=True,
            max_length=100,
        )
        self.add_item(self.item_name)

    async def on_submit(self, interaction: discord.Interaction):
        item_name = (self.item_name.value or "").strip()
        if not item_name:
            item_name = "Item"
        if len(item_name) > 100:
            item_name = item_name[:100]
        await self.auction_cog.process_auction_start(
            interaction,
            item_name,
            source=self.source,
            popup_can_manage=self.popup_can_manage,
            popup_can_rename_thread=self.popup_can_rename_thread,
            popup_message=self.popup_message,
        )

class BidModal(Modal, title="Place Your Bid"):
    def __init__(self, auction_cog, auction_id: int):
        super().__init__()
        self.auction_cog = auction_cog
        self.auction_id = auction_id
        self.bid_amount = TextInput(
            label="Your Bid Amount (DKP)",
            placeholder="Enter a whole number",
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.bid_amount)

    async def on_submit(self, interaction: discord.Interaction):
        await self.auction_cog.process_bid(interaction, self.auction_id, self.bid_amount.value)


class RaidRulesModal(Modal, title="Edit Raid Rules"):
    def __init__(self, bot, raid_id: int, existing_rules: str | None = None):
        super().__init__()
        self.bot = bot
        self.raid_id = raid_id

        # Discord modals can only have up to 5 inputs, so we add
        # one rule at a time to keep things simple and reliable.
        self.description_input = TextInput(
            label="Rule Description",
            placeholder="Describe one rule, e.g.: Showed up on time",
            style=discord.TextStyle.long,
            required=True,
            max_length=300,
        )
        self.points_input = TextInput(
            label="Points for this Rule",
            placeholder="Enter a whole number, e.g.: 5",
            style=discord.TextStyle.short,
            required=True,
        )

        self.add_item(self.description_input)
        self.add_item(self.points_input)

    async def on_submit(self, interaction: discord.Interaction):
        description = self.description_input.value.strip()
        if len(description) > 300:
            description = description[:300]
        points_raw = self.points_input.value.strip()

        # Basic validation for points
        try:
            points_val = int(points_raw)
            if points_val <= 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "Points must be a positive whole number.",
                ephemeral=True,
            )

        # Fetch existing rules text (if any) and rebuild numbered list
        existing_text = await self.bot.db.get_raid_rules(self.raid_id)
        existing_lines = []
        if existing_text:
            existing_lines = [line.strip() for line in existing_text.splitlines() if line.strip()]

        # Append the new rule and renumber everything
        all_rules = []
        # First, keep existing rules but strip their leading numbers if present
        for line in existing_lines:
            # Try to split off an initial "N." if present
            parts = line.split(".", 1)
            if len(parts) == 2 and parts[0].strip().isdigit():
                rule_body = parts[1].strip()
            else:
                rule_body = line
            all_rules.append(rule_body)

        all_rules.append(f"{description} – {points_val} points")

        # Re-number
        numbered_lines = [f"{idx}. {body}" for idx, body in enumerate(all_rules, start=1)]
        rules_text = "\n".join(numbered_lines)

        await self.bot.db.set_raid_rules(self.raid_id, rules_text)
        await interaction.response.send_message(
            "Rule added. Discord limits how many inputs a modal can have, "
            "so rules are added one at a time.",
            ephemeral=True,
        )

class ThreadRenameModal(discord.ui.Modal):
    def __init__(
        self,
        raid_cog,
        raid_id: int,
        *,
        source: str | None = None,
        popup_can_manage: bool = False,
        popup_can_rename_thread: bool = False,
        popup_message: discord.Message | None = None,
    ):
        super().__init__(title="Rename Raid Thread")
        self.raid_cog = raid_cog
        self.raid_id = raid_id
        self.source = source
        self.popup_can_manage = bool(popup_can_manage)
        self.popup_can_rename_thread = bool(popup_can_rename_thread)
        self.popup_message = popup_message

        self.new_name = discord.ui.TextInput(
            label="New thread name",
            placeholder="Enter the new name for the raid thread",
            required=True,
            max_length=100,
        )
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.new_name.value.strip()
        await self.raid_cog.rename_raid_thread(
            interaction,
            self.raid_id,
            new_name,
            source=self.source,
            popup_can_manage=self.popup_can_manage,
            popup_can_rename_thread=self.popup_can_rename_thread,
            popup_message=self.popup_message,
        )


class RaidGroupSetupModal(Modal, title="Set Up Raid Groups"):
    def __init__(self, raid_cog):
        super().__init__()
        self.raid_cog = raid_cog

        self.group_count = TextInput(
            label="Number of groups",
            placeholder="e.g., 2, 4, 6",
            style=discord.TextStyle.short,
            required=True,
            max_length=2,
        )
        self.add_item(self.group_count)

    async def on_submit(self, interaction: discord.Interaction):
        raw = (self.group_count.value or "").strip()
        try:
            count = int(raw)
        except ValueError:
            return await interaction.response.send_message("Group count must be a whole number.", ephemeral=True)

        if count < 1 or count > 25:
            return await interaction.response.send_message("Group count must be between 1 and 25.", ephemeral=True)

        await self.raid_cog.setup_raid_groups(interaction, count)



class DefaultDKPAwardModal(Modal, title="Default Timed DKP"):
    def __init__(self, bot: commands.Bot, *, panel_message: discord.Message | None = None):
        super().__init__()
        self.bot = bot
        self.panel_message = panel_message

        self.amount = TextInput(
            label="DKP per interval",
            placeholder="e.g., 6 (recommended: use a 1-minute interval)",
            style=discord.TextStyle.short,
            required=True,
            max_length=6,
        )
        self.interval_minutes = TextInput(
            label="Interval (minutes)",
            placeholder="e.g., 1 (recommended)",
            style=discord.TextStyle.short,
            required=True,
            max_length=3,
            default="1",
        )
        self.add_item(self.amount)
        self.add_item(self.interval_minutes)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "This can only be used inside a server.",
                ephemeral=True,
            )

        raw_amount = (self.amount.value or "").strip()
        raw_interval = (self.interval_minutes.value or "").strip()
        try:
            amount = int(raw_amount)
        except ValueError:
            return await interaction.response.send_message("DKP amount must be a whole number.", ephemeral=True)

        try:
            interval = int(raw_interval)
        except ValueError:
            return await interaction.response.send_message("Interval must be a whole number.", ephemeral=True)

        if amount <= 0:
            return await interaction.response.send_message("DKP amount must be greater than 0.", ephemeral=True)

        if interval <= 0:
            return await interaction.response.send_message("Interval must be greater than 0.", ephemeral=True)

        if interval > 999:
            return await interaction.response.send_message("Interval cannot exceed 999 minutes.", ephemeral=True)

        try:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)",
                (int(interaction.guild.id),),
            )
        except Exception:
            pass

        await self.bot.db.execute(
            "UPDATE guilds SET default_dkp_award = ?, default_dkp_interval = ? WHERE guild_id = ?",
            (int(amount), int(interval), int(interaction.guild.id)),
        )

        if self.panel_message is not None:
            try:
                await self.panel_message.edit(
                    content=f"Default timed DKP set to {int(amount)} DKP per {int(interval)} minute(s).",
                    view=None,
                )
            except Exception:
                pass

        return await interaction.response.send_message(
            f"Default timed DKP is now set to `{int(amount)}` DKP per `{int(interval)}` minute(s).\n\n"
            f"**Tip:** We recommend using the smallest interval (e.g., 6 DKP per 1 minute instead of 10 DKP per 60 minutes).",
            ephemeral=True,
        )


class GuildBankDepositModal(Modal, title="Deposit Item"):
    def __init__(self, bank_cog):
        super().__init__()
        self.bank_cog = bank_cog

        self.item_name = TextInput(
            label="Item Name",
            placeholder="e.g., Arcanite Bar",
            style=discord.TextStyle.short,
            required=True,
            max_length=100,
        )
        self.quantity = TextInput(
            label="Quantity",
            placeholder="e.g., 10",
            style=discord.TextStyle.short,
            required=True,
            max_length=10,
        )
        self.category = TextInput(
            label="Category",
            placeholder="material / consumable / equipment / currency / other",
            style=discord.TextStyle.short,
            required=True,
            max_length=20,
            default="other",
        )
        self.location = TextInput(
            label="Location / Storage Name",
            placeholder="e.g., Guild Vault Tab 1, BankAlt",
            style=discord.TextStyle.short,
            required=True,
            max_length=100,
        )
        self.held_by = TextInput(
            label="Held By (member name or ID, blank = you)",
            placeholder="Leave blank to use your own name",
            style=discord.TextStyle.short,
            required=False,
            max_length=100,
        )

        self.add_item(self.item_name)
        self.add_item(self.quantity)
        self.add_item(self.category)
        self.add_item(self.location)
        self.add_item(self.held_by)

    async def on_submit(self, interaction: discord.Interaction):
        await self.bank_cog.process_deposit(
            interaction,
            item_name=self.item_name.value,
            quantity_str=self.quantity.value,
            category=self.category.value,
            location=self.location.value,
            held_by_name=self.held_by.value or "",
        )


class GuildBankWithdrawModal(Modal, title="Withdraw Item"):
    def __init__(self, bank_cog):
        super().__init__()
        self.bank_cog = bank_cog

        self.item_id = TextInput(
            label="Item ID (from /bank_inventory)",
            placeholder="e.g., 3",
            style=discord.TextStyle.short,
            required=True,
            max_length=10,
        )
        self.quantity = TextInput(
            label="Quantity",
            placeholder="e.g., 5",
            style=discord.TextStyle.short,
            required=True,
            max_length=10,
        )
        self.note = TextInput(
            label="Note (optional)",
            placeholder="e.g., For raid consumables",
            style=discord.TextStyle.long,
            required=False,
            max_length=300,
        )

        self.add_item(self.item_id)
        self.add_item(self.quantity)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        await self.bank_cog.process_withdraw(
            interaction,
            item_id_str=self.item_id.value,
            quantity_str=self.quantity.value,
            note=self.note.value or "",
        )
