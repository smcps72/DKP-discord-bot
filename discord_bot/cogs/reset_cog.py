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
            for role in list(guild.roles):
                try:
                    if role.is_default():
                        skipped_roles.append((role.name, "default role"))
                        continue
                    if role.managed:
                        skipped_roles.append((role.name, "managed role"))
                        continue
                    # Preserve Officer role and assignments
                    try:
                        if 'officer_role_id' in config and role.id == config['officer_role_id']:
                            skipped_roles.append((role.name, "preserved Officer role"))
                            continue
                    except Exception:
                        pass
                    if role.name == "Officer":
                        skipped_roles.append((role.name, "preserved Officer role (by name)"))
                        continue
                    if role.permissions.administrator:
                        skipped_roles.append((role.name, "administrator role"))
                        continue
                    await role.delete(reason="DKP Bot Reset: remove all roles except admin")
                    deleted_roles.append(role.name)
                    logging.info(f"Deleted role {role.name} ({role.id})")
                except discord.Forbidden:
                    skipped_roles.append((role.name, "insufficient permissions / role above bot"))
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
            if skipped_roles:
                preview = "\n".join([f"- {name}: {reason}" for name, reason in skipped_roles[:10]])
                if len(skipped_roles) > 10:
                    preview += f"\n... and {len(skipped_roles) - 10} more"
                summary += "Roles skipped (first 10):\n" + preview
            await interaction.followup.send(summary + "\nYou can run `/setup_dkp` again when ready.", ephemeral=True)

        except discord.Forbidden:
            logging.error(f"Reset failed for {guild.name}: Bot lacks permissions.")
            await interaction.followup.send("The bot lacks permissions to delete required roles/channels. Please check its permissions.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error during reset for {guild.name}: {e}", exc_info=True)
            await interaction.followup.send(f"An unexpected error occurred during the reset process. Please check the logs.", ephemeral=True)

async def setup(bot: commands.Bot):
    """Standard setup function to load the cog."""
    await bot.add_cog(ResetCog(bot))
