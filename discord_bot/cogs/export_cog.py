import discord
from discord.ext import commands
from discord import app_commands
import io
import csv
import zipfile
from datetime import datetime, timezone
import os
import asyncio
import json

from ..utils import is_officer
from ..utils import is_admin

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

    def _extract_message_content(self, msg: discord.Message) -> str:
        """Return a text representation of a message.

        Prefers clean_content, but for embed-only messages (such as the
        raid control and DKP award panels), fall back to a simple textual
        rendering of the embeds so that exports are human-readable.
        """
        base = msg.clean_content or ""
        if base.strip():
            return base

        parts: list[str] = []
        for emb in msg.embeds:
            if emb.title:
                parts.append(str(emb.title))
            if emb.description:
                parts.append(str(emb.description))
            for field in getattr(emb, "fields", []) or []:
                # Format as "Field Name: Field Value"
                name = str(field.name) if field.name is not None else ""
                value = str(field.value) if field.value is not None else ""
                if name or value:
                    parts.append(f"{name}: {value}".strip())
        return "\n".join(p for p in parts if p)

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
            has_plain = bool(msg.clean_content and msg.clean_content.strip())
            messages.append({
                "id": msg.id,
                "author_id": msg.author.id if msg.author else None,
                "author_name": getattr(msg.author, "display_name", str(msg.author)) if msg.author else "Unknown",
                "timestamp": msg.created_at.replace(tzinfo=timezone.utc).isoformat(),
                "content": self._extract_message_content(msg),
                "attachments": attachments,
                "has_plain_content": has_plain,
                # Store raw embed JSON so future imports can recreate UI
                "embeds": [e.to_dict() for e in msg.embeds],
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
            has_plain = bool(msg.clean_content and msg.clean_content.strip())
            messages.append({
                "id": msg.id,
                "author_id": msg.author.id if msg.author else None,
                "author_name": getattr(msg.author, "display_name", str(msg.author)) if msg.author else "Unknown",
                "timestamp": msg.created_at.replace(tzinfo=timezone.utc).isoformat(),
                "content": self._extract_message_content(msg),
                "attachments": attachments,
                "has_plain_content": has_plain,
                "embeds": [e.to_dict() for e in msg.embeds],
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
                m["content"],
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
                    logging.exception("Failed to fetch attachment for export")
                    continue

    @app_commands.command(name="export_thread", description="Export this thread to a ZIP (Markdown + CSV + attachments).")
    @app_commands.check(is_admin)
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
            zf.writestr(
                "meta.txt",
                f"thread_id={target.id}\nthread_name={target.name}\nexported_at={datetime.now(timezone.utc).isoformat()}\n",
            )
            # New: structured JSON export for future rich imports (embeds, etc.)
            zf.writestr("messages.json", json.dumps(messages, ensure_ascii=False).encode("utf-8"))
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
            logging.exception("Failed to write local backup of export")

        file = discord.File(bio, filename=filename)
        await interaction.followup.send(content="Thread export ready.", file=file, ephemeral=True)

    @app_commands.command(name="export_all_threads", description="Export all threads under a text channel to ZIPs in the backups folder.")
    @app_commands.check(is_admin)
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
            logging.exception("Failed to fetch archived threads")

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
                    zf.writestr("messages.json", json.dumps(messages, ensure_ascii=False).encode("utf-8"))
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
                            logging.exception("Failed to write file to aggregate export ZIP")
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
    @app_commands.check(is_admin)
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
            zf.writestr("messages.json", json.dumps(messages, ensure_ascii=False).encode("utf-8"))
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
            logging.exception("Failed to write local backup of export")

        file = discord.File(bio, filename=filename)
        await interaction.followup.send(content="Channel export ready.", file=file, ephemeral=True)

    @app_commands.command(name="export_test", description="Test command to verify export cog slash commands are synced.")
    @app_commands.check(is_admin)
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

    def _load_messages_json(self, zf: zipfile.ZipFile) -> list[dict] | None:
        """Load structured messages.json if present.

        Returns a list of message dicts matching the order used when building
        thread.csv/channel.csv. If the file is missing or invalid, returns None
        so imports can fall back to CSV-only behavior.
        """
        try:
            with zf.open("messages.json") as f:
                data = f.read().decode("utf-8", errors="ignore")
            obj = json.loads(data)
            if isinstance(obj, list):
                return obj
        except KeyError:
            return None
        except Exception:
            return None
        return None

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

    async def _send_message_with_attachments(
        self,
        target: discord.abc.Messageable,
        content: str,
        files: list[discord.File],
        embeds: list[discord.Embed] | None = None,
    ):
        """Send a message with attachments (and optional embeds) in batches.

        "target" may be a Thread or TextChannel. Embeds are optional so that
        existing callers without embed metadata continue to work.
        """
        # Discord allows up to 10 attachments per message
        embeds = embeds or []
        if not files:
            await target.send(content if content else "", embeds=embeds or None)
            return
        batch = []
        first = True
        for f in files:
            batch.append(f)
            if len(batch) == 10:
                await target.send(content if first else "", files=batch, embeds=embeds or None)
                first = False
                batch = []
                await asyncio.sleep(0.5)
        if batch:
            await target.send(content if first else "", files=batch, embeds=embeds or None)

    @app_commands.command(name="import_thread", description="Import a thread from an exported ZIP (replay messages and attachments).")
    @app_commands.check(is_admin)
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
        original_leader: str | None = None
        messages_meta = self._load_messages_json(zf) or []
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
            index = 0
            for row in self._iter_csv_rows(zf):
                if len(row) < 5:
                    continue
                _, _, _, content, att_field = row
                files = await build_files(att_field)

                # Capture original raid leader from the very first "Raid started by" line
                if index == 0 and not original_leader:
                    prefix = "Raid started by "
                    if (content or "").startswith(prefix):
                        # Expect format: "Raid started by X on ..."; fall back to the
                        # entire tail if we can't find the separator.
                        tail = content[len(prefix):]
                        sep = tail.find(" on ")
                        original_leader = tail[:sep] if sep != -1 else tail

                # Optional embed reconstruction from messages.json; index aligned
                embeds: list[discord.Embed] = []
                if 0 <= index < len(messages_meta):
                    raw = messages_meta[index] or {}
                    raw_embeds = raw.get("embeds", []) or []

                    # Special handling for the first raid control panel message:
                    # replace it with a simple 'Raid leader is {name}' line
                    # instead of replaying the control panel embed.
                    if index == 0 and raw_embeds:
                        title = str(raw_embeds[0].get("title", ""))
                        if title.startswith("Raid Control Panel for "):
                            leader = raw.get("author_name") or title.removeprefix("Raid Control Panel for ")
                            content = f"Raid leader is {leader}"
                            embeds = []
                    else:
                        for e in raw_embeds:
                            try:
                                embeds.append(discord.Embed.from_dict(e))
                            except Exception:
                                logging.exception("Failed to deserialize embed during import")
                                continue

                        # When embeds are present, prefer the embed UI only to avoid
                        # duplicating the flattened text representation.
                        if embeds:
                            content = ""

                # Skip rows that would be completely empty: no text, no files, no embeds
                if (not (content or "").strip()) and not files and not embeds:
                    continue

                await self._send_message_with_attachments(target_thread, content, files, embeds)
                sent += 1
                index += 1
                # small delay to be gentle with rate limits
                await asyncio.sleep(0.5)
        except Exception:
            return await interaction.followup.send("Import failed while sending messages. Check the ZIP contents.", ephemeral=True)

        await interaction.followup.send(f"Import complete. Replayed {sent} messages into {target_thread.mention}.", ephemeral=True)

    @app_commands.command(name="import_channel", description="Import a text channel from an exported ZIP (replay messages and attachments).")
    @app_commands.check(is_admin)
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
        messages_meta = self._load_messages_json(zf) or []

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
            index = 0
            for row in self._iter_csv_rows_generic(zf, "channel.csv"):
                if len(row) < 5:
                    continue
                _, _, _, content, att_field = row
                files = await build_files(att_field)

                embeds: list[discord.Embed] = []
                if 0 <= index < len(messages_meta):
                    raw = messages_meta[index] or {}
                    for e in raw.get("embeds", []) or []:
                        try:
                            embeds.append(discord.Embed.from_dict(e))
                        except Exception:
                            logging.exception("Failed to deserialize embed during import (channel import)")
                            continue

                    # When embeds are present, prefer the embed UI only to avoid
                    # duplicating the flattened text representation.
                    if embeds:
                        content = ""

                # Skip completely empty rows
                if (not (content or "").strip()) and not files and not embeds:
                    continue

                await self._send_message_with_attachments(target_channel, content, files, embeds)
                sent += 1
                index += 1
                await asyncio.sleep(0.5)
        except Exception:
            return await interaction.followup.send("Import failed while sending messages. Check the ZIP contents.", ephemeral=True)

        await interaction.followup.send(f"Import complete. Replayed {sent} messages into {target_channel.mention}.", ephemeral=True)

    @app_commands.command(name="import_all_threads", description="Bulk-import multiple thread exports from a ZIP-of-ZIPs or a backups timestamp.")
    @app_commands.check(is_admin)
    @app_commands.describe(
        archive="ZIP file created by /export_all_threads containing multiple thread_export_...zip files",
        backup_id="Timestamp ID matching a backups/<TIMESTAMP>/ folder on the bot server",
        parent_channel="Text channel under which new threads will be created (defaults to current channel)",
    )
    async def import_all_threads_cmd(
        self,
        interaction: discord.Interaction,
        archive: discord.Attachment | None = None,
        backup_id: str | None = None,
        parent_channel: discord.TextChannel | None = None,
    ):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        # Ensure exactly one source is provided
        if (archive is None and not backup_id) or (archive is not None and backup_id):
            return await interaction.followup.send(
                "Please provide exactly one of: an uploaded ZIP-of-ZIPs (archive) or a backup_id timestamp.",
                ephemeral=True,
            )

        # Determine parent text channel where new threads will be created
        target_parent = parent_channel if parent_channel is not None else interaction.channel
        if not isinstance(target_parent, discord.TextChannel):
            return await interaction.followup.send(
                "Use this in or target a text channel where imported threads should be created.",
                ephemeral=True,
            )

        # Helper to import a single thread export from an open ZipFile into a new thread
        async def import_single_thread(zf: zipfile.ZipFile) -> int:
            meta = self._read_meta(zf)
            desired_name = meta.get("thread_name") or f"Imported Thread {datetime.now().strftime('%Y-%m-%d %H-%M')}"

            seed = await target_parent.send(f"Starting import for: {desired_name}")
            thread = await seed.create_thread(name=desired_name)

            sent = 0
            messages_meta = self._load_messages_json(zf) or []

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

            index = 0
            for row in self._iter_csv_rows(zf):
                if len(row) < 5:
                    continue
                _, _, _, content, att_field = row
                files = await build_files(att_field)

                embeds: list[discord.Embed] = []
                if 0 <= index < len(messages_meta):
                    raw = messages_meta[index] or {}
                    raw_embeds = raw.get("embeds", []) or []

                    # Special handling for the first raid control panel message
                    if index == 0 and raw_embeds:
                        title = str(raw_embeds[0].get("title", ""))
                        if title.startswith("Raid Control Panel for "):
                            leader = raw.get("author_name") or title.removeprefix("Raid Control Panel for ")
                            content = f"Raid leader is {leader}"
                            embeds = []
                    else:
                        for e in raw_embeds:
                            try:
                                embeds.append(discord.Embed.from_dict(e))
                            except Exception:
                                logging.exception("Failed to deserialize embed during import")
                                continue

                        # When embeds are present, prefer the embed UI only to avoid
                        # duplicating the flattened text representation.
                        if embeds:
                            content = ""

                # Skip completely empty rows so we never send empty messages
                if (not (content or "").strip()) and not files and not embeds:
                    continue

                await self._send_message_with_attachments(thread, content, files, embeds)
                sent += 1
                index += 1
                await asyncio.sleep(0.5)

            return sent

        imported_threads = 0
        total_messages = 0
        skipped_archives = 0

        # Case 1: uploaded ZIP-of-ZIPs from /export_all_threads
        if archive is not None:
            if not archive.filename.lower().endswith(".zip"):
                return await interaction.followup.send(
                    "Please upload a .zip file generated by /export_all_threads.",
                    ephemeral=True,
                )
            try:
                outer_zf = await self._read_zip_bytes(archive)
            except zipfile.BadZipFile:
                return await interaction.followup.send("The uploaded file is not a valid ZIP.", ephemeral=True)

            # Each inner entry that ends with .zip is treated as a thread export
            for name in outer_zf.namelist():
                if not name.lower().endswith(".zip"):
                    continue
                try:
                    with outer_zf.open(name) as f:
                        data = f.read()
                    bio = io.BytesIO(data)
                    with zipfile.ZipFile(bio, mode="r") as inner_zf:
                        messages_sent = await import_single_thread(inner_zf)
                        imported_threads += 1
                        total_messages += messages_sent
                except Exception:
                    skipped_archives += 1
                    continue

        # Case 2: backups/<TIMESTAMP>/ folder on disk
        else:
            # Resolve backups root similar to export commands
            db = getattr(self.bot, "db", None)
            db_file = getattr(db, "db_file", None) if db is not None else None
            if db_file:
                base_dir = os.path.dirname(os.path.abspath(db_file)) or "."
            else:
                base_dir = "."
            backup_root = os.getenv("DKP_DB_BACKUP_DIR") or os.path.join(base_dir, "backups")
            ts_folder = os.path.join(backup_root, backup_id)

            if not os.path.isdir(ts_folder):
                return await interaction.followup.send(
                    f"No backups folder found for ID {backup_id} (expected at {ts_folder}).",
                    ephemeral=True,
                )

            # Import every thread_export_*.zip in this timestamped folder
            for filename in os.listdir(ts_folder):
                if not filename.lower().endswith(".zip"):
                    continue
                if "thread_export" not in filename:
                    continue
                full_path = os.path.join(ts_folder, filename)
                try:
                    with zipfile.ZipFile(full_path, mode="r") as zf:
                        messages_sent = await import_single_thread(zf)
                        imported_threads += 1
                        total_messages += messages_sent
                except Exception:
                    skipped_archives += 1
                    continue

        if imported_threads == 0 and skipped_archives == 0:
            return await interaction.followup.send(
                "No valid thread exports were found to import.",
                ephemeral=True,
            )

        source_desc = (
            f"archive {archive.filename}" if archive is not None else f"backups/{backup_id}"
        )

        summary = (
            f"Imported {imported_threads} thread(s) into {target_parent.mention} from {source_desc}. "
            f"Replayed {total_messages} messages. Skipped {skipped_archives} broken archive(s)."
        )

        await interaction.followup.send(summary, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ExportCog(bot))
