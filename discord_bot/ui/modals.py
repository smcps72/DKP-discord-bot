import discord
from discord.ui import Modal, TextInput

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
