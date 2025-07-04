import discord
from discord.ui import Modal, TextInput

class DKPAdjustmentModal(Modal, title="DKP Adjustment"):
    def __init__(self, action: str, raid_cog):
        super().__init__()
        self.action = action  # "Award" or "Deduct"
        self.raid_cog = raid_cog
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
        self.target_member = TextInput(
            label="Target Member ID (optional)",
            placeholder="Leave blank to adjust everyone in VC",
            style=discord.TextStyle.short,
            required=False,
        )
        self.add_item(self.amount)
        self.add_item(self.reason)
        self.add_item(self.target_member)

    async def on_submit(self, interaction: discord.Interaction):
        member = None
        if self.target_member.value:
            member_id = None
            digits = [c for c in self.target_member.value if c.isdigit()]
            if digits:
                try:
                    member_id = int("".join(digits))
                except ValueError:
                    member_id = None
            if member_id:
                member = interaction.guild.get_member(member_id)
            if member is None:
                return await interaction.response.send_message("Member not found.", ephemeral=True)
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
