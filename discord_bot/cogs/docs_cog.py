import discord
from discord.ext import commands
from discord import app_commands
from pathlib import Path
import re

from .. import __version__ as bot_version
from ..utils import ensure_allowed_guild, is_officer, is_admin, create_info_embed


DOCS_DIR = Path(__file__).resolve().parents[2] / "Documentation"


def _extract_title(md: str, fallback: str) -> str:
    for line in md.splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()[:256]
    return fallback[:256]


def _split_chunks(text: str, limit: int = 4000) -> list[str]:
    chunks: list[str] = []
    t = text
    while t:
        chunks.append(t[:limit])
        t = t[limit:]
    return chunks or [""]


_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _with_cache_bust(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw
    if raw.startswith("http://") or raw.startswith("https://"):
        if "?" in raw:
            return f"{raw}&v={bot_version}"
        return f"{raw}?v={bot_version}"
    return raw


def _extract_first_image(md: str) -> tuple[str | None, str]:
    m = _IMAGE_RE.search(md)
    if not m:
        return None, md
    url = (m.group(1) or "").strip()
    stripped = _IMAGE_RE.sub("", md, count=1).strip()
    if url.startswith("http://") or url.startswith("https://"):
        return _with_cache_bust(url), stripped
    return None, stripped


def _load_pages() -> list[dict[str, str]]:
    pages: list[dict[str, str]] = []
    if not DOCS_DIR.is_dir():
        return pages

    for path in sorted(DOCS_DIR.glob("*.md")):
        if not path.is_file():
            continue
        if path.name == "loot modes.md":
            continue
        if path.parent.name == "dont_commit":
            continue

        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        title = _extract_title(raw, path.stem)
        pages.append({"file": path.name, "title": title})

    return pages


def _read_page(filename: str) -> tuple[str, str, str | None]:
    path = DOCS_DIR / filename
    raw = path.read_text(encoding="utf-8", errors="replace")
    title = _extract_title(raw, path.stem)

    img_url, stripped = _extract_first_image(raw)

    body_lines: list[str] = []
    saw_title = False
    for line in stripped.splitlines():
        if not saw_title and re.match(r"^#\s+", line):
            saw_title = True
            continue
        body_lines.append(line)

    body = "\n".join(body_lines).strip() or "(No content)"
    return title, body, img_url


def _page_officer_only(filename: str) -> bool:
    return filename in {"Officer-Admin-Help.md"}


class DocsPageSelect(discord.ui.Select):
    def __init__(self, pages: list[dict[str, str]], default_file: str):
        options = [
            discord.SelectOption(
                label=p["title"][:100],
                value=p["file"],
                default=(p["file"] == default_file),
            )
            for p in pages
        ][:25]

        super().__init__(
            placeholder="Select a docs page...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, DocsView):
            return await interaction.response.edit_message(view=None)

        selected = self.values[0]
        if selected not in view.allowed_files:
            return await interaction.response.send_message(
                "You don't have permission to view that page.",
                ephemeral=True,
            )

        for option in self.options:
            option.default = option.value == selected

        embeds = view.create_embeds(selected)
        await interaction.response.edit_message(embeds=embeds, view=view)


class DocsView(discord.ui.View):
    def __init__(self, pages: list[dict[str, str]], allowed_files: set[str], default_file: str):
        super().__init__(timeout=180)
        self._pages = list(pages)
        self.allowed_files = set(allowed_files)
        self.add_item(DocsPageSelect(pages, default_file))

    def create_embeds(self, filename: str) -> list[discord.Embed]:
        title, body, img_url = _read_page(filename)
        chunks = _split_chunks(body, limit=4000)

        embeds: list[discord.Embed] = []
        total = len(chunks)
        for i, chunk in enumerate(chunks, start=1):
            page_title = title if total == 1 else f"{title} ({i}/{total})"
            embed = create_info_embed(page_title, chunk)
            embeds.append(embed)

        if img_url:
            embeds[0].set_image(url=img_url)

        return embeds

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, row=1)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)


class DocsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def show_docs(self, interaction: discord.Interaction):
        if not await ensure_allowed_guild(interaction):
            return

        if not await is_admin(interaction):
            if not interaction.response.is_done():
                return await interaction.response.send_message("You don't have permission to use this.", ephemeral=True)
            return await interaction.followup.send("You don't have permission to use this.", ephemeral=True)

        pages = _load_pages()
        if not pages:
            if not interaction.response.is_done():
                return await interaction.response.send_message("No docs pages were found.", ephemeral=True)
            return await interaction.followup.send("No docs pages were found.", ephemeral=True)

        can_view_officer = await is_officer(interaction)

        allowed = []
        for p in pages:
            if _page_officer_only(p["file"]) and not can_view_officer:
                continue
            allowed.append(p)

        if not allowed:
            if not interaction.response.is_done():
                return await interaction.response.send_message("No docs pages are available.", ephemeral=True)
            return await interaction.followup.send("No docs pages are available.", ephemeral=True)

        allowed_files = {p["file"] for p in allowed}
        default_file = "getting-started.md" if "getting-started.md" in allowed_files else allowed[0]["file"]

        view = DocsView(allowed, allowed_files, default_file)
        embeds = view.create_embeds(default_file)

        if not interaction.response.is_done():
            await interaction.response.send_message(embeds=embeds, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embeds=embeds, view=view, ephemeral=True)

    @app_commands.command(name="docs", description="Browse the DKP bot user documentation.")
    @app_commands.check(is_admin)
    async def docs_cmd(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        await self.show_docs(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(DocsCog(bot))
