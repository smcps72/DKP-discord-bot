import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
import shutil
import io
import zipfile
from datetime import datetime, timezone

from ..utils import is_admin

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
            # Use a filesystem-safe timestamp format (no colons) so it can be used
            # in both filenames and directory names on Windows.
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

    async def _post_backup_record_to_archive(
        self,
        guild: discord.Guild,
        config: dict,
        backup_id: str,
        backup_path: str,
    ) -> None:
        """Post a persistent record of the reset backup into the archive.

        This is the primary way to associate backups with the completed-raids
        history across multiple resets, since the DB is wiped on reset but the
        archive category is preserved.
        """
        try:
            completed_channel = None
            completed_id = None
            try:
                completed_id = (
                    config.get("completed_raid_channel_id")
                    if isinstance(config, dict)
                    else None
                )
            except Exception:
                completed_id = None

            if completed_id:
                ch = guild.get_channel(completed_id)
                if isinstance(ch, discord.TextChannel):
                    completed_channel = ch

            if completed_channel is None:
                # Fall back by name/category
                archive_category = None
                for cat in getattr(guild, "categories", []) or []:
                    if (getattr(cat, "name", "") or "").lower() == "dkp-archive":
                        archive_category = cat
                        break
                for ch in getattr(guild, "text_channels", []) or []:
                    if (getattr(ch, "name", "") or "").lower() != "completed-raids":
                        continue
                    if archive_category is not None and getattr(ch, "category_id", None) != getattr(archive_category, "id", None):
                        continue
                    completed_channel = ch
                    break

            if completed_channel is None:
                return

            file_name = os.path.basename(backup_path) if backup_path else "(unknown)"
            await completed_channel.send(
                f"Reset backup created. backup_id=`{backup_id}` file=`{file_name}`\n"
                f"Use `/restore_backup backup_id:{backup_id} confirm:true` to restore, or `/list_backups` to list all backups."
            )
        except Exception:
            logging.exception("Failed to post reset backup record to archive")

    @app_commands.command(name="reset", description="Resets the DKP bot's configuration on this server.")
    @app_commands.check(is_admin)
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
        # Normalize to a plain dict so newer code can safely use .get().
        if config:
            try:
                config = dict(config)
            except Exception:
                pass

        # For safety, do not allow /reset to run from within the DKP-System
        # category or its primary channels, since those may be deleted as part
        # of the reset while the command is running.
        channel = interaction.channel
        if config and isinstance(channel, (discord.TextChannel, discord.Thread)):
            dkp_category_id = config['dkp_category_id']
            dkp_channel_id = config['dkp_channel_id']
            raid_channel_id = config['raid_channel_id']
            archive_category_id = config['archive_category_id'] if 'archive_category_id' in config.keys() else None
            completed_raid_channel_id = (
                config['completed_raid_channel_id'] if 'completed_raid_channel_id' in config.keys() else None
            )

            in_dkp_category = getattr(channel, 'category_id', None) == dkp_category_id
            in_archive_category = (
                archive_category_id is not None and getattr(channel, 'category_id', None) == archive_category_id
            )
            is_dkp_channel = channel.id in (dkp_channel_id, raid_channel_id)
            is_archive_channel = completed_raid_channel_id is not None and channel.id == completed_raid_channel_id

            if in_dkp_category or is_dkp_channel or in_archive_category or is_archive_channel:
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
            # Match the filesystem-safe format used in _backup_database so the
            # DB backup and thread exports share the same backup_id.
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

            # Persistently record the backup in the archive so the backup history
            # survives multiple resets.
            try:
                await self._post_backup_record_to_archive(guild, config, reset_timestamp, backup_path)
            except Exception:
                logging.exception("Failed while recording backup into archive")

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

            def _channel_in_category(ch, category_id: int | None) -> bool:
                try:
                    return category_id is not None and getattr(ch, "category_id", None) == category_id
                except Exception:
                    return False

            def _is_category_channel(ch) -> bool:
                return isinstance(ch, discord.CategoryChannel) or (
                    ch is not None and hasattr(ch, "text_channels") and hasattr(ch, "delete")
                )

            async def safe_delete_dkp_channel(item_id, expected_names: set[str] | None = None):
                """Delete a channel only if it appears to be DKP-owned."""
                if not item_id:
                    return
                ch = guild.get_channel(item_id)
                if ch is None:
                    return

                dkp_category_id = config.get("dkp_category_id") if isinstance(config, dict) else None
                if _channel_in_category(ch, dkp_category_id):
                    await ch.delete(reason="DKP Bot Reset")
                    logging.info(f"Deleted channel {getattr(ch, 'name', '')} ({item_id})")
                    return

                if expected_names is not None:
                    name = (getattr(ch, "name", "") or "").lower()
                    if name in {n.lower() for n in expected_names}:
                        await ch.delete(reason="DKP Bot Reset")
                        logging.info(f"Deleted channel {getattr(ch, 'name', '')} ({item_id})")

            # Remove all roles except admin roles, @everyone, and the configured
            # Officer role. Reset should only affect DKP-owned roles; do not
            # touch unrelated guild roles.
            deleted_roles = []
            skipped_roles = []  # tuples of (name, reason)

            # Determine the bot member and top role position for diagnostics
            bot_member = guild.get_member(self.bot.user.id) if self.bot.user else None
            bot_top_pos = bot_member.top_role.position if bot_member and bot_member.top_role else None

            # Delete Discord entities for the *active* raids category only.
            # Archive (DKP-archive and #completed-raids) is intentionally preserved.
            await safe_delete_dkp_channel(config.get('dkp_channel_id'), expected_names={"dkp-system"})
            await safe_delete_dkp_channel(config.get('raid_channel_id'), expected_names={"active-raids"})

            # Only delete the active category if it looks like the DKP category.
            dkp_category = guild.get_channel(config.get('dkp_category_id')) if config.get('dkp_category_id') else None
            if _is_category_channel(dkp_category):
                if (getattr(dkp_category, "name", "") or "").lower() in {"dkp-active-raids", "dkp-system"}:
                    await dkp_category.delete(reason="DKP Bot Reset")
                    logging.info(
                        f"Deleted category {getattr(dkp_category, 'name', '')} ({getattr(dkp_category, 'id', None)})"
                    )
            # Officer role is preserved intentionally (role object and assignments)
            await safe_delete(config.get('raider_role_id'), guild.get_role, "role")
            if config.get('raider_role_id'):
                deleted_roles.append("Raider")
            # Also try to delete raid leader role by ID if present
            if config.get('raid_leader_role_id'):
                await safe_delete(config.get('raid_leader_role_id'), guild.get_role, "role")
                deleted_roles.append("Raid-Leader")

            # Only delete the legacy template VC if it is inside the DKP category.
            raid_vc_template_id = config.get('raid_vc_template_id') if isinstance(config, dict) else None
            if raid_vc_template_id:
                vc = guild.get_channel(raid_vc_template_id)
                if isinstance(vc, discord.VoiceChannel):
                    if _channel_in_category(vc, config.get('dkp_category_id')) and (vc.name or "").lower() == "raid-template":
                        await vc.delete(reason="DKP Bot Reset: remove legacy Raid-Template voice channel")
                        logging.info(f"Deleted legacy Raid-Template voice channel {vc.name} ({vc.id})")

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
            summary += f"Backup saved as backup_id={reset_timestamp}.\n"
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
    @app_commands.check(is_admin)
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

            def _parse_ts(ts: str):
                for fmt in ("%d-%m-%Y %H:%M:%S", "%Y%m%d-%H%M%S"):
                    try:
                        return datetime.strptime(ts, fmt)
                    except ValueError:
                        continue
                return datetime.min

            entries = sorted(timestamps, key=_parse_ts, reverse=True)
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
    @app_commands.check(is_admin)
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
