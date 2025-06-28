import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import asyncio
import aiohttp
from discord_bot.database import Database, DB_FILE
from discord_bot.ui.views import WelcomeView, RaidControlView

# Compute absolute path to project root .env or .env.local
from pathlib import Path
project_root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dotenv_local = project_root / ".env.local"
dotenv_path = project_root / ".env"
if dotenv_local.exists():
    print(f"DEBUG: Loading .env.local from {dotenv_local}")
    load_dotenv(dotenv_path=dotenv_local)
else:
    print(f"DEBUG: Loading .env from {dotenv_path}")
    load_dotenv(dotenv_path=dotenv_path)


# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')

# --- Load Environment Variables ---
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
LICENSE_KEY = os.getenv("GUILD_LICENSE_KEY")
LICENSE_SERVER_URL = os.getenv("LICENSE_SERVER_URL", "https://dkp-discord-bot-production.up.railway.app")

print('DEBUG: DISCORD_BOT_TOKEN:', os.getenv('DISCORD_BOT_TOKEN'))
print('DEBUG: GUILD_LICENSE_KEY:', os.getenv('GUILD_LICENSE_KEY'))
print('DEBUG: LICENSE_SERVER_URL:', os.getenv('LICENSE_SERVER_URL'))

if not all([TOKEN, LICENSE_KEY, LICENSE_SERVER_URL]):
    raise ValueError("One or more environment variables are missing. Please check your .env file.")

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
        
    async def setup_hook(self):
        # This is called before the bot logs in
        await self.db.connect()
        self.http_session = aiohttp.ClientSession()

        # Load Cogs
        cogs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cogs")
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
        synced = await self.tree.sync()
        logging.info(f"Synced {len(synced)} slash commands.")

    async def close(self):
        await super().close()
        await self.http_session.close()
        await self.db.conn.close()

# --- Run the Bot ---
if __name__ == "__main__":
    bot = DkpBot()
    bot.run(TOKEN)
