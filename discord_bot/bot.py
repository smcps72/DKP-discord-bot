import discord
from discord.ext import commands
import argparse
import os
from dotenv import load_dotenv
import logging
import asyncio
import aiohttp
import sys
from pathlib import Path
from discord import app_commands, HTTPException

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')

# Fix for 'RuntimeError: Event loop is closed' on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- Path Setup ---
# This allows the script to be run from anywhere by adding the project root to the system path.
# This ensures that imports like `from discord_bot.database...` work correctly.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

parser = argparse.ArgumentParser()
parser.add_argument(
    "--bot",
    dest="bot_profile",
    choices=["default", "local2"],
    default=os.getenv("DKP_BOT_PROFILE", "default"),
)
args, _unknown = parser.parse_known_args()
BOT_PROFILE = args.bot_profile

# --- Environment Variable Loading ---
# The bot will look for the .env file in the project root.
dotenv_paths = [
    project_root / "secrets" / ".env.local",
    project_root / ".env.local",
    project_root / ".env",
]

dotenv_loaded = False
for dotenv_path in dotenv_paths:
    if dotenv_path.exists():
        logging.info(f"Loading environment from {dotenv_path}")
        try:
            load_dotenv(dotenv_path=dotenv_path, override=False)
            dotenv_loaded = True
            break
        except Exception as e:
            logging.warning(
                f"Failed to load environment from {dotenv_path}: {e}. Relying on system environment variables."
            )

if not dotenv_loaded:
    logging.warning(
        "No secrets/.env.local, .env.local, or .env file found (or they failed to load). Relying on system environment variables."
    )

from discord_bot.database import Database, DB_FILE
from discord_bot.ui.views import WelcomeView, WelcomeLegacyView, RaidControlView, AuctionOpenPanelView, RaidOpenPanelView, RaidGroupSignupView, GuildBankPanelView
from discord_bot.utils import ensure_allowed_guild, create_info_embed
from discord_bot.analytics import Analytics
from discord_bot import __version__

try:
    resolved_db = str(Path(DB_FILE).expanduser().resolve())
except Exception:
    resolved_db = str(DB_FILE)
logging.info(
    "Bot environment identity: cwd=%s db_file=%s db_file_resolved=%s railway_env=%s railway_service=%s test_guild=%s allowed_guild_ids=%s",
    os.getcwd(),
    str(DB_FILE),
    resolved_db,
    os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("RAILWAY_ENVIRONMENT") or "",
    os.getenv("RAILWAY_SERVICE_NAME") or "",
    os.getenv("TEST_GUILD_ID") or "",
    os.getenv("ALLOWED_GUILD_IDS") or "",
)

# --- Load Environment Variables ---
token_env_var = "DISCORD_BOT_TOKEN"
if BOT_PROFILE == "local2":
    token_env_var = "DKP_local2"
    TOKEN = os.getenv(token_env_var) or os.getenv("DKP_LOCAL2") or os.getenv("LOCAL_2")
else:
    TOKEN = os.getenv(token_env_var)
logging.info("Bot profile selected: %s (token var: %s)", BOT_PROFILE, token_env_var)
LICENSE_KEY = os.getenv("GUILD_LICENSE_KEY")
LICENSE_SERVER_URL = os.getenv("LICENSE_SERVER_URL", "https://dkp-discord-bot-production.up.railway.app")
LICENSE_CHECK_ENABLED = os.getenv("LICENSE_CHECK_ENABLED", "false").lower() == "true"
ALLOWED_GUILD_IDS_ENV = os.getenv("ALLOWED_GUILD_IDS")
ALLOWED_GUILD_IDS: set[int] = set()
if ALLOWED_GUILD_IDS_ENV:
    for raw in ALLOWED_GUILD_IDS_ENV.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ALLOWED_GUILD_IDS.add(int(raw))
        except ValueError:
            logging.warning("Invalid guild id in ALLOWED_GUILD_IDS: %s", raw)
# Optional: limit slash-command sync to a single test guild so changes appear immediately.
TEST_GUILD_ID_ENV = os.getenv("TEST_GUILD_ID")
TEST_GUILD_ID: int | None = None
if TEST_GUILD_ID_ENV:
    try:
        TEST_GUILD_ID = int(TEST_GUILD_ID_ENV)
    except ValueError:
        logging.warning("TEST_GUILD_ID is set but is not a valid integer; falling back to global command sync.")

if not TOKEN:
    raise ValueError(f"{token_env_var} is missing (bot profile: {BOT_PROFILE}). Please check your .env file.")
if LICENSE_CHECK_ENABLED and not all([LICENSE_KEY, LICENSE_SERVER_URL]):
    raise ValueError("GUILD_LICENSE_KEY or LICENSE_SERVER_URL are missing for license check. Please check your .env file or disable license check.")

# --- Bot Class ---
class DkpCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        allowed = await ensure_allowed_guild(interaction)
        if not allowed:
            return False

        try:
            client = getattr(interaction, "client", None)
            analytics = getattr(client, "analytics", None)
            if analytics is not None and getattr(analytics, "enabled", False):
                cmd_name = None
                data = getattr(interaction, "data", None)
                if isinstance(data, dict):
                    cmd_name = data.get("name")
                if not cmd_name:
                    cmd = getattr(interaction, "command", None)
                    cmd_name = getattr(cmd, "qualified_name", None) or getattr(cmd, "name", None)

                guild = getattr(interaction, "guild", None)
                groups = {"guild": str(guild.id)} if guild is not None else None

                analytics.capture(
                    "discord_interaction",
                    distinct_id=str(getattr(interaction.user, "id", "unknown")),
                    properties={
                        "command": cmd_name,
                        "guild_id": getattr(guild, "id", None),
                        "channel_id": getattr(getattr(interaction, "channel", None), "id", None),
                    },
                    groups=groups,
                )
        except Exception:
            logging.exception("Failed to capture analytics event for interaction")

        return True


class DkpBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True  # Required for member info and voice state
        intents.voice_states = True # Required for seeing who is in a VC
        intents.messages = True
        intents.message_content = False # Required for potential future prefix commands

        super().__init__(command_prefix="!", intents=intents, tree_cls=DkpCommandTree)
        self.db = Database(DB_FILE)
        self.license_key = LICENSE_KEY
        self.license_server_url = LICENSE_SERVER_URL
        self.license_check_enabled = LICENSE_CHECK_ENABLED
        self.analytics = Analytics(__version__)
        
    def _cfg_get(self, config, key: str, default=None):
        if not config:
            return default
        try:
            keys = config.keys() if hasattr(config, "keys") else None
            if keys is not None and key in keys:
                return config[key]
        except Exception:
            pass
        try:
            return config.get(key, default)
        except Exception:
            return default

    async def _announce_version_updates(self):
        for guild in list(getattr(self, "guilds", []) or []):
            try:
                config = await self.db.get_guild_config(guild.id)
            except Exception:
                logging.exception("Failed to load guild config for update announcement")
                continue

            dkp_channel_id = self._cfg_get(config, "dkp_channel_id")
            if not dkp_channel_id:
                continue

            last_announced = self._cfg_get(config, "last_announced_version")
            if last_announced == __version__:
                continue

            channel = self.get_channel(int(dkp_channel_id))
            if channel is None:
                try:
                    channel = await guild.fetch_channel(int(dkp_channel_id))
                except Exception:
                    channel = None

            if channel is None or not hasattr(channel, "send"):
                continue

            try:
                embed = create_info_embed(
                    "DKP Bot Updated",
                    f"Now running version: `{__version__}`",
                )
                await channel.send(embed=embed)
                await self.db.execute(
                    "UPDATE guilds SET last_announced_version = ? WHERE guild_id = ?",
                    (__version__, int(guild.id)),
                )
            except Exception:
                logging.exception("Failed to post update announcement for guild_id=%s", getattr(guild, "id", None))
        
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
        self.add_view(WelcomeLegacyView(self))
        self.add_view(RaidControlView(self))
        self.add_view(AuctionOpenPanelView(self))
        self.add_view(RaidOpenPanelView(self))
        self.add_view(RaidGroupSignupView(self))
        self.add_view(GuildBankPanelView(self))
        
        # Sync slash commands
        # In a production bot, you might want to sync only once or on command
        # await self.tree.sync()

    async def on_ready(self):
        logging.info(f'Logged in as {self.user} (ID: {self.user.id})')
        logging.info('------')

        try:
            if getattr(self, "analytics", None) is not None and getattr(self.analytics, "enabled", False):
                self.analytics.capture(
                    "discord_bot_ready",
                    distinct_id=str(getattr(getattr(self, "user", None), "id", "unknown")),
                    properties={
                        "guild_count": len(getattr(self, "guilds", []) or []),
                        "license_check_enabled": bool(getattr(self, "license_check_enabled", False)),
                    },
                )
        except Exception:
            logging.exception("Failed to capture analytics event for on_ready")

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

        try:
            await self._announce_version_updates()
        except Exception:
            logging.exception("Failed during version update announcements")

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

        # Ignore voice state changes that don't involve connecting/moving
        # channels (mute/deafen/stream/video toggles) to prevent duplicate
        # join bookkeeping and join announcements.
        if before.channel is not None and after.channel is not None:
            if getattr(before.channel, "id", None) == getattr(after.channel, "id", None):
                return

        if getattr(member, "bot", False):
            return

        # Auto-add members who join linked raid voice channels once the raid
        # leader has used Update Team at least once for this raid.
        try:
            raid = await self.db.get_raid_by_vc(after.channel.id)
        except Exception:
            raid = None

        if raid:
            try:
                auto_add_enabled = bool(int(raid.get("auto_add_from_vc") if isinstance(raid, dict) else raid["auto_add_from_vc"]))
            except Exception:
                auto_add_enabled = False

            if auto_add_enabled:
                required_role = None
                try:
                    config = await self.db.get_guild_config(int(member.guild.id))
                    if config and ("raider_role_id" in getattr(config, "keys", lambda: [])()):
                        required_role_id = config["raider_role_id"]
                        required_role_id = int(required_role_id) if required_role_id else None
                        required_role = member.guild.get_role(required_role_id) if required_role_id else None
                except Exception:
                    required_role = None

                is_eligible = True
                if required_role is not None:
                    try:
                        is_eligible = required_role in list(getattr(member, "roles", []) or [])
                    except Exception:
                        is_eligible = True

                if is_eligible:
                    raid_id = int(raid["id"])
                    try:
                        if await self.db.is_raid_member_excluded(raid_id, int(member.id)):
                            is_eligible = False
                    except Exception:
                        pass

                if is_eligible:
                    inserted = False
                    try:
                        inserted = await self.db.add_raid_member(int(raid["id"]), int(member.id))
                    except Exception:
                        inserted = False

                    if inserted:
                        try:
                            await self.db.delete_raid_join_request(int(raid["id"]), int(member.id))
                        except Exception:
                            pass

                        thread = None
                        try:
                            thread_id = int(raid["thread_id"])
                        except Exception:
                            thread_id = None

                        if thread_id:
                            try:
                                thread = member.guild.get_thread(thread_id)
                            except Exception:
                                thread = None
                        if thread is None and thread_id:
                            try:
                                resolved = self.get_channel(thread_id)
                                if isinstance(resolved, discord.Thread):
                                    thread = resolved
                            except Exception:
                                thread = None
                        if thread is None and thread_id:
                            try:
                                resolved = await member.guild.fetch_channel(thread_id)
                                if isinstance(resolved, discord.Thread):
                                    thread = resolved
                            except Exception:
                                thread = None

                        if thread is not None:
                            try:
                                await thread.send(
                                    f"{member.mention} joined the raid voice channel and was added to the raid."
                                )
                            except Exception:
                                logging.exception("Failed to announce auto-join in raid thread")

        # Option B: voice-channel activity should not affect raid membership.
        # We only use the raid leader's voice joins to associate their active
        # raid with a voice channel (vc_id) if needed.
        try:
            if member.guild is not None:
                leader_raid = await self.db.get_active_raid_by_leader(member.guild.id, member.id)
            else:
                leader_raid = None
        except Exception as e:
            logging.error(f"Error fetching active raid for leader {member.id}: {e}")
            leader_raid = None

        if leader_raid is None:
            return

        try:
            current_vc_id = leader_raid["vc_id"]
            if not current_vc_id or int(current_vc_id) != int(after.channel.id):
                await self.db.execute(
                    "UPDATE raids SET vc_id = ? WHERE id = ?",
                    (after.channel.id, leader_raid["id"]),
                )
            try:
                await self.db.add_raid_voice_channel(int(leader_raid["id"]), int(after.channel.id))
            except Exception:
                pass
        except Exception as e:
            logging.error(f"Error updating raid vc_id for raid {leader_raid.get('id')}: {e}")
            return

    async def close(self):
        await super().close()
        if hasattr(self, 'http_session'):
            await self.http_session.close()
        if hasattr(self, "db") and getattr(self.db, "pool", None):
            await self.db.pool.close()

        try:
            if getattr(self, "analytics", None) is not None:
                self.analytics.shutdown()
        except Exception:
            logging.exception("Failed to shutdown analytics")

# --- Run the Bot ---
bot = DkpBot()
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logging.error(f"App command error: {type(error).__name__}: {error}")

    try:
        analytics = getattr(getattr(interaction, "client", None), "analytics", None)
        if analytics is not None and getattr(analytics, "enabled", False):
            cmd_name = None
            data = getattr(interaction, "data", None)
            if isinstance(data, dict):
                cmd_name = data.get("name")
            if not cmd_name:
                cmd = getattr(interaction, "command", None)
                cmd_name = getattr(cmd, "qualified_name", None) or getattr(cmd, "name", None)

            guild = getattr(interaction, "guild", None)
            groups = {"guild": str(guild.id)} if guild is not None else None

            analytics.capture(
                "discord_app_command_error",
                distinct_id=str(getattr(interaction.user, "id", "unknown")),
                properties={
                    "command": cmd_name,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "guild_id": getattr(guild, "id", None),
                },
                groups=groups,
            )
    except Exception:
        logging.exception("Failed to capture analytics event for app command error")

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
