import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import asyncio
import aiohttp
import sys
from pathlib import Path
from discord import app_commands, HTTPException

# Fix for 'RuntimeError: Event loop is closed' on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- Path Setup ---
# This allows the script to be run from anywhere by adding the project root to the system path.
# This ensures that imports like `from discord_bot.database...` work correctly.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from discord_bot.database import Database, DB_FILE
from discord_bot.ui.views import WelcomeView, RaidControlView

# --- Environment Variable Loading ---
# The bot will look for the .env file in the project root.
dotenv_path = project_root / ".env"

if dotenv_path.exists():
    print(f"INFO: Loading environment from {dotenv_path}")
    load_dotenv(dotenv_path=dotenv_path, override=True)
else:
    print("WARNING: No .env file found. Relying on system environment variables.")

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')

# --- Load Environment Variables ---
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
LICENSE_KEY = os.getenv("GUILD_LICENSE_KEY")
LICENSE_SERVER_URL = os.getenv("LICENSE_SERVER_URL", "https://dkp-discord-bot-production.up.railway.app")
LICENSE_CHECK_ENABLED = os.getenv("LICENSE_CHECK_ENABLED", "false").lower() == "true"

# Optional: limit slash-command sync to a single test guild so changes appear immediately.
TEST_GUILD_ID_ENV = os.getenv("TEST_GUILD_ID")
TEST_GUILD_ID: int | None = None
if TEST_GUILD_ID_ENV:
    try:
        TEST_GUILD_ID = int(TEST_GUILD_ID_ENV)
    except ValueError:
        logging.warning("TEST_GUILD_ID is set but is not a valid integer; falling back to global command sync.")

if not TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN is missing. Please check your .env file.")
if LICENSE_CHECK_ENABLED and not all([LICENSE_KEY, LICENSE_SERVER_URL]):
    raise ValueError("GUILD_LICENSE_KEY or LICENSE_SERVER_URL are missing for license check. Please check your .env file or disable license check.")

# --- Bot Class ---
class DkpBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True  # Required for member info and voice state
        intents.voice_states = True # Required for seeing who is in a VC
        intents.messages = True
        intents.message_content = True # Required for potential future prefix commands

        super().__init__(command_prefix="!", intents=intents)
        self.db = Database(DB_FILE)
        self.license_key = LICENSE_KEY
        self.license_server_url = LICENSE_SERVER_URL
        self.license_check_enabled = LICENSE_CHECK_ENABLED
        
    async def setup_hook(self):
        # This is called before the bot logs in
        await self.db.connect()
        self.http_session = aiohttp.ClientSession()

        # Load Cogs
        cogs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cogs")
        if os.path.isdir(cogs_dir):
            for filename in os.listdir(cogs_dir):
                if filename.endswith('.py'):
                    try:
                        await self.load_extension(f'discord_bot.cogs.{filename[:-3]}')
                        logging.info(f'Loaded cog: {filename}')
                    except Exception as e:
                        logging.error(f'Failed to load cog {filename}: {e}')
        
        # Add persistent views
        self.add_view(WelcomeView(self))
        self.add_view(RaidControlView(self))
        
        # Sync slash commands
        # In a production bot, you might want to sync only once or on command
        # await self.tree.sync()

    async def on_ready(self):
        logging.info(f'Logged in as {self.user} (ID: {self.user.id})')
        logging.info('------')
        # Sync slash commands after ready, ensures guild objects are cached.
        try:
            if TEST_GUILD_ID is not None:
                guild = discord.Object(id=TEST_GUILD_ID)
                # Copy all global commands into this guild so they can be updated instantly
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logging.info(f"Synced {len(synced)} slash commands to test guild {TEST_GUILD_ID}.")
            else:
                synced = await self.tree.sync()
                logging.info(f"Synced {len(synced)} global slash commands.")
        except Exception as e:
            logging.error(f"Error syncing application commands: {e}")

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Track which users have ever joined a raid voice channel.

        Whenever a member connects to or moves into a voice channel that is
        associated with an active raid, we record them in the raid_members
        table so that raid membership can later be reported even after the
        raid is closed and the VC is deleted.
        """

        # Only care when the member is connected to a voice channel.
        if after.channel is None:
            return

        try:
            raid = await self.db.get_raid_by_vc(after.channel.id)
        except Exception as e:
            logging.error(f"Error fetching raid for voice channel {after.channel.id}: {e}")
            return

        if not raid:
            return

        try:
            await self.db.add_raid_member(raid["id"], member.id)
        except Exception as e:
            logging.error(
                f"Error recording raid member {member.id} for raid {raid.get('id')}: {e}"
            )

    async def close(self):
        await super().close()
        if hasattr(self, 'http_session'):
            await self.http_session.close()
        if hasattr(self.db, 'conn') and self.db.conn:
            await self.db.conn.close()

# --- Run the Bot ---
bot = DkpBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logging.error(f"App command error: {type(error).__name__}: {error}")
    # If the underlying HTTP request failed because the interaction is unknown/expired,
    # just log and return without trying to respond again.
    cause = getattr(error, "__cause__", None)
    if isinstance(cause, HTTPException) and cause.status == 404:
        return
    try:
        msg = "An error occurred while processing that command."
        if isinstance(error, app_commands.MissingPermissions) or isinstance(error, app_commands.CheckFailure):
            msg = "You don't have permission to use this command."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        logging.error(f"Failed to send error response: {e}")

@bot.tree.command(name="ping", description="Simple connectivity check")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong", ephemeral=True)

bot.run(TOKEN)
