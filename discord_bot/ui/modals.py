import discord
from discord.ui import Modal, TextInput
from discord.ext import commands


class DKPAdjustmentModal(Modal, title="DKP Adjustment"):
    def __init__(self, action: str, raid_cog, member: discord.Member | None = None):
        super().__init__()
        self.action = action
        self.raid_cog = raid_cog
        self.target_member_obj = member  # The member passed from the command

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
            required=True
        )
        self.add_item(self.amount)
        self.add_item(self.reason)

        # Only add the text input if no member was pre-selected
        self.target_member_input = None
        if member is None:
            self.target_member_input = TextInput(
                label="Target Member Name (optional)",
                placeholder="Leave blank to adjust everyone in VC",
                style=discord.TextStyle.short,
                required=False,
            )
            self.add_item(self.target_member_input)

    async def on_submit(self, interaction: discord.Interaction):
        member = self.target_member_obj
        
        # If no member was passed, get it from the text input
        if member is None and self.target_member_input:
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
                    return await interaction.response.send_message(
                        f"Member '{target_value}' not found. Please use their exact Discord name, nickname, or ID.",
                        ephemeral=True
                    )
        
        await self.raid_cog.process_dkp_adjustment(interaction, self.action, self.amount.value, self.reason.value, member)


class RaidCreateModal(Modal, title="Create New Raid"):
    def __init__(self, raid_cog):
        super().__init__()
        self.raid_cog = raid_cog

        self.raid_name = TextInput(
            label="Raid Name",
            placeholder="e.g., MC Progression, Weekly PUG",
            style=discord.TextStyle.short,
            required=True,
        )
        self.add_item(self.raid_name)

    async def on_submit(self, interaction: discord.Interaction):
        await self.raid_cog.create_raid_with_name(interaction, self.raid_name.value)


class AuctionStartModal(Modal, title="Start New Auction"):
    def __init__(self, auction_cog):
        super().__init__()
        self.auction_cog = auction_cog
        self.item_name = TextInput(
            label="Item Name to Auction",
            placeholder="e.g., Thunderfury, Blessed Blade of the Windseeker",
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.item_name)

    async def on_submit(self, interaction: discord.Interaction):
        await self.auction_cog.process_auction_start(interaction, self.item_name.value)

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
