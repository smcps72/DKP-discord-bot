import discord
from discord.ext import commands
from discord import app_commands
import io
import csv
import zipfile
from datetime import datetime, timezone
import os
import asyncio

from ..utils import is_officer

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}

class ExportCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _is_image(self, attachment: discord.Attachment) -> bool:
        name = attachment.filename.lower()
        _, ext = os.path.splitext(name)
        if attachment.content_type and attachment.content_type.startswith("image/"):
            return True
        return ext in IMAGE_EXTS

    async def _gather_thread(self, thread: discord.Thread):
        messages = []
        async for msg in thread.history(limit=None, oldest_first=True):
            attachments = []
            for a in msg.attachments:
                attachments.append({
                    "id": a.id,
                    "filename": a.filename,
                    "url": a.url,
                    "is_image": self._is_image(a),
                    "size": a.size,
                    "content_type": a.content_type or ""
                })
            messages.append({
                "id": msg.id,
                "author_id": msg.author.id if msg.author else None,
                "author_name": getattr(msg.author, "display_name", str(msg.author)) if msg.author else "Unknown",
                "timestamp": msg.created_at.replace(tzinfo=timezone.utc).isoformat(),
                "content": msg.clean_content or "",
                "attachments": attachments
            })
        return messages

    async def _gather_channel(self, channel: discord.TextChannel):
        """Gather full message history from a text channel.

        Structure matches _gather_thread so that downstream exporters can reuse
        the same markdown/CSV builders.
        """
        messages = []
        async for msg in channel.history(limit=None, oldest_first=True):
            attachments = []
            for a in msg.attachments:
                attachments.append({
                    "id": a.id,
                    "filename": a.filename,
                    "url": a.url,
                    "is_image": self._is_image(a),
                    "size": a.size,
                    "content_type": a.content_type or ""
                })
            messages.append({
                "id": msg.id,
                "author_id": msg.author.id if msg.author else None,
                "author_name": getattr(msg.author, "display_name", str(msg.author)) if msg.author else "Unknown",
                "timestamp": msg.created_at.replace(tzinfo=timezone.utc).isoformat(),
                "content": msg.clean_content or "",
                "attachments": attachments,
            })
        return messages

    def _build_markdown(self, thread: discord.Thread, messages: list) -> str:
        lines = []
        header = f"# Thread Export: {thread.name}\n\n"
        lines.append(header)
        lines.append(f"Thread ID: {thread.id}\n")
        lines.append(f"Channel: #{getattr(thread.parent, 'name', 'unknown')}\n")
        lines.append("\n---\n\n")
        for m in messages:
            ts = m["timestamp"]
            author = m["author_name"]
            content = m["content"].replace("\r\n", "\n").replace("\r", "\n")
            lines.append(f"[{ts}] {author}:\n")
            if content:
                lines.append(content + "\n")
            for a in m["attachments"]:
                fn = f"attachments/{a['id']}_{a['filename']}"
                if a["is_image"]:
                    lines.append(f"![]({fn})\n")
                else:
                    lines.append(f"Attachment: {fn}\n")
            lines.append("\n")
        return "".join(lines)

    def _build_channel_markdown(self, channel: discord.TextChannel, messages: list) -> str:
        lines = []
        header = f"# Channel Export: #{channel.name}\n\n"
        lines.append(header)
        lines.append(f"Channel ID: {channel.id}\n")
        lines.append("\n---\n\n")
        for m in messages:
            ts = m["timestamp"]
            author = m["author_name"]
            content = m["content"].replace("\r\n", "\n").replace("\r", "\n")
            lines.append(f"[{ts}] {author}:\n")
            if content:
                lines.append(content + "\n")
            for a in m["attachments"]:
                fn = f"attachments/{a['id']}_{a['filename']}"
                if a["is_image"]:
                    lines.append(f"![]({fn})\n")
                else:
                    lines.append(f"Attachment: {fn}\n")
            lines.append("\n")
        return "".join(lines)

    def _build_csv(self, messages: list) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["timestamp", "author_id", "author_name", "content", "attachments"]) 
        for m in messages:
            att_list = ";".join([f"{a['id']}_{a['filename']}" for a in m["attachments"]])
            writer.writerow([
                m["timestamp"],
                m["author_id"],
                m["author_name"],
                m["content"].replace("\n", " ").strip(),
                att_list,
            ])
        return buf.getvalue().encode()

    async def _download_attachments_into_zip(self, zf: zipfile.ZipFile, messages: list):
        session = getattr(self.bot, "http_session", None)
        if session is None:
            return
        for m in messages:
            for a in m["attachments"]:
                path_in_zip = f"attachments/{a['id']}_{a['filename']}"
                try:
                    async with session.get(a["url"]) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            zf.writestr(path_in_zip, data)
                except Exception:
                    continue

    @app_commands.command(name="export_thread", description="Export this thread to a ZIP (Markdown + CSV + attachments).")
    @app_commands.checks.has_permissions(administrator=True)
    async def export_thread_cmd(self, interaction: discord.Interaction, thread: discord.Thread | None = None):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        target = thread if thread else interaction.channel
        if not isinstance(target, discord.Thread):
            return await interaction.followup.send("Use this in a thread or provide a thread option.", ephemeral=True)

        messages = await self._gather_thread(target)
        md_text = self._build_markdown(target, messages)
        csv_bytes = self._build_csv(messages)

        bio = io.BytesIO()
        with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("thread.md", md_text.encode())
            zf.writestr("thread.csv", csv_bytes)
            zf.writestr("meta.txt", f"thread_id={target.id}\nthread_name={target.name}\nexported_at={datetime.now(timezone.utc).isoformat()}\n")
            await self._download_attachments_into_zip(zf, messages)
        bio.seek(0)
        filename = f"thread_export_{target.id}.zip"

        # Save a local copy into the backups directory so that thread exports
        # can be grouped with database backups.
        try:
            db = getattr(self.bot, "db", None)
            db_file = getattr(db, "db_file", None) if db is not None else None
            if db_file:
                base_dir = os.path.dirname(os.path.abspath(db_file)) or "."
            else:
                base_dir = "."
            backup_root = os.getenv("DKP_DB_BACKUP_DIR") or os.path.join(base_dir, "backups")
            os.makedirs(backup_root, exist_ok=True)

            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            ts_folder = os.path.join(backup_root, ts)
            os.makedirs(ts_folder, exist_ok=True)

            local_name = f"thread_export_guild_{interaction.guild.id}_thread_{target.id}_{ts}.zip"
            local_path = os.path.join(ts_folder, local_name)
            with open(local_path, "wb") as f:
                f.write(bio.getvalue())
        except Exception:
            # Local backup failure should not prevent delivering the export to the user.
            pass

        file = discord.File(bio, filename=filename)
        await interaction.followup.send(content="Thread export ready.", file=file, ephemeral=True)

    @app_commands.command(name="export_all_threads", description="Export all threads under a text channel to ZIPs in the backups folder.")
    @app_commands.checks.has_permissions(administrator=True)
    async def export_all_threads_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None):
        """Bulk-export all threads under the given text channel.

        For each thread, writes a ZIP with the same structure as /export_thread into
        backups/<TIMESTAMP>/thread_export_guild_<guild>_thread_<id>_<TIMESTAMP>.zip.
        """
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        target = channel if channel else interaction.channel
        if not isinstance(target, discord.TextChannel):
            return await interaction.followup.send("Use this in a text channel or provide a text channel option.", ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("This command can only be used inside a server.", ephemeral=True)

        # Determine backup root and timestamped folder as in /export_thread
        db = getattr(self.bot, "db", None)
        db_file = getattr(db, "db_file", None) if db is not None else None
        if db_file:
            base_dir = os.path.dirname(os.path.abspath(db_file)) or "."
        else:
            base_dir = "."
        backup_root = os.getenv("DKP_DB_BACKUP_DIR") or os.path.join(base_dir, "backups")
        os.makedirs(backup_root, exist_ok=True)

        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        ts_folder = os.path.join(backup_root, ts)
        os.makedirs(ts_folder, exist_ok=True)

        # Collect all relevant threads: active + archived
        seen_ids = set()
        threads: list[discord.Thread] = []

        for th in target.threads:
            if isinstance(th, discord.Thread) and th.id not in seen_ids:
                seen_ids.add(th.id)
                threads.append(th)

        try:
            async for th in target.archived_threads(limit=None):
                if isinstance(th, discord.Thread) and th.id not in seen_ids:
                    seen_ids.add(th.id)
                    threads.append(th)
        except Exception:
            # Older discord.py or missing permissions may not support archived_threads;
            # in that case we proceed with whatever we have.
            pass

        if not threads:
            return await interaction.followup.send("No threads found under this channel to export.", ephemeral=True)

        exported = 0
        skipped = 0
        exported_files: list[tuple[str, str]] = []  # (filename, full_path)

        for th in threads:
            try:
                messages = await self._gather_thread(th)
                md_text = self._build_markdown(th, messages)
                csv_bytes = self._build_csv(messages)

                bio = io.BytesIO()
                with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr("thread.md", md_text.encode())
                    zf.writestr("thread.csv", csv_bytes)
                    zf.writestr(
                        "meta.txt",
                        (
                            f"thread_id={th.id}\n"
                            f"thread_name={th.name}\n"
                            f"exported_at={datetime.now(timezone.utc).isoformat()}\n"
                        ),
                    )
                    await self._download_attachments_into_zip(zf, messages)

                bio.seek(0)
                local_name = f"thread_export_guild_{guild.id}_thread_{th.id}_{ts}.zip"
                local_path = os.path.join(ts_folder, local_name)
                with open(local_path, "wb") as f:
                    f.write(bio.getvalue())
                exported += 1
                exported_files.append((local_name, local_path))
            except Exception as e:
                skipped += 1
                logging = __import__("logging")
                logging.getLogger(__name__).error(
                    f"Failed to export thread {th.id} in guild {guild.id}: {e}",
                    exc_info=True,
                )

        summary = (
            f"Exported {exported} thread(s) under {target.mention} into backups/{ts}. "
            f"Skipped {skipped} due to errors."
        )

        file = None
        if exported_files:
            try:
                all_bio = io.BytesIO()
                with zipfile.ZipFile(all_bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for name, path in exported_files:
                        try:
                            # Store each per-thread ZIP under its own name inside the aggregate ZIP
                            zf.write(path, arcname=name)
                        except Exception:
                            # If one file fails, skip it but continue building the archive
                            continue
                all_bio.seek(0)
                agg_name = f"all_threads_export_guild_{guild.id}_channel_{target.id}_{ts}.zip"
                file = discord.File(all_bio, filename=agg_name)
            except Exception:
                file = None

        if file is not None:
            await interaction.followup.send(summary, file=file, ephemeral=True)
        else:
            await interaction.followup.send(summary, ephemeral=True)

    @app_commands.command(name="export_channel", description="Export a text channel to a ZIP (Markdown + CSV + attachments).")
    @app_commands.checks.has_permissions(administrator=True)
    async def export_channel_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        target = channel if channel else interaction.channel
        if not isinstance(target, discord.TextChannel):
            return await interaction.followup.send("Use this in a text channel or provide a text channel option.", ephemeral=True)

        messages = await self._gather_channel(target)
        md_text = self._build_channel_markdown(target, messages)
        csv_bytes = self._build_csv(messages)

        bio = io.BytesIO()
        with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("channel.md", md_text.encode())
            zf.writestr("channel.csv", csv_bytes)
            zf.writestr(
                "meta.txt",
                (
                    f"channel_id={target.id}\n"
                    f"channel_name={target.name}\n"
                    f"exported_at={datetime.now(timezone.utc).isoformat()}\n"
                ),
            )
            await self._download_attachments_into_zip(zf, messages)
        bio.seek(0)
        filename = f"channel_export_{target.id}.zip"

        # Save a local copy into the backups directory so that channel exports
        # can be grouped with database backups.
        try:
            db = getattr(self.bot, "db", None)
            db_file = getattr(db, "db_file", None) if db is not None else None
            if db_file:
                base_dir = os.path.dirname(os.path.abspath(db_file)) or "."
            else:
                base_dir = "."
            backup_root = os.getenv("DKP_DB_BACKUP_DIR") or os.path.join(base_dir, "backups")
            os.makedirs(backup_root, exist_ok=True)

            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            ts_folder = os.path.join(backup_root, ts)
            os.makedirs(ts_folder, exist_ok=True)

            local_name = f"channel_export_guild_{interaction.guild.id}_channel_{target.id}_{ts}.zip"
            local_path = os.path.join(ts_folder, local_name)
            with open(local_path, "wb") as f:
                f.write(bio.getvalue())
        except Exception:
            # Local backup failure should not prevent delivering the export to the user.
            pass

        file = discord.File(bio, filename=filename)
        await interaction.followup.send(content="Channel export ready.", file=file, ephemeral=True)

    @app_commands.command(name="export_test", description="Test command to verify export cog slash commands are synced.")
    @app_commands.checks.has_permissions(administrator=True)
    async def export_test_cmd(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("/export_test is working.", ephemeral=True)

    async def _read_zip_bytes(self, attachment: discord.Attachment) -> zipfile.ZipFile:
        data = await attachment.read()
        bio = io.BytesIO(data)
        return zipfile.ZipFile(bio, mode="r")

    def _read_meta(self, zf: zipfile.ZipFile) -> dict:
        meta = {"thread_name": None}
        try:
            with zf.open("meta.txt") as f:
                content = f.read().decode(errors="ignore")
            for line in content.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    meta[k.strip()] = v.strip()
        except KeyError:
            pass
        return meta

    def _iter_csv_rows_generic(self, zf: zipfile.ZipFile, csv_name: str):
        """Yield rows from the given CSV file inside the ZIP."""
        with zf.open(csv_name) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            reader = csv.reader(text)
            _header = next(reader, None)
            for row in reader:
                yield row

    def _iter_csv_rows(self, zf: zipfile.ZipFile):
        """Backward-compatible helper for thread exports (thread.csv)."""
        return self._iter_csv_rows_generic(zf, "thread.csv")

    def _load_attachment_bytes(self, zf: zipfile.ZipFile, relpath: str) -> bytes | None:
        try:
            with zf.open(f"attachments/{relpath}") as f:
                return f.read()
        except KeyError:
            return None

    async def _ensure_target_thread(self, interaction: discord.Interaction, desired_name: str | None) -> discord.Thread:
        # If already in a thread, reuse it
        if isinstance(interaction.channel, discord.Thread):
            return interaction.channel
        # Otherwise, create a new thread under the current text channel
        channel = interaction.channel
        name = desired_name or f"Imported Thread {datetime.now().strftime('%Y-%m-%d %H-%M')}"
        # Create a seed message then a thread from it to ensure compatibility
        seed = await channel.send(f"Starting import for: {name}")
        thread = await seed.create_thread(name=name)
        return thread

    async def _send_message_with_attachments(self, thread: discord.Thread, content: str, files: list[discord.File]):
        # Discord allows up to 10 attachments per message
        if not files:
            await thread.send(content if content else "")
            return
        batch = []
        first = True
        for f in files:
            batch.append(f)
            if len(batch) == 10:
                await thread.send(content if first else "", files=batch)
                first = False
                batch = []
                await asyncio.sleep(0.5)
        if batch:
            await thread.send(content if first else "", files=batch)

    @app_commands.command(name="import_thread", description="Import a thread from an exported ZIP (replay messages and attachments).")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(archive="The exported ZIP file created by /export_thread", name_override="Optional new thread name")
    async def import_thread_cmd(self, interaction: discord.Interaction, archive: discord.Attachment, name_override: str | None = None):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        # Basic validation
        if not archive.filename.lower().endswith(".zip"):
            return await interaction.followup.send("Please upload a .zip file generated by /export_thread.", ephemeral=True)

        try:
            zf = await self._read_zip_bytes(archive)
        except zipfile.BadZipFile:
            return await interaction.followup.send("The uploaded file is not a valid ZIP.", ephemeral=True)

        meta = self._read_meta(zf)
        desired_name = name_override or meta.get("thread_name")
        target_thread = await self._ensure_target_thread(interaction, desired_name)

        # Iterate CSV rows: [timestamp, author_id, author_name, content, attachments]
        sent = 0
        async def build_files(att_field: str) -> list[discord.File]:
            files: list[discord.File] = []
            att_field = (att_field or "").strip()
            if not att_field:
                return files
            parts = [p for p in att_field.split(";") if p]
            for p in parts:
                data = self._load_attachment_bytes(zf, p)
                if data is None:
                    continue
                # Original filename after id_
                try:
                    _, original = p.split("_", 1)
                except ValueError:
                    original = p
                files.append(discord.File(io.BytesIO(data), filename=original))
            return files

        try:
            for row in self._iter_csv_rows(zf):
                if len(row) < 5:
                    continue
                _, _, _, content, att_field = row
                files = await build_files(att_field)
                await self._send_message_with_attachments(target_thread, content, files)
                sent += 1
                # small delay to be gentle with rate limits
                await asyncio.sleep(0.5)
        except Exception:
            return await interaction.followup.send("Import failed while sending messages. Check the ZIP contents.", ephemeral=True)

        await interaction.followup.send(f"Import complete. Replayed {sent} messages into {target_thread.mention}.", ephemeral=True)

    @app_commands.command(name="import_channel", description="Import a text channel from an exported ZIP (replay messages and attachments).")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(archive="The exported ZIP file created by /export_channel")
    async def import_channel_cmd(self, interaction: discord.Interaction, archive: discord.Attachment):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        if not archive.filename.lower().endswith(".zip"):
            return await interaction.followup.send("Please upload a .zip file generated by /export_channel.", ephemeral=True)

        try:
            zf = await self._read_zip_bytes(archive)
        except zipfile.BadZipFile:
            return await interaction.followup.send("The uploaded file is not a valid ZIP.", ephemeral=True)

        # Target is the current text channel
        target_channel = interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            return await interaction.followup.send("Use this in a text channel where you want messages replayed.", ephemeral=True)

        sent = 0

        async def build_files(att_field: str) -> list[discord.File]:
            files: list[discord.File] = []
            att_field = (att_field or "").strip()
            if not att_field:
                return files
            parts = [p for p in att_field.split(";") if p]
            for p in parts:
                data = self._load_attachment_bytes(zf, p)
                if data is None:
                    continue
                try:
                    _, original = p.split("_", 1)
                except ValueError:
                    original = p
                files.append(discord.File(io.BytesIO(data), filename=original))
            return files

        try:
            for row in self._iter_csv_rows_generic(zf, "channel.csv"):
                if len(row) < 5:
                    continue
                _, _, _, content, att_field = row
                files = await build_files(att_field)

                # Skip completely empty rows
                if (not (content or "").strip()) and not files:
                    continue

                await self._send_message_with_attachments(target_channel, content, files)
                sent += 1
                await asyncio.sleep(0.5)
        except Exception:
            return await interaction.followup.send("Import failed while sending messages. Check the ZIP contents.", ephemeral=True)

        await interaction.followup.send(f"Import complete. Replayed {sent} messages into {target_channel.mention}.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ExportCog(bot))
