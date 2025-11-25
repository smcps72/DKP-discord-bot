import discord
from discord.ext import commands
from discord import app_commands
import logging

class ResetCog(commands.Cog):
    """A cog for resetting the bot's configuration on a server."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="reset", description="Resets the DKP bot's configuration on this server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset(self, interaction: discord.Interaction):
        """Allows an admin to wipe the bot's configuration and channels."""
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        # Access the database instance from the bot object.
        # This assumes the database object is attached to the bot instance as 'db'.
        if not hasattr(self.bot, 'db'):
            logging.error("Database instance not found on bot object. Cannot perform reset.")
            await interaction.followup.send("A critical error occurred: Database connection not found.", ephemeral=True)
            return

        db = self.bot.db
        config = await db.get_guild_config(guild.id)
        
        if not config:
            await interaction.followup.send("The bot has not been set up on this server yet.", ephemeral=True)
            return

        try:
            logging.info(f"Starting reset for guild: {guild.name} ({guild.id})")

            # Helper to safely delete channels/roles
            async def safe_delete(item_id, get_method, item_type):
                if item_id:
                    item = get_method(item_id)
                    if item is not None:
                        await item.delete(reason="DKP Bot Reset")
                        logging.info(f"Deleted {item_type} {item.name} ({item_id})")

            # Remove all roles except admin roles and @everyone. Skip managed roles.
            # Requires the bot's top role to be above roles it tries to delete.
            deleted_roles = []
            skipped_roles = []  # tuples of (name, reason)
            # Known DKP role names to force-delete (case-insensitive)
            # These will be deleted even if they have administrator permissions,
            # as long as the bot's top role is high enough.
            dkp_role_names = {"officer", "raider", "raid-leader", "raid leader"}

            # Determine the bot member and top role position for diagnostics
            bot_member = guild.get_member(self.bot.user.id) if self.bot.user else None
            bot_top_pos = bot_member.top_role.position if bot_member and bot_member.top_role else None

            for role in list(guild.roles):
                try:
                    if role.is_default():
                        skipped_roles.append((role.name, "default role"))
                        continue
                    if role.managed:
                        skipped_roles.append((role.name, "managed role"))
                        continue
                    # Allow forced deletion for known DKP roles even if they have admin perms
                    normalized_name = role.name.lower()
                    if role.permissions.administrator and normalized_name not in dkp_role_names:
                        # Skip true admin roles
                        reason = "administrator role"
                        if bot_top_pos is not None:
                            reason += f" (role_pos={role.position}, bot_top_pos={bot_top_pos})"
                        skipped_roles.append((role.name, reason))
                        continue
                    await role.delete(reason="DKP Bot Reset: remove all roles except admin")
                    deleted_roles.append(role.name)
                    logging.info(f"Deleted role {role.name} ({role.id})")
                except discord.Forbidden:
                    reason = "insufficient permissions / role above bot"
                    if bot_top_pos is not None:
                        reason += f" (role_pos={role.position}, bot_top_pos={bot_top_pos})"
                    skipped_roles.append((role.name, reason))
                    logging.warning(f"Insufficient permissions to delete role {role.name} ({role.id})")
                except Exception as e:
                    skipped_roles.append((role.name, f"error: {e}"))
                    logging.error(f"Error deleting role {role.name} ({role.id}): {e}")

            # Delete Discord entities using correct names from database.py
            await safe_delete(config['dkp_channel_id'], guild.get_channel, "channel")
            await safe_delete(config['raid_channel_id'], guild.get_channel, "channel")
            await safe_delete(config['dkp_category_id'], guild.get_channel, "category")
            # Officer role is preserved intentionally (role object and assignments)
            await safe_delete(config['raider_role_id'], guild.get_role, "role")
            # Also try to delete raid leader role by ID if present
            if 'raid_leader_role_id' in config:
                await safe_delete(config['raid_leader_role_id'], guild.get_role, "role")
            await safe_delete(config['raid_vc_template_id'], guild.get_channel, "channel")

            # Additionally, clean up any legacy "Raid-Template" voice channels that might not
            # be referenced by the current guild config. Older versions of the bot created
            # this template; the current design no longer uses it.
            for vc in list(guild.voice_channels):
                if vc.name.lower() == "raid-template":
                    try:
                        await vc.delete(reason="DKP Bot Reset: remove legacy Raid-Template voice channel")
                        logging.info(f"Deleted legacy Raid-Template voice channel {vc.name} ({vc.id})")
                    except discord.Forbidden:
                        logging.warning("Failed to delete legacy Raid-Template voice channel due to permissions.")
                    except Exception as e:
                        logging.warning(f"Error deleting legacy Raid-Template voice channel: {e}")

            # Delete from all database tables for a full, clean reset.
            logging.info(f"Deleting database entries for guild {guild.id}")
            await db.execute("DELETE FROM auctions WHERE raid_id IN (SELECT id FROM raids WHERE guild_id = ?)", (guild.id,))
            await db.execute("DELETE FROM raids WHERE guild_id = ?", (guild.id,))
            await db.execute("DELETE FROM transactions WHERE guild_id = ?", (guild.id,))
            await db.execute("DELETE FROM users WHERE guild_id = ?", (guild.id,))
            await db.execute("DELETE FROM guilds WHERE guild_id = ?", (guild.id,))
            logging.info(f"Finished deleting database entries for guild {guild.id}")

            # Compose summary
            summary = (
                f"Reset complete. Deleted roles: {len(deleted_roles)}. "
                f"Skipped roles: {len(skipped_roles)}.\n"
            )
            if bot_top_pos is not None:
                summary += f"Bot top role position: {bot_top_pos}.\n"
            if skipped_roles:
                preview = "\n".join([f"- {name}: {reason}" for name, reason in skipped_roles[:10]])
                if len(skipped_roles) > 10:
                    preview += f"\n... and {len(skipped_roles) - 10} more"
                summary += "Roles skipped (first 10):\n" + preview

            try:
                await interaction.followup.send(
                    summary + "\nYou can run `/setup_dkp` again when ready.",
                    ephemeral=True,
                )
            except (discord.NotFound, discord.HTTPException):
                # Interaction or underlying webhook message may have expired or been deleted.
                logging.warning("Reset completed but could not send summary (interaction expired or unknown message).")

        except discord.Forbidden:
            logging.error(f"Reset failed for {guild.name}: Bot lacks permissions.")
            try:
                await interaction.followup.send(
                    "The bot lacks permissions to delete required roles/channels. Please check its permissions.",
                    ephemeral=True,
                )
            except (discord.NotFound, discord.HTTPException):
                logging.warning("Could not send reset permissions error because the interaction is no longer valid.")
        except Exception as e:
            logging.error(f"Error during reset for {guild.name}: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "An unexpected error occurred during the reset process. Please check the logs.",
                    ephemeral=True,
                )
            except (discord.NotFound, discord.HTTPException):
                logging.warning("Could not send reset error message because the interaction is no longer valid.")

async def setup(bot: commands.Bot):
    """Standard setup function to load the cog."""
    await bot.add_cog(ResetCog(bot))
