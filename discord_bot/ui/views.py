import discord
from .modals import DKPAdjustmentModal, AuctionStartModal, BidModal, RoleSetupModal
from discord.ui import UserSelect
from ..utils import is_officer

class WelcomeView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Create Raid 🏰", style=discord.ButtonStyle.success, custom_id="welcome_create_raid")
    async def create_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
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
        if not await is_officer(interaction):
            return await interaction.followup.send("You must be an officer to use this.", ephemeral=True)
        
        view = AdminPanelView(self.bot)
        await interaction.followup.send("Welcome to the Admin Panel.", view=view, ephemeral=True)


# -- ADMIN VIEWS --

class RoleManagementView(discord.ui.View):
    def __init__(self, bot, role_type: str, original_view: discord.ui.View):
        super().__init__(timeout=180)
        self.bot = bot
        self.role_type = role_type
        self.original_view = original_view
        self.add_item(self.AssignUserSelect(bot=self.bot, role_type=self.role_type))
        self.add_item(self.UnassignUserSelect(bot=self.bot, role_type=self.role_type))

        if self.role_type == "Raider":
            self.add_item(self.AssignVCButton(bot=self.bot, role_type=self.role_type))

    class AssignUserSelect(UserSelect):
        def __init__(self, bot, role_type):
            self.bot = bot
            self.role_type = role_type
            super().__init__(placeholder=f"Assign {role_type} role to...", min_values=1, max_values=25, row=0)

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            config = await self.bot.db.get_guild_config(interaction.guild.id)
            key = f'{self.role_type.lower().replace("-", "_")}_role_id'
            role_id = config[key] if key in config.keys() else None
            if not role_id:
                return await interaction.followup.send(f"The {self.role_type} role has not been set.", ephemeral=True)
            
            role = interaction.guild.get_role(role_id)
            if not role:
                return await interaction.followup.send(f"The configured {self.role_type} role could not be found.", ephemeral=True)

            successful, failed = [], []
            for member in self.values:
                if role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Assigned by {interaction.user}")
                        successful.append(member.display_name)
                    except discord.Forbidden:
                        failed.append(member.display_name)
                
            msg = f"Assigned {self.role_type} role to: {', '.join(successful)}." if successful else ""
            if failed:
                msg += f"\nFailed to assign role to: {', '.join(failed)}. (Check bot permissions and role hierarchy)"
            
            await interaction.followup.send(msg or "No changes made.", ephemeral=True)

    class UnassignUserSelect(UserSelect):
        def __init__(self, bot, role_type):
            self.bot = bot
            self.role_type = role_type
            super().__init__(placeholder=f"Unassign {role_type} role from...", min_values=1, max_values=25, row=1)

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            config = await self.bot.db.get_guild_config(interaction.guild.id)
            key = f'{self.role_type.lower().replace("-", "_")}_role_id'
            role_id = config[key] if key in config.keys() else None
            if not role_id:
                return await interaction.followup.send(f"The {self.role_type} role has not been set.", ephemeral=True)
            
            role = interaction.guild.get_role(role_id)
            if not role:
                return await interaction.followup.send(f"The configured {self.role_type} role could not be found.", ephemeral=True)

            successful, failed = [], []
            for member in self.values:
                if role in member.roles:
                    try:
                        await member.remove_roles(role, reason=f"Unassigned by {interaction.user}")
                        successful.append(member.display_name)
                    except discord.Forbidden:
                        failed.append(member.display_name)
            
            msg = f"Unassigned {self.role_type} role from: {', '.join(successful)}." if successful else ""
            if failed:
                msg += f"\nFailed to unassign role from: {', '.join(failed)}. (Check bot permissions and role hierarchy)"

            await interaction.followup.send(msg or "No changes made.", ephemeral=True)

    class AssignVCButton(discord.ui.Button):
        def __init__(self, bot, role_type):
            self.bot = bot
            self.role_type = role_type
            super().__init__(label="Assign to all in your VC", style=discord.ButtonStyle.success, row=2)

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)

            admin_member = interaction.user
            if not isinstance(admin_member, discord.Member) or not admin_member.voice or not admin_member.voice.channel:
                return await interaction.followup.send("You must be in a voice channel to use this button.", ephemeral=True)

            voice_channel = admin_member.voice.channel
            members_in_vc = voice_channel.members

            config = await self.bot.db.get_guild_config(interaction.guild.id)
            key = f'{self.role_type.lower().replace("-", "_")}_role_id'
            role_id = config[key] if key in config.keys() else None
            if not role_id:
                return await interaction.followup.send(f"The {self.role_type} role has not been set.", ephemeral=True)
            
            role = interaction.guild.get_role(role_id)
            if not role:
                return await interaction.followup.send(f"The configured {self.role_type} role could not be found.", ephemeral=True)

            successful, failed = [], []
            for member in members_in_vc:
                if role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Assigned by {interaction.user} via VC assignment")
                        successful.append(member.display_name)
                    except discord.Forbidden:
                        failed.append(member.display_name)
            
            msg = f"Assigned {self.role_type} role to: {', '.join(successful)}." if successful else ""
            if failed:
                msg += f"\nFailed to assign role to: {', '.join(failed)}. (Check bot permissions and role hierarchy)"

            await interaction.followup.send(msg or "All members in the voice channel already have the Raider role.", ephemeral=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.grey, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self.original_view)

class AdminPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await is_officer(interaction):
            await interaction.response.send_message("You must be an officer to use this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Manage Officers", style=discord.ButtonStyle.primary, row=0)
    async def manage_officers(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RoleManagementView(self.bot, "Officer", self)
        await interaction.response.edit_message(content="Manage Officer assignments:", view=view)

    @discord.ui.button(label="Manage Raid Leaders", style=discord.ButtonStyle.primary, row=0)
    async def manage_raid_leaders(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RoleManagementView(self.bot, "Raid-Leader", self)
        await interaction.response.edit_message(content="Manage Raid Leader assignments:", view=view)

    @discord.ui.button(label="Manage Raiders", style=discord.ButtonStyle.primary, row=0)
    async def manage_raiders(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RoleManagementView(self.bot, "Raider", self)
        await interaction.response.edit_message(content="Manage Raider assignments:", view=view)

    @discord.ui.button(label="Admin Help", style=discord.ButtonStyle.secondary, row=1)
    async def admin_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        help_text = (
            "### What is the difference between Officers and Raid Leaders?\n\n"
            "**Officer Role**\n"
            "- **Purpose**: Bot Administration. Officers are trusted users who can configure the bot and access protected admin commands.\n"
            "- **Permissions**: Grants access to the `/admin_panel`. It does not grant any special Discord server permissions.\n"
            "- **Assignment**: Manually assigned via this panel. It is a permanent role until manually removed.\n\n"
            "**Raid-Leader Role**\n"
            "- **Purpose**: Raid Management. Raid Leaders are responsible for managing a single, active raid instance.\n"
            "- **Permissions**: When a raid starts, a temporary role is created with permissions to manage the new raid channel. This role is removed when the raid ends.\n"
            "- **Assignment**: Automatically assigned to the user who starts a raid. It is a temporary role that is automatically removed when the raid ends.\n\n"
            "**In short: Officers manage the bot, Raid Leaders manage the raid.**"
        )
        await interaction.response.send_message(help_text, ephemeral=True)

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
        modal = DKPAdjustmentModal(action="Award", raid_cog=raid_cog, member=None)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Deduct DKP", style=discord.ButtonStyle.danger, custom_id="raid_deduct_dkp", row=0)
    async def deduct_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        modal = DKPAdjustmentModal(action="Deduct", raid_cog=raid_cog, member=None)
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
