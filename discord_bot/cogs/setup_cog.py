import discord
from discord.ext import commands
from ..ui.views import WelcomeView
from ..utils import create_info_embed
import logging

class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        logging.info(f"Joined new guild: {guild.name} ({guild.id})")
        # Check if setup has already been run
        config = await self.bot.db.get_guild_config(guild.id)
        if config and config['dkp_category_id']:
            logging.warning(f"Bot re-joined {guild.name}, setup already exists.")
            return
        # Create a DKP category
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False)
            }
            category = await guild.create_category("DKP-System", overwrites=overwrites)
            # Create text channels
            dkp_channel = await category.create_text_channel("dkp-system")
            raid_channel = await category.create_text_channel("active-raids")
            # Create hidden voice channel template
            vc_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False)
            }
            vc_template = await category.create_voice_channel("Raid-Template", overwrites=vc_overwrites)
            # Save to DB
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO guilds (guild_id, dkp_category_id, dkp_channel_id, raid_channel_id, raid_vc_template_id, license_key) VALUES (?, ?, ?, ?, ?, ?)",
                (guild.id, category.id, dkp_channel.id, raid_channel.id, vc_template.id, self.bot.license_key)
            )
            # Send welcome panel
            embed = create_info_embed(
                "Welcome to the DKP Bot!",
                "This bot helps you manage your guild's DKP system right here in Discord.\n\n"
                "**Buttons:**\n"
                "🏰 **Create Raid:** Starts a new raid, creating a voice channel and thread.\n"
                "💰 **My DKP:** Privately check your current DKP balance.\n"
                "❓ **Auction Help:** Get information on how bidding works.\n"
                "⚙️ **Admin:** (Officers Only) Configure the bot settings."
            )
            view = WelcomeView(self.bot)
            message = await dkp_channel.send(embed=embed, view=view)
            await message.pin()
            logging.info(f"Successfully set up DKP system for guild {guild.name}")
        except discord.Forbidden:
            logging.error(f"Missing permissions to set up channels in {guild.name}")
            # Try to send a message to the owner or the first available channel
            try:
                await guild.owner.send("I tried to set up my channels in your server but I'm missing the 'Manage Channels' permission. Please grant it and re-invite me.")
            except discord.Forbidden:
                pass # Can't do anything else

async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
