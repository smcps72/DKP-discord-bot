import discord
from .modals import DKPAdjustmentModal, AuctionStartModal, BidModal
from ..utils import is_officer

class WelcomeView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Create Raid 🏰", style=discord.ButtonStyle.success, custom_id="welcome_create_raid")
    async def create_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            await raid_cog.create_raid_from_interaction(interaction)
        else:
            await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)

    @discord.ui.button(label="My DKP 💰", style=discord.ButtonStyle.secondary, custom_id="welcome_my_dkp")
    async def my_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_my_dkp(interaction)
        else:
            await interaction.response.send_message("User module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Auction Help ❓", style=discord.ButtonStyle.primary, custom_id="welcome_auction_help")
    async def auction_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_auction_help(interaction)
        else:
            await interaction.response.send_message("User module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Admin ⚙️", style=discord.ButtonStyle.danger, custom_id="welcome_admin_panel")
    async def admin_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_officer(interaction):
            return await interaction.response.send_message("You must be an officer to use this.", ephemeral=True)
        admin_cog = self.bot.get_cog("AdminCog")
        if admin_cog:
            try:
                await interaction.response.defer(ephemeral=True)
                embed = await admin_cog._create_status_embed(interaction.guild.id)
                await interaction.followup.send(embed=embed, ephemeral=True)
            except discord.NotFound:
                # This might happen if the original interaction is deleted or expires before we can respond.
                pass
        else:
            await interaction.response.send_message("Admin module is currently offline.", ephemeral=True)

class RaidControlView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if raid and interaction.user.id == raid['leader_id']:
            return True
        
        # If the check fails, respond to the user if we haven't already.
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("You are not the leader of this raid.", ephemeral=True)
            except discord.HTTPException:
                # This can happen in a race condition, it's safe to ignore.
                pass
        return False

    @discord.ui.button(label="Update Team", style=discord.ButtonStyle.secondary, custom_id="raid_update_team", row=0)
    async def update_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        await raid_cog.update_team_list(interaction)

    @discord.ui.button(label="Award DKP", style=discord.ButtonStyle.success, custom_id="raid_award_dkp", row=0)
    async def award_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        modal = DKPAdjustmentModal(action="Award", raid_cog=raid_cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Deduct DKP", style=discord.ButtonStyle.danger, custom_id="raid_deduct_dkp", row=0)
    async def deduct_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        modal = DKPAdjustmentModal(action="Deduct", raid_cog=raid_cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Start Auction 💎", style=discord.ButtonStyle.primary, custom_id="raid_start_auction", row=1)
    async def start_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        auction_cog = self.bot.get_cog("AuctionCog")
        modal = AuctionStartModal(auction_cog=auction_cog)
        try:
            await interaction.response.send_modal(modal)
        except (discord.InteractionResponded, discord.NotFound):
            try:
                await interaction.followup.send("This interaction has expired or already received a response. Please try again.", ephemeral=True)
            except Exception:
                pass  # Fully expired, ignore
        except discord.HTTPException as e:
            # Optionally log or handle other HTTP errors
            pass

    @discord.ui.button(label="End Auction", style=discord.ButtonStyle.primary, custom_id="raid_end_auction", row=1)
    async def end_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        auction_cog = self.bot.get_cog("AuctionCog")
        await auction_cog.end_auction_from_button(interaction)

    @discord.ui.button(label="Close Raid ❌", style=discord.ButtonStyle.danger, custom_id="raid_close_raid", row=1)
    async def close_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        await raid_cog.close_raid(interaction)

class AuctionBidView(discord.ui.View):
    def __init__(self, bot, auction_id):
        super().__init__(timeout=300) # 5 minute timeout for bidding
        self.bot = bot
        self.auction_id = auction_id

    @discord.ui.button(label="Bid", style=discord.ButtonStyle.success, custom_id="auction_bid")
    async def bid(self, interaction: discord.Interaction, button: discord.ui.Button):
        auction_cog = self.bot.get_cog("AuctionCog")
        modal = BidModal(auction_cog=auction_cog, auction_id=self.auction_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="auction_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("You have chosen not to bid.", ephemeral=True)
        self.stop()
