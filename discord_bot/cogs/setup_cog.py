import discord
import discord
from discord.ext import commands
from discord import app_commands
from ..ui.views import WelcomeView
from ..utils import create_info_embed
import logging

class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.run_setup(guild)

    async def run_setup(self, guild: discord.Guild, interaction=None):
        logging.info(f"Running DKP setup for guild: {guild.name} ({guild.id})")
        # Check if setup has already been run
        config = await self.bot.db.get_guild_config(guild.id)
        if config and config['dkp_category_id']:
            category = guild.get_channel(config['dkp_category_id'])
            if isinstance(category, discord.CategoryChannel):
                # We have a config row and a DKP category, but older installs may be missing
                # the raid channel ID or the channel may have been deleted. In that case,
                # attempt a lightweight repair instead of bailing out.
                raid_channel_id = config['raid_channel_id'] if 'raid_channel_id' in config.keys() else None
                raid_channel = guild.get_channel(raid_channel_id) if raid_channel_id else None

                if not raid_channel:
                    # Try to locate an existing "active-raids" channel under the DKP category,
                    # or create it if it does not exist.
                    raid_channel = None
                    for channel in category.text_channels:
                        if channel.name == "active-raids":
                            raid_channel = channel
                            break

                    if not raid_channel:
                        raid_channel = await category.create_text_channel("active-raids")

                    await self.bot.db.execute(
                        "UPDATE guilds SET raid_channel_id = ? WHERE guild_id = ?",
                        (raid_channel.id, guild.id),
                    )
                    msg = f"Setup repaired for {guild.name}: raid channel linked."
                    logging.info(msg)
                else:
                    msg = f"Setup already exists for {guild.name}."
                    logging.warning(f"Bot re-joined {guild.name}, setup already exists.")

                if interaction:
                    # followup.send is used because we deferred the response
                    try:
                        await interaction.followup.send(msg, ephemeral=True)
                    except (discord.NotFound, discord.HTTPException):
                        logging.warning("Setup finished but interaction is no longer valid.")
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

            # Explicitly clean up any legacy "Raid-Template" voice channel under this category.
            # Older versions of the bot created a template VC; the current design does not use it.
            for channel in list(category.voice_channels):
                if channel.name.lower() == "raid-template":
                    try:
                        await channel.delete(reason="Remove legacy Raid-Template voice channel")
                    except discord.Forbidden:
                        logging.warning("Failed to delete legacy Raid-Template voice channel due to permissions.")
                    except Exception as e:
                        logging.warning(f"Error deleting legacy Raid-Template voice channel: {e}")

            # (Legacy) Raid voice channel template is no longer used; store NULL for compatibility.
            vc_template_id = None
            # Create or reuse roles
            officer_role = discord.utils.get(guild.roles, name="Officer")
            if officer_role is None:
                officer_role = await guild.create_role(
                    name="Officer",
                    permissions=discord.Permissions.none(),
                    hoist=True,
                    mentionable=True,
                )

            raider_role = discord.utils.get(guild.roles, name="Raider")
            if raider_role is None:
                raider_role = await guild.create_role(
                    name="Raider",
                    permissions=discord.Permissions.none(),
                    hoist=True,
                    mentionable=True,
                )

            raid_leader_role = discord.utils.get(guild.roles, name="Raid-Leader")
            if raid_leader_role is None:
                raid_leader_role = await guild.create_role(
                    name="Raid-Leader",
                    permissions=discord.Permissions.none(),
                    hoist=True,
                    mentionable=True,
                )

            # Save to DB
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO guilds (guild_id, dkp_category_id, dkp_channel_id, raid_channel_id, raid_vc_template_id, officer_role_id, raider_role_id, raid_leader_role_id, license_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (guild.id, category.id, dkp_channel.id, raid_channel.id, vc_template_id, officer_role.id, raider_role.id, raid_leader_role.id, self.bot.license_key)
            )
            # Send welcome panel
            embed = create_info_embed(
                "Welcome to the DKP Bot!",
                "This bot helps you manage your guild's Dragon Kill Points system right here in Discord.\n\n"
                "**Buttons:**\n"
                "	 **Create Raid:** Starts a new raid tied to your current voice channel and creates a raid log thread.\n"
                "	 **My DKP:** Privately check your current DKP balance.\n"
                "	 **Auction Help:** Get information on how bidding works.\n"
                "	 **Admin:** (Admins Only) Configure the bot settings."
            )
            view = WelcomeView(self.bot)
            message = await dkp_channel.send(embed=embed, view=view)
            await message.pin()
            logging.info(f"Successfully set up DKP system for guild {guild.name}")
            if interaction:
                try:
                    await interaction.followup.send("DKP system setup complete!", ephemeral=True)
                except (discord.NotFound, discord.HTTPException):
                    logging.warning("Setup complete but interaction is no longer valid.")
        except discord.Forbidden:
            logging.error(f"Missing permissions to set up channels or roles in {guild.name}")
            # Try to send a message to the owner or the first available channel
            try:
                await guild.owner.send("I tried to set up my channels and roles in your server but I'm missing the 'Manage Channels' or 'Manage Roles' permission. Please grant them and re-invite me.")
            except discord.Forbidden:
                pass # Can't do anything else
            if interaction:
                try:
                    await interaction.followup.send("Missing permissions to set up channels or roles. Please grant 'Manage Channels' and 'Manage Roles' and try again.", ephemeral=True)
                except (discord.NotFound, discord.HTTPException):
                    logging.warning("Setup permissions error but interaction is no longer valid.")

    @app_commands.command(name="setup_dkp", description="Manually (re)run the DKP system setup. Admins only.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_dkp(self, interaction: discord.Interaction):
        """Manually (re)run the DKP system setup."""
        # We need to defer here because the setup can take a moment
        await interaction.response.defer(ephemeral=True)
        await self.run_setup(interaction.guild, interaction=interaction)

async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
