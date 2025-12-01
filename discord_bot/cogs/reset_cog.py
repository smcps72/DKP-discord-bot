import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
import shutil
import io
import zipfile
from datetime import datetime, timezone

class ResetCog(commands.Cog):
    """A cog for resetting the bot's configuration on a server."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _backup_database(self, guild_id: int, timestamp: str | None = None) -> str:
        """Create a backup copy of the SQLite database file.

        Returns the path to the *flat* backup file on success. Raises on failure.
        If a timestamp is provided, it will also place a copy into a
        backups/<timestamp>/ folder so that other artifacts (like thread
        exports) can be grouped with the same reset operation.
        """
        # Expect the Database instance to expose the DB file path via db_file
        db = getattr(self.bot, "db", None)
        if db is None or not hasattr(db, "db_file"):
            raise RuntimeError("Database instance or db_file attribute not found on bot.")

        source_path = db.db_file
        # Store backups in a "backups" folder next to the primary DB file
        base_dir = os.path.dirname(os.path.abspath(source_path)) or "."
        backup_dir = os.getenv("DKP_DB_BACKUP_DIR") or os.path.join(base_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        if timestamp is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_filename = f"dkp_bot_backup_guild_{guild_id}_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_filename)

        # Also place a copy inside a timestamped subfolder so DB and thread
        # exports can be grouped together logically.
        timestamp_folder = os.path.join(backup_dir, timestamp)
        os.makedirs(timestamp_folder, exist_ok=True)
        backup_path_in_folder = os.path.join(timestamp_folder, backup_filename)

        # Copy the live SQLite file. This gives us a simple snapshot of the DB.
        shutil.copy2(source_path, backup_path)
        try:
            shutil.copy2(source_path, backup_path_in_folder)
        except Exception as folder_err:
            logging.warning(f"Failed to copy DB backup into timestamp folder: {folder_err}")

        logging.info(f"Created database backup for guild {guild_id} at {backup_path}")
        return backup_path

    async def _export_raid_threads_for_guild(self, guild: discord.Guild, timestamp: str) -> None:
        """Export all raid threads for this guild into the timestamped backup folder.

        Uses ExportCog's internal helpers so that thread ZIPs have the same
        structure as /export_thread exports. Failures are logged but do not
        abort the reset process.
        """
        db = getattr(self.bot, "db", None)
        if db is None or not hasattr(db, "db_file"):
            logging.error("Cannot export raid threads: database instance or db_file missing on bot.")
            return

        # Determine the same backup root and timestamp folder used by _backup_database
        source_path = db.db_file
        base_dir = os.path.dirname(os.path.abspath(source_path)) or "."
        backup_root = os.getenv("DKP_DB_BACKUP_DIR") or os.path.join(base_dir, "backups")
        os.makedirs(backup_root, exist_ok=True)
        ts_folder = os.path.join(backup_root, timestamp)
        os.makedirs(ts_folder, exist_ok=True)

        try:
            rows = await db.fetchall("SELECT thread_id FROM raids WHERE guild_id = ?", (guild.id,))
        except Exception as e:
            logging.error(f"Failed to query raid threads for guild {guild.id}: {e}", exc_info=True)
            return

        thread_ids = {row["thread_id"] for row in rows if row["thread_id"]}
        if not thread_ids:
            logging.info(f"No raid threads found to export for guild {guild.id}.")
            return

        export_cog = self.bot.get_cog("ExportCog")
        if export_cog is None:
            logging.warning("ExportCog is not loaded; skipping raid thread exports during reset.")
            return

        for thread_id in thread_ids:
            try:
                # Try to resolve the thread from cache
                thread = self.bot.get_channel(thread_id)
                if not isinstance(thread, discord.Thread):
                    logging.warning(f"Raid thread {thread_id} not found or not a Thread object; skipping.")
                    continue

                messages = await export_cog._gather_thread(thread)
                md_text = export_cog._build_markdown(thread, messages)
                csv_bytes = export_cog._build_csv(messages)

                bio = io.BytesIO()
                with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr("thread.md", md_text.encode())
                    zf.writestr("thread.csv", csv_bytes)
                    zf.writestr(
                        "meta.txt",
                        (
                            f"thread_id={thread.id}\n"
                            f"thread_name={thread.name}\n"
                            f"exported_at={datetime.now(timezone.utc).isoformat()}\n"
                        ),
                    )
                    await export_cog._download_attachments_into_zip(zf, messages)

                bio.seek(0)
                local_name = f"thread_export_guild_{guild.id}_thread_{thread.id}_{timestamp}.zip"
                local_path = os.path.join(ts_folder, local_name)
                with open(local_path, "wb") as f:
                    f.write(bio.getvalue())
                logging.info(f"Exported raid thread {thread.id} for guild {guild.id} to {local_path}")
            except Exception as e:
                logging.error(f"Failed to export raid thread {thread_id} for guild {guild.id}: {e}", exc_info=True)

    @app_commands.command(name="reset", description="Resets the DKP bot's configuration on this server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset(self, interaction: discord.Interaction):
        """Allows an admin to wipe the bot's configuration and channels."""
        guild = interaction.guild

        # Access the database instance from the bot object.
        # This assumes the database object is attached to the bot instance as 'db'.
        if not hasattr(self.bot, 'db'):
            logging.error("Database instance not found on bot object. Cannot perform reset.")
            await interaction.response.send_message("A critical error occurred: Database connection not found.", ephemeral=True)
            return

        db = self.bot.db
        config = await db.get_guild_config(guild.id)

        # For safety, do not allow /reset to run from within the DKP-System
        # category or its primary channels, since those may be deleted as part
        # of the reset while the command is running.
        channel = interaction.channel
        if config and isinstance(channel, (discord.TextChannel, discord.Thread)):
            dkp_category_id = config['dkp_category_id']
            dkp_channel_id = config['dkp_channel_id']
            raid_channel_id = config['raid_channel_id']

            in_dkp_category = getattr(channel, 'category_id', None) == dkp_category_id
            is_dkp_channel = channel.id in (dkp_channel_id, raid_channel_id)

            if in_dkp_category or is_dkp_channel:
                await interaction.response.send_message(
                    "For safety, please run `/reset` in a non-DKP channel such as #general.",
                    ephemeral=True,
                )
                return

        await interaction.response.defer(ephemeral=True)
        
        if not config:
            await interaction.followup.send("The bot has not been set up on this server yet.", ephemeral=True)
            return

        try:
            logging.info(f"Starting reset for guild: {guild.name} ({guild.id})")

            # Use a single shared timestamp for this reset operation so that the
            # DB snapshot and any raid thread exports are grouped together.
            reset_timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

            # First, back up the current database before making any destructive changes.
            try:
                backup_path = await self._backup_database(guild.id, timestamp=reset_timestamp)
                logging.info(f"Database backup completed for guild {guild.id}: {backup_path}")
            except Exception as backup_err:
                logging.error(f"Failed to back up database for guild {guild.id}: {backup_err}", exc_info=True)
                await interaction.followup.send(
                    "Reset aborted because the database backup step failed. Please check the bot logs.",
                    ephemeral=True,
                )
                return

            # Next, try to export any raid threads for this guild into the same
            # timestamped backup folder. Failures here are logged but do not
            # abort the reset since the DB snapshot has already been taken.
            try:
                await self._export_raid_threads_for_guild(guild, reset_timestamp)
            except Exception as export_err:
                logging.error(f"Error while exporting raid threads during reset for guild {guild.id}: {export_err}", exc_info=True)

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

    @app_commands.command(name="list_backups", description="Lists database backup IDs (timestamps) for this server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_backups(self, interaction: discord.Interaction):
        guild = interaction.guild

        if not hasattr(self.bot, "db"):
            logging.error("Database instance not found on bot object. Cannot list backups.")
            await interaction.response.send_message("A critical error occurred: Database connection not found.", ephemeral=True)
            return

        db = self.bot.db
        source_path = getattr(db, "db_file", None)
        if not source_path:
            await interaction.response.send_message("Database file path is not configured.", ephemeral=True)
            return

        base_dir = os.path.dirname(os.path.abspath(source_path)) or "."
        backup_dir = os.getenv("DKP_DB_BACKUP_DIR") or os.path.join(base_dir, "backups")

        try:
            timestamps = set()
            if os.path.isdir(backup_dir):
                prefix = f"dkp_bot_backup_guild_{guild.id}_"
                for name in os.listdir(backup_dir):
                    if name.startswith(prefix) and name.endswith(".db"):
                        # Extract the timestamp portion between prefix and .db
                        ts = name[len(prefix):-3]
                        if ts:
                            timestamps.add(ts)

            if not timestamps:
                await interaction.response.send_message("No backups found for this server.", ephemeral=True)
                return

            entries = sorted(timestamps, reverse=True)
            preview = entries[:10]
            lines = [f"{i+1}. {ts}" for i, ts in enumerate(preview)]
            extra = ""
            if len(entries) > len(preview):
                extra = f"\n... and {len(entries) - len(preview)} more"

            message = (
                "Backup IDs for this server (newest first):\n" +
                "\n".join(lines) +
                "\n\nUse one of these timestamps as the backup_id with /restore_backup."
                + extra
            )
            await interaction.response.send_message(message, ephemeral=True)
        except Exception as e:
            logging.error(f"Error listing backups for guild {guild.id}: {e}", exc_info=True)
            await interaction.response.send_message("Failed to list backups. Please check the logs.", ephemeral=True)

    @app_commands.command(name="restore_backup", description="Restores the database from a backup ID (timestamp) for this server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def restore_backup(self, interaction: discord.Interaction, backup_id: str, confirm: bool):
        guild = interaction.guild

        if not hasattr(self.bot, "db"):
            logging.error("Database instance not found on bot object. Cannot restore backup.")
            await interaction.response.send_message("A critical error occurred: Database connection not found.", ephemeral=True)
            return
        
        if not confirm:
            await interaction.response.send_message(
                "This is a destructive operation that overwrites the live database. "
                "Re-run the command with `confirm: true` to proceed.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        db = self.bot.db
        source_path = getattr(db, "db_file", None)
        if not source_path:
            await interaction.followup.send("Database file path is not configured.", ephemeral=True)
            return

        base_dir = os.path.dirname(os.path.abspath(source_path)) or "."
        backup_dir = os.getenv("DKP_DB_BACKUP_DIR") or os.path.join(base_dir, "backups")

        try:
            if not os.path.isdir(backup_dir):
                await interaction.followup.send("No backups directory exists.", ephemeral=True)
                return

            # backup_id is expected to be the timestamp portion used in the filename.
            # Reconstruct the DB backup filename from the guild ID and backup_id.
            prefix = f"dkp_bot_backup_guild_{guild.id}_"
            if not backup_id:
                await interaction.followup.send("You must provide a valid backup_id (timestamp).", ephemeral=True)
                return

            backup_filename = f"{prefix}{backup_id}.db"
            backup_path = os.path.join(backup_dir, backup_filename)
            if not os.path.isfile(backup_path):
                await interaction.followup.send("Specified backup_id was not found for this server.", ephemeral=True)
                return

            try:
                if getattr(db, "pool", None) is not None:
                    await db.pool.close()
                    db.pool = None
            except Exception as close_err:
                logging.warning(f"Error closing database connection before restore: {close_err}")

            shutil.copy2(backup_path, source_path)

            try:
                await db.connect()
            except Exception as reconnect_err:
                logging.error(f"Error reconnecting to database after restore: {reconnect_err}", exc_info=True)
                await interaction.followup.send(
                    "Copied backup file, but failed to reconnect to the database. Please restart the bot.",
                    ephemeral=True,
                )
                return

            logging.info(f"Restored database for guild {guild.id} from backup {backup_path}")

            # After restoring the DB, attempt to (re)run DKP setup to recreate any missing
            # channels or categories according to the restored configuration.
            setup_cog = self.bot.get_cog("SetupCog")
            if setup_cog is not None and hasattr(setup_cog, "run_setup"):
                try:
                    await setup_cog.run_setup(guild, interaction=None)
                except Exception as setup_err:
                    logging.error(f"Error running SetupCog.run_setup after restore: {setup_err}", exc_info=True)

            # Next, try to restore any raid thread exports that were saved for this backup
            # ID into the active-raids channel. Failures here are logged but do not abort
            # the overall restore operation.
            try:
                config = await db.get_guild_config(guild.id)
                raid_channel = None
                if config and "raid_channel_id" in config.keys():
                    raid_channel = guild.get_channel(config["raid_channel_id"])

                if isinstance(raid_channel, discord.TextChannel):
                    export_cog = self.bot.get_cog("ExportCog")
                    if export_cog is not None:
                        ts_folder = os.path.join(backup_dir, backup_id)
                        if os.path.isdir(ts_folder):
                            prefix = f"thread_export_guild_{guild.id}_"
                            for name in sorted(os.listdir(ts_folder)):
                                if not (name.startswith(prefix) and name.endswith(".zip")):
                                    continue
                                zip_path = os.path.join(ts_folder, name)
                                try:
                                    with zipfile.ZipFile(zip_path, mode="r") as zf:
                                        meta = export_cog._read_meta(zf)
                                        desired_name = meta.get("thread_name") or f"Restored Raid {backup_id}"

                                        seed = await raid_channel.send(f"Restoring raid thread from backup {backup_id}: {desired_name}")
                                        thread = await seed.create_thread(name=desired_name)

                                        # Iterate CSV rows: [timestamp, author_id, author_name, content, attachments]
                                        async def build_files(att_field: str) -> list[discord.File]:
                                            files: list[discord.File] = []
                                            att_field = (att_field or "").strip()
                                            if not att_field:
                                                return files
                                            parts = [p for p in att_field.split(";") if p]
                                            for p in parts:
                                                data = export_cog._load_attachment_bytes(zf, p)
                                                if data is None:
                                                    continue
                                                files.append(discord.File(io.BytesIO(data), filename=os.path.basename(p)))
                                            return files

                                        sent = 0
                                        for row in export_cog._iter_csv_rows(zf):
                                            if len(row) < 5:
                                                continue
                                            _ts, _author_id, _author_name, content, att_field = row
                                            files = await build_files(att_field)

                                            # Discord rejects completely empty messages; if there is no
                                            # text content and no attachments for this row, skip it.
                                            if (not (content or "").strip()) and not files:
                                                continue

                                            await export_cog._send_message_with_attachments(thread, content, files)
                                            sent += 1
                                        logging.info(f"Restored raid thread from {zip_path} with {sent} messages into guild {guild.id}")
                                except Exception as thread_err:
                                    logging.error(f"Failed to restore raid thread from {zip_path} for guild {guild.id}: {thread_err}", exc_info=True)
                    else:
                        logging.warning("ExportCog is not loaded; skipping automatic raid thread restore.")
                else:
                    logging.warning("Raid channel not found after restore; skipping automatic raid thread restore.")
            except Exception as import_err:
                logging.error(f"Error while restoring raid threads for guild {guild.id}: {import_err}", exc_info=True)

            await interaction.followup.send(
                "Database restored from backup successfully. If channels or roles were missing, "
                "they have been checked and recreated where possible. Any saved raid logs for this "
                "backup have also been replayed into the active-raids channel when possible.",
                ephemeral=True,
            )
        except Exception as e:
            logging.error(f"Error restoring backup for guild {guild.id}: {e}", exc_info=True)
            await interaction.followup.send("Failed to restore backup. Please check the logs.", ephemeral=True)

async def setup(bot: commands.Bot):
    """Standard setup function to load the cog."""
    await bot.add_cog(ResetCog(bot))
