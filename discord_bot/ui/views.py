import discord
import logging
import re
import subprocess
from pathlib import Path
from .modals import DKPAdjustmentModal, AuctionStartModal, BidModal, RaidRulesModal, RaidGroupCountModal, RaidGroupSetupModal
from discord.ui import UserSelect, Select
from .. import __version__ as bot_version
from ..utils import is_admin, is_officer, ensure_allowed_guild, create_info_embed


CHANGELOG_PATH = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
CHANGELOG_DIR = Path(__file__).resolve().parents[2] / "changelog"

FALLBACK_CHANGELOG_ENTRIES: dict[str, str] = {
    "Unreleased": "No changelog file was found.",
}

_CHANGELOG_CACHE: dict[str, object] = {
    "mtime": None,
    "versions": [],
    "entries": {},
}


def _changelog_sort_key(version: str) -> tuple[int, int, int, int, int, str]:
    if version == "Unreleased":
        return (1_000_000, 0, 0, 10, 0, "")

    m = re.match(
        r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:-(?P<tag>[0-9A-Za-z]+)\.(?P<num>\d+))?$",
        version,
    )
    if not m:
        return (0, 0, 0, 0, 0, version)

    major = int(m.group("major"))
    minor = int(m.group("minor"))
    patch = int(m.group("patch"))
    tag = (m.group("tag") or "").lower()
    num = int(m.group("num") or 0)

    tag_rank_map = {
        "": 4,
        "rc": 3,
        "beta": 2,
        "b": 2,
        "alpha": 1,
        "a": 1,
    }
    tag_rank = tag_rank_map.get(tag, 0)

    return (major, minor, patch, tag_rank, num, tag)


def _sort_changelog_versions(versions: list[str]) -> list[str]:
    def key(v: str):
        if v == "Unreleased":
            return (-10_000_000, 0, 0, 0, 0, "")
        k = _changelog_sort_key(v)
        return (-k[0], -k[1], -k[2], -k[3], -k[4], k[5])

    return sorted(versions, key=key)


def _parse_changelog_markdown(raw: str) -> tuple[list[str], dict[str, str]]:
    versions: list[str] = []
    entries: dict[str, str] = {}
    current_version: str | None = None
    buffer: list[str] = []

    for line in raw.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current_version is not None:
                entries[current_version] = ("\n".join(buffer).strip() or "No details provided.")
                versions.append(current_version)
            header = m.group(1).strip()
            m2 = re.match(r"^\[(?P<version>[^\]]+)\]\([^\)]+\)(?:\s+\(.*\))?\s*$", header)
            current_version = (m2.group("version").strip() if m2 else header)
            buffer = []
            continue

        if current_version is not None:
            buffer.append(line.rstrip())

    if current_version is not None:
        entries[current_version] = ("\n".join(buffer).strip() or "No details provided.")
        versions.append(current_version)

    return versions, entries


def _load_changelog() -> tuple[list[str], dict[str, str]]:
    if CHANGELOG_DIR.is_dir():
        try:
            files = sorted([p for p in CHANGELOG_DIR.glob("*.md") if p.is_file()])
        except OSError:
            files = []

        if files:
            try:
                sig = tuple(sorted([(p.name, float(p.stat().st_mtime)) for p in files]))
            except OSError:
                sig = None

            cached_mtime = _CHANGELOG_CACHE.get("mtime")
            if cached_mtime == sig:
                return (
                    list(_CHANGELOG_CACHE.get("versions") or []),
                    dict(_CHANGELOG_CACHE.get("entries") or {}),
                )

            entries: dict[str, str] = {}
            versions: list[str] = []
            for path in files:
                version = path.stem
                try:
                    body = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                versions.append(version)
                entries[version] = body.strip() or "No details provided."

            versions = _sort_changelog_versions(versions)

            _CHANGELOG_CACHE["mtime"] = sig
            _CHANGELOG_CACHE["versions"] = list(versions)
            _CHANGELOG_CACHE["entries"] = dict(entries)
            return versions, entries

    try:
        stat = CHANGELOG_PATH.stat()
    except OSError:
        return list(FALLBACK_CHANGELOG_ENTRIES.keys()), dict(FALLBACK_CHANGELOG_ENTRIES)

    mtime = float(stat.st_mtime)
    cached_mtime = _CHANGELOG_CACHE.get("mtime")
    if cached_mtime == mtime:
        return (
            list(_CHANGELOG_CACHE.get("versions") or []),
            dict(_CHANGELOG_CACHE.get("entries") or {}),
        )

    try:
        raw = CHANGELOG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return list(FALLBACK_CHANGELOG_ENTRIES.keys()), dict(FALLBACK_CHANGELOG_ENTRIES)

    versions, entries = _parse_changelog_markdown(raw)
    if not versions or not entries:
        versions = list(FALLBACK_CHANGELOG_ENTRIES.keys())
        entries = dict(FALLBACK_CHANGELOG_ENTRIES)

    _CHANGELOG_CACHE["mtime"] = mtime
    _CHANGELOG_CACHE["versions"] = list(versions)
    _CHANGELOG_CACHE["entries"] = dict(entries)
    return versions, entries


def _get_default_changelog_version() -> str:
    versions, _entries = _load_changelog()
    if bot_version in versions:
        return bot_version
    if versions:
        return versions[0]
    return bot_version


def _run_git(args: list[str], cwd: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=3,
        )
    except Exception:
        return None

    if proc.returncode != 0:
        return None

    return proc.stdout


def _get_uncommitted_worktree_changes_markdown() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / ".git").exists():
        return ""

    raw = _run_git(["worktree", "list", "--porcelain"], cwd=repo_root)
    if not raw:
        return ""

    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(dict(current))
            current = {"path": line.split(" ", 1)[1].strip()}
            continue
        if line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].strip()
            continue
        if line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1].strip()
            continue

    if current:
        worktrees.append(dict(current))

    sections: list[str] = []
    for wt in worktrees:
        path = wt.get("path")
        if not path:
            continue

        status_raw = _run_git(["status", "--porcelain=v1"], cwd=Path(path))
        if status_raw is None:
            continue

        status_lines = [ln.rstrip() for ln in status_raw.splitlines() if ln.strip()]
        if not status_lines:
            continue

        branch = wt.get("branch") or "(detached)"
        if branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/") :]

        rendered: list[str] = []
        limit = 40
        for ln in status_lines[:limit]:
            code = ln[:2].strip() or ln[:2]
            file_part = ln[3:] if len(ln) > 3 else ""
            rendered.append(f"- `{code}` {file_part}")

        remaining = len(status_lines) - limit
        if remaining > 0:
            rendered.append(f"- …and {remaining} more")

        sections.append("\n".join([f"### {path} ({branch})", "", *rendered]))

    if not sections:
        return ""

    return "\n".join([
        "## Local worktree changes (not yet committed)",
        "",
        *sections,
    ])


def _create_changelog_embeds(version: str, entries: dict[str, str]) -> list[discord.Embed]:
    notes = entries.get(version)
    if not notes:
        notes = "No changelog entry is available for this version."

    if version == "Unreleased":
        extra = _get_uncommitted_worktree_changes_markdown()
        if extra:
            notes = f"{notes}\n\n{extra}"

    base_title = f"Changelog – v{version}" if version != "Unreleased" else "Changelog – Unreleased"
    chunks: list[str] = []
    text = notes
    while text:
        chunks.append(text[:4000])
        text = text[4000:]

    embeds: list[discord.Embed] = []
    total = len(chunks) if chunks else 1
    for i, chunk in enumerate(chunks or [""], start=1):
        title = base_title if total == 1 else f"{base_title} ({i}/{total})"
        embed = create_info_embed(title, chunk)
        embeds.append(embed)

    embeds[-1].set_footer(text=f"Current bot version: v{bot_version}")
    return embeds


class ChangelogVersionSelect(Select):
    def __init__(self, versions: list[str], default_version: str):
        options = [
            discord.SelectOption(
                label=v[:100],
                value=v,
                default=(v == default_version),
            )
            for v in versions
        ][:25]

        super().__init__(
            placeholder="Select a version...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_version = self.values[0]

        view = self.view
        if not isinstance(view, ChangelogView):
            return await interaction.response.edit_message(view=None)

        if selected_version not in view.allowed_versions:
            return await interaction.response.send_message(
                "You don't have permission to view that changelog.",
                ephemeral=True,
            )

        for option in self.options:
            option.default = option.value == selected_version

        embeds = view.create_embeds(selected_version)
        await interaction.response.edit_message(embeds=embeds, view=view)


class ChangelogView(discord.ui.View):
    def __init__(
        self,
        versions: list[str],
        entries: dict[str, str],
        default_version: str,
    ):
        super().__init__(timeout=180)
        self.allowed_versions = set(versions)
        self._entries = dict(entries)
        self.add_item(ChangelogVersionSelect(versions, default_version))

    def create_embeds(self, version: str) -> list[discord.Embed]:
        return _create_changelog_embeds(version, self._entries)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, row=1)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)


class WelcomeLegacyView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_allowed_guild(interaction)

    @discord.ui.button(label="Create Raid 🏰", style=discord.ButtonStyle.success, custom_id="welcome_create_raid")
    async def create_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            await raid_cog.create_raid_from_interaction(interaction)
        else:
            await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)

    @discord.ui.button(label="My DKP 💰", style=discord.ButtonStyle.secondary, custom_id="welcome_my_dkp")
    async def my_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_my_dkp(interaction)
        else:
            await interaction.followup.send("User module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Auction Help ❓", style=discord.ButtonStyle.primary, custom_id="welcome_auction_help")
    async def auction_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_auction_help(interaction)
        else:
            await interaction.followup.send("User module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Bot Status 📈", style=discord.ButtonStyle.secondary, custom_id="welcome_bot_status")
    async def bot_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        admin_cog = self.bot.get_cog("AdminCog")
        if admin_cog and interaction.guild is not None:
            embed_fn = getattr(admin_cog, "_create_status_embed", None)
            if callable(embed_fn):
                embed = await embed_fn(interaction.guild.id)
            else:
                embed = await admin_cog._create_status_basic_embed(interaction.guild.id)
            await interaction.followup.send(embed=embed, ephemeral=True)
            if await is_admin(interaction):
                env_embed = await admin_cog._create_status_env_embed()
                await interaction.followup.send(embed=env_embed, ephemeral=True)
        else:
            await interaction.followup.send("Admin module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Admin Panel ⚙️", style=discord.ButtonStyle.danger, custom_id="welcome_admin_panel")
    async def admin_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not await is_admin(interaction):
            return await interaction.followup.send("You must be a bot admin to use this.", ephemeral=True)

        view = AdminPanelView(self.bot)
        await interaction.followup.send("Welcome to the Admin Panel.", view=view, ephemeral=True)

    @discord.ui.button(
        label="Change Log 🔒",
        style=discord.ButtonStyle.secondary,
        custom_id="welcome_change_log",
        row=1,
    )
    async def change_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass

        versions, entries = _load_changelog()
        can_view_unreleased = await is_officer(interaction)
        allowed_versions = versions if can_view_unreleased else [v for v in versions if v != "Unreleased"]

        content = None
        if not can_view_unreleased and "Unreleased" in versions:
            content = "Showing public changelog entries. (Unreleased is officers-only.)"

        if not allowed_versions:
            return await interaction.followup.send(
                "No public changelog entries are available.",
                ephemeral=True,
            )

        default_version = bot_version if bot_version in allowed_versions else allowed_versions[0]
        view = ChangelogView(allowed_versions, entries, default_version)
        embeds = view.create_embeds(default_version)
        if content:
            await interaction.followup.send(content=content, embeds=embeds, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embeds=embeds, view=view, ephemeral=True)

    @discord.ui.button(
        label="Docs 📚",
        style=discord.ButtonStyle.primary,
        custom_id="welcome_docs",
        row=1,
    )
    async def docs(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass

        if not await is_admin(interaction):
            return await interaction.followup.send("You must be a bot admin to use this.", ephemeral=True)

        docs_cog = self.bot.get_cog("DocsCog")
        if docs_cog and hasattr(docs_cog, "show_docs"):
            await docs_cog.show_docs(interaction)
        else:
            await interaction.followup.send("Docs module is currently offline.", ephemeral=True)

class MemberSelect(Select):
    def __init__(self, bot, action: str, members: list[discord.Member]):
        self.bot = bot
        self.action = action
        # Track which members are currently in the raid voice channel so we can
        # enforce that only active raiders are selected, while still allowing
        # Discord's built-in type-to-search user picker.
        self._allowed_member_ids = {m.id for m in members}

        options = [
            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
            for m in members
        ][:25]

        super().__init__(
            placeholder=f"Select a member to {action.lower()} DKP...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        raid_cog = self.bot.get_cog("RaidCog")

        # Resolve the selected member from the stored user ID value.
        member: discord.Member | None = None
        if interaction.guild:
            try:
                selected_id = int(self.values[0])
            except (ValueError, TypeError):
                member = None
            else:
                member = interaction.guild.get_member(selected_id)

        if not member or member.id not in self._allowed_member_ids:
            await interaction.response.send_message(
                "That member is not an eligible raid member.",
                ephemeral=True,
            )
            return

        modal = DKPAdjustmentModal(
            action=self.action,
            raid_cog=raid_cog,
            member=member,
            source="raid_panel",
        )
        await interaction.response.send_modal(modal)


class RaidMemberRemoveSelect(Select):
    def __init__(self, bot, members: list[discord.Member]):
        self.bot = bot
        self._allowed_member_ids = {m.id for m in members}

        options = [
            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
            for m in members
        ][:25]

        super().__init__(
            placeholder="Select a member to remove from the raid...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.channel:
            return await interaction.response.send_message("This is not a raid thread.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

        try:
            selected_id = int(self.values[0])
        except (ValueError, TypeError):
            return await interaction.response.send_message("Invalid selection.", ephemeral=True)

        if selected_id not in self._allowed_member_ids:
            return await interaction.response.send_message("That member is not a raid member.", ephemeral=True)

        raid_id = int(raid["id"])

        try:
            removed = await self.bot.db.remove_raid_member(raid_id, selected_id)
        except Exception:
            removed = False

        try:
            await self.bot.db.add_raid_member_exclusion(raid_id, selected_id)
        except Exception:
            pass

        try:
            await self.bot.db.delete_raid_join_request(raid_id, selected_id)
        except Exception:
            pass

        member = interaction.guild.get_member(selected_id) if interaction.guild else None
        mention = member.mention if member else f"<@{selected_id}>"

        if not removed:
            return await interaction.response.send_message(f"{mention} is not part of this raid.", ephemeral=True)

        try:
            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(f"{mention} was removed from the raid.")
        except Exception:
            logging.exception("Failed to send removal message to raid thread")

        return await interaction.response.send_message(f"Removed {mention} from the raid.", ephemeral=True)


class RaidMemberRemoveView(discord.ui.View):
    def __init__(self, bot, members: list[discord.Member]):
        super().__init__(timeout=180)
        self.bot = bot
        self.add_item(RaidMemberRemoveSelect(bot, members))


class RaidMemberClearGroupSelect(Select):
    def __init__(self, bot, members: list[discord.Member]):
        self.bot = bot
        self._allowed_member_ids = {m.id for m in members}

        options = [
            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
            for m in members
        ][:25]

        super().__init__(
            placeholder="Select a member to remove from their group...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.channel:
            return await interaction.response.send_message("This is not a raid thread.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

        try:
            selected_id = int(self.values[0])
        except (ValueError, TypeError):
            return await interaction.response.send_message("Invalid selection.", ephemeral=True)

        if selected_id not in self._allowed_member_ids:
            return await interaction.response.send_message("That member is not a raid member.", ephemeral=True)

        raid_id = int(raid["id"])
        await self.bot.db.set_raid_member_group(raid_id, selected_id, None)

        member = interaction.guild.get_member(selected_id) if interaction.guild else None
        mention = member.mention if member else f"<@{selected_id}>"

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog and interaction.guild:
            raid_dict = raid
            try:
                if raid is not None and not isinstance(raid, dict):
                    raid_dict = dict(raid)
            except Exception:
                raid_dict = raid

            group_count = 0
            try:
                if isinstance(raid_dict, dict):
                    group_count = int(raid_dict.get("group_count") or 0)
                elif raid is not None:
                    group_count = int(raid["group_count"])
            except Exception:
                group_count = 0

            if group_count > 0 and isinstance(interaction.channel, discord.Thread):
                try:
                    embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                    await raid_cog._ensure_group_panel_message(interaction.channel, raid_dict, embed)
                except Exception:
                    logging.exception("Failed to refresh group signup message after clearing member group")

        try:
            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(f"{mention} was removed from their group.")
        except Exception:
            logging.exception("Failed to send group removal message to raid thread")

        return await interaction.response.send_message(f"Cleared group assignment for {mention}.", ephemeral=True)


class RaidMemberClearGroupView(discord.ui.View):
    def __init__(self, bot, members: list[discord.Member]):
        super().__init__(timeout=180)
        self.bot = bot
        self.add_item(RaidMemberClearGroupSelect(bot, members))


class DKPAdjustmentView(discord.ui.View):
    def __init__(self, bot, action: str, members: list[discord.Member], group_count: int | None = None):
        super().__init__(timeout=180)
        self.bot = bot
        self.action = action
        self.add_item(MemberSelect(bot, action, members))

        max_groups = 0
        try:
            if group_count is not None:
                max_groups = max(0, min(int(group_count), 4))
        except Exception:
            max_groups = 0

        for i in range(1, max_groups + 1):
            btn = discord.ui.Button(
                label=f"Group {i}",
                style=discord.ButtonStyle.secondary,
                row=1,
            )

            async def _group_cb(interaction: discord.Interaction, group_number: int = i):
                raid_cog = self.bot.get_cog("RaidCog")
                modal = DKPAdjustmentModal(
                    action=self.action,
                    raid_cog=raid_cog,
                    member=None,
                    group_number=group_number,
                    source="raid_panel",
                )
                await interaction.response.send_modal(modal)

            btn.callback = _group_cb
            self.add_item(btn)

    @discord.ui.button(label="All Raid Members", style=discord.ButtonStyle.primary, row=1)
    async def all_in_vc(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        modal = DKPAdjustmentModal(
            action=self.action,
            raid_cog=raid_cog,
            member=None,
            group_number=None,
            source="raid_panel",
        )
        await interaction.response.send_modal(modal)


class WelcomeView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_allowed_guild(interaction)

    @discord.ui.button(
        label="Open DKP Panel",
        style=discord.ButtonStyle.primary,
        custom_id="welcome_open_panel",
    )
    async def open_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass

        if not isinstance(interaction.user, discord.Member):
            return await interaction.followup.send("This panel can only be used in a server.", ephemeral=True)

        admin_ok = await is_admin(interaction)
        officer_ok = await is_officer(interaction)

        embed = create_info_embed(
            f"DKP Panel for {interaction.user.display_name}",
            "Use the buttons below to access DKP bot features. This panel is only visible to you.",
        )
        view = DkpPanelView(self.bot, admin_ok=admin_ok, officer_ok=officer_ok)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class DkpPanelView(discord.ui.View):
    def __init__(self, bot, admin_ok: bool, officer_ok: bool):
        super().__init__(timeout=180)
        self.bot = bot
        self.admin_ok = bool(admin_ok)
        self.officer_ok = bool(officer_ok)

        hide_ids: set[str] = set()

        if not (self.admin_ok or self.officer_ok):
            hide_ids.add("dkp_panel_create_raid")

        if not self.admin_ok:
            hide_ids |= {
                "dkp_panel_admin_panel",
                "dkp_panel_docs",
            }

        if hide_ids:
            to_remove: list[discord.ui.Item] = []
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.custom_id in hide_ids:
                    to_remove.append(child)
            for child in to_remove:
                self.remove_item(child)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_allowed_guild(interaction)

    @discord.ui.button(label="Create Raid 🏰", style=discord.ButtonStyle.success, custom_id="dkp_panel_create_raid")
    async def create_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (self.admin_ok or self.officer_ok):
            return await interaction.response.send_message("You don't have permission to create a raid.", ephemeral=True)
        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            await raid_cog.create_raid_from_interaction(interaction)
        else:
            await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)

    @discord.ui.button(label="My DKP 💰", style=discord.ButtonStyle.secondary, custom_id="dkp_panel_my_dkp")
    async def my_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_my_dkp(interaction)
        else:
            await interaction.followup.send("User module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Auction Help ❓", style=discord.ButtonStyle.primary, custom_id="dkp_panel_auction_help")
    async def auction_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_auction_help(interaction)
        else:
            await interaction.followup.send("User module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Bot Status 📈", style=discord.ButtonStyle.secondary, custom_id="dkp_panel_bot_status")
    async def bot_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass
        admin_cog = self.bot.get_cog("AdminCog")
        if admin_cog and interaction.guild is not None:
            embed = await admin_cog._create_status_basic_embed(interaction.guild.id)
            await interaction.followup.send(embed=embed, ephemeral=True)
            if await is_admin(interaction):
                env_embed = await admin_cog._create_status_env_embed()
                await interaction.followup.send(embed=env_embed, ephemeral=True)
        else:
            await interaction.followup.send("Admin module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Admin Panel ⚙️", style=discord.ButtonStyle.danger, custom_id="dkp_panel_admin_panel")
    async def admin_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass
        if not self.admin_ok:
            return await interaction.followup.send("You must be a bot admin to use this.", ephemeral=True)

        view = AdminPanelView(self.bot)
        await interaction.followup.send("Welcome to the Admin Panel.", view=view, ephemeral=True)

    @discord.ui.button(
        label="Change Log 🔒",
        style=discord.ButtonStyle.secondary,
        custom_id="dkp_panel_change_log",
    )
    async def change_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass

        versions, entries = _load_changelog()
        can_view_unreleased = await is_officer(interaction)
        allowed_versions = versions if can_view_unreleased else [v for v in versions if v != "Unreleased"]

        content = None
        if not can_view_unreleased and "Unreleased" in versions:
            content = "Showing public changelog entries. (Unreleased is officers-only.)"

        if not allowed_versions:
            return await interaction.followup.send(
                "No public changelog entries are available.",
                ephemeral=True,
            )

        default_version = bot_version if bot_version in allowed_versions else allowed_versions[0]
        view = ChangelogView(allowed_versions, entries, default_version)
        embeds = view.create_embeds(default_version)
        if content:
            await interaction.followup.send(content=content, embeds=embeds, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embeds=embeds, view=view, ephemeral=True)

    @discord.ui.button(
        label="Docs 📚",
        style=discord.ButtonStyle.primary,
        custom_id="dkp_panel_docs",
    )
    async def docs(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass
        if not self.admin_ok:
            return await interaction.followup.send("You must be a bot admin to use this.", ephemeral=True)

        docs_cog = self.bot.get_cog("DocsCog")
        if docs_cog and hasattr(docs_cog, "show_docs"):
            await docs_cog.show_docs(interaction)
        else:
            await interaction.followup.send("Docs module is currently offline.", ephemeral=True)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="dkp_panel_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)


# -- ADMIN VIEWS --


async def send_admin_confirmation(
    interaction: discord.Interaction,
    panel_text: str,
    ephemeral_text: str,
):
    """Small helper to keep admin confirmations consistent.

    Edits the original admin panel message with a tiny confirmation line
    and sends a separate ephemeral confirmation to the acting user.
    """
    await interaction.response.edit_message(
        content=panel_text,
        view=None,
    )
    await interaction.followup.send(
        ephemeral_text,
        ephemeral=True,
    )


class OfficerRoleSelect(discord.ui.RoleSelect):
    def __init__(self, bot: discord.Client):
        self.bot = bot

        super().__init__(
            placeholder="Type to search for a role to use as Officers...",
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        if not isinstance(role, discord.Role):
            return await interaction.response.edit_message(
                content="Please select a role (not a category).",
                view=self.view,
            )
        if role.is_default() or role.managed:
            return await interaction.response.edit_message(
                content="Please select a non-managed role.",
                view=self.view,
            )

        admin_cog = self.view.bot.get_cog("AdminCog") if hasattr(self.view, "bot") else None
        if not admin_cog:
            return await interaction.response.edit_message(
                content="Admin module is currently offline. Please try again later.",
                view=None,
            )

        # Delegate persistence to the existing AdminCog.set_role helper.
        await admin_cog.set_role(interaction, "Officer", role)

        # Use shared helper so all admin confirmations look and behave
        # the same across the panel.
        await send_admin_confirmation(
            interaction,
            panel_text=f"Officers role set to {role.mention}.",
            ephemeral_text=f"Officer role has been updated to {role.mention}.",
        )


class OfficerRoleAssignView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot
        self.add_item(OfficerRoleSelect(bot))


class AdminPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await ensure_allowed_guild(interaction):
            return False
        if not await is_admin(interaction):
            await interaction.response.send_message("You must be a bot admin to use this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Assign Officers Role Name", style=discord.ButtonStyle.primary, row=0)
    async def assign_officers_role_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = OfficerRoleAssignView(self.bot)
        await interaction.response.edit_message(
            content="Type to search for a role to use as the Officers role:",
            view=view,
        )


class RaidGroupJoinSelect(discord.ui.Select):
    def __init__(self, bot, raid_id: int, group_count: int):
        self.bot = bot
        self.raid_id = int(raid_id)
        self.group_count = int(group_count)

        options: list[discord.SelectOption] = [
            discord.SelectOption(label=f"Group {i}", value=str(i)) for i in range(1, self.group_count + 1)
        ]
        options.append(discord.SelectOption(label="Ungrouped", value="0"))

        super().__init__(
            placeholder="Select a group...",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        if not await ensure_allowed_guild(interaction):
            return

        user_id = int(getattr(interaction.user, "id", 0) or 0)
        if not user_id:
            return await interaction.response.send_message("Could not resolve your user.", ephemeral=True)

        try:
            is_member = await self.bot.db.is_raid_member(self.raid_id, user_id)
        except Exception:
            is_member = False
        if not is_member:
            return await interaction.response.send_message(
                "You must join the raid before picking a group.",
                ephemeral=True,
            )

        raw = (self.values[0] or "").strip()
        try:
            selected = int(raw)
        except ValueError:
            selected = 0

        group_number = None if selected == 0 else selected
        if group_number is not None and (group_number < 1 or group_number > self.group_count):
            return await interaction.response.send_message(
                "That group is no longer available. Please try again.",
                ephemeral=True,
            )

        try:
            await self.bot.db.set_raid_member_group(self.raid_id, user_id, group_number)
        except Exception:
            return await interaction.response.send_message(
                "Failed to update your group. Please try again.",
                ephemeral=True,
            )

        if group_number is None:
            return await interaction.response.send_message("You are now ungrouped.", ephemeral=True)
        return await interaction.response.send_message(
            f"You joined **Group {group_number}**.",
            ephemeral=True,
        )


class RaidGroupJoinView(discord.ui.View):
    def __init__(self, bot, raid_id: int, group_count: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.add_item(RaidGroupJoinSelect(bot, raid_id, group_count))


class RaidControlView(discord.ui.View):
    def __init__(self, bot, show_leader_buttons: bool = True, show_rename_thread_button: bool = True):
        super().__init__(timeout=None)
        self.bot = bot

        # Optionally hide leader-only controls for raiders in ephemeral panels.
        # The public thread panel can still show all buttons while access is
        # enforced via interaction_check.
        self.show_leader_buttons = show_leader_buttons
        self.show_rename_thread_button = show_rename_thread_button

        hide_ids: set[str] = set()
        if not self.show_leader_buttons:
            hide_ids |= {
                "raid_award_dkp",
                "raid_deduct_dkp",
                "raid_update_team",
                "raid_sync_voice",
                "raid_remove_raider",
                "raid_remove_from_group",
                "raid_configure_groups",
                "raid_start_auction",
                "raid_end_auction",
                "raid_close_raid",
            }
        if not self.show_rename_thread_button:
            hide_ids.add("raid_rename_thread")

        if hide_ids:
            to_remove: list[discord.ui.Item] = []
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.custom_id in hide_ids:
                    to_remove.append(child)
            for child in to_remove:
                self.remove_item(child)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await ensure_allowed_guild(interaction):
            return False
        # On bot startup, interaction_check can be called with a mock interaction
        # that has no channel. We return False to prevent errors.
        if not interaction.channel:
            return False

        # Determine which button was pressed, if any.
        custom_id = None
        if getattr(interaction, "data", None) and isinstance(interaction.data, dict):
            custom_id = interaction.data.get("custom_id")

        # Defer most interactions immediately to prevent timeouts.
        # IMPORTANT: Do NOT defer for buttons that will open a modal, since
        # modals must be sent via the initial interaction response.
        if interaction.type != discord.InteractionType.modal_submit and custom_id not in (
            "raid_add_rule",
            "raid_award_dkp",
            "raid_deduct_dkp",
            "raid_remove_raider",
            "raid_remove_from_group",
            "raid_start_auction",
            "raid_show_groups",
            "raid_configure_groups",
            "raid_rename_thread",
        ):
            # Only defer if the interaction hasn't already been acknowledged
            # by another handler (e.g., a command or previous callback).
            if not interaction.response.is_done():
                # "Update Team" should be a public message so raiders can see
                # the current team list. Defer non-ephemerally for that button
                # while keeping other raid controls ephemeral.
                ephemeral = custom_id not in ("raid_update_team", "raid_voice_roster", "raid_sync_voice")
                try:
                    await interaction.response.defer(ephemeral=ephemeral)
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                    # Already responded to, expired, or otherwise invalid; safe to ignore.
                    pass

        # Allow everyone to use the raid "My DKP" button and view rules.
        if custom_id in (
            "raid_my_dkp",
            "raid_view_rules",
            "raid_join_raid",
            "raid_leave_raid",
            "raid_help",
            "raid_show_groups",
            "raid_join_group",
            "raid_voice_roster",
        ):
            return True

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)

        admin_ok = await is_admin(interaction)
        if raid and (interaction.user.id == raid['leader_id'] or admin_ok):
            return True

        if custom_id == "raid_rename_thread" and raid and await is_officer(interaction):
            return True

        # User is not the raid leader. If we haven't responded yet, send an
        # ephemeral error via the initial interaction response; otherwise use
        # a followup. This avoids generic interaction failures on buttons
        # like "Start Auction" that haven't been deferred yet.
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "You must be the raid leader or a bot admin to use this control.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "You must be the raid leader or a bot admin to use this control.",
                    ephemeral=True,
                )
        except discord.HTTPException:
            # Interaction may have expired or otherwise failed; ignore.
            pass

        return False

    @discord.ui.button(label="Join Raid", style=discord.ButtonStyle.success, custom_id="raid_join_raid", row=0)
    async def join_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        if getattr(interaction.user, "bot", False):
            return await interaction.followup.send("Bots cannot join raids.", ephemeral=True)

        raid_id = int(raid["id"])
        user_id = int(interaction.user.id)

        try:
            if await self.bot.db.is_raid_member(raid_id, user_id):
                return await interaction.followup.send("You are already part of this raid.", ephemeral=True)
        except Exception:
            pass

        admin_ok = await is_admin(interaction)
        if user_id == int(raid["leader_id"]) or admin_ok:
            try:
                inserted = await self.bot.db.add_raid_member(raid_id, user_id)
            except Exception:
                inserted = False
            if not inserted:
                return await interaction.followup.send("You are already part of this raid.", ephemeral=True)
            try:
                await self.bot.db.remove_raid_member_exclusion(raid_id, user_id)
            except Exception:
                pass
            try:
                if isinstance(interaction.channel, discord.Thread):
                    await interaction.channel.send(f"{interaction.user.mention} joined the raid.")
            except Exception:
                logging.exception("Failed to send join message to raid thread")
            return await interaction.followup.send("You have been added to the raid.", ephemeral=True)

        try:
            existing = await self.bot.db.get_raid_join_request(raid_id, user_id)
        except Exception:
            existing = None
        if existing is not None:
            try:
                if str(existing["status"]) == "pending":
                    return await interaction.followup.send(
                        "Your join request is already pending approval.",
                        ephemeral=True,
                    )
            except Exception:
                pass

        try:
            await self.bot.db.upsert_raid_join_request(raid_id, user_id, source="button")
        except Exception:
            return await interaction.followup.send(
                "Failed to submit join request. Please try again.",
                ephemeral=True,
            )

        leader_id = int(raid["leader_id"])
        leader_mention = f"<@{leader_id}>"
        if interaction.guild:
            leader_member = interaction.guild.get_member(leader_id)
            if leader_member:
                leader_mention = leader_member.mention

        try:
            if isinstance(interaction.channel, discord.Thread):
                # Send the approval request as a DM to the raid leader only
                leader_member = interaction.guild.get_member(leader_id)
                if leader_member is None:
                    try:
                        leader_member = await interaction.guild.fetch_member(leader_id)
                    except Exception:
                        leader_member = None
                if leader_member:
                    try:
                        await leader_member.send(
                            f"Join request from {interaction.user.mention} for raid in {interaction.channel.mention}. Approve?",
                            view=RaidJoinApprovalView(self.bot, raid_id, user_id),
                        )
                    except discord.Forbidden:
                        # If DMs are disabled, fall back to posting the approval UI
                        # in the raid thread.
                        await interaction.channel.send(
                            f"{leader_mention} approve join request from {interaction.user.mention}?",
                            view=RaidJoinApprovalView(self.bot, raid_id, user_id),
                        )
                else:
                    # Leader not found, fall back to thread message
                    await interaction.channel.send(
                        f"{leader_mention} approve join request from {interaction.user.mention}?",
                        view=RaidJoinApprovalView(self.bot, raid_id, user_id),
                    )
        except Exception:
            logging.exception("Failed to send join approval request")

        return await interaction.followup.send(
            "Join request sent to the raid leader for approval.",
            ephemeral=True,
        )

    @discord.ui.button(label="My DKP 💰", style=discord.ButtonStyle.secondary, custom_id="raid_my_dkp", row=0)
    async def raid_my_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_cog = self.bot.get_cog("UserCog")
        if user_cog:
            await user_cog.show_my_dkp(interaction)
        else:
            await interaction.followup.send("User module is currently offline.", ephemeral=True)

    async def _show_dkp_adjustment_view(self, interaction: discord.Interaction, action: str):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is not active.", ephemeral=True)

        group_count = None
        try:
            group_count = int(raid["group_count"])
        except Exception:
            group_count = None
        if group_count is not None and group_count <= 0:
            group_count = None

        members_by_id: dict[int, discord.Member] = {}

        try:
            member_rows = await self.bot.db.get_raid_members(raid["id"])
        except Exception:
            member_rows = []

        for row in member_rows:
            # sqlite/aiosqlite rows support dict-style access but not .get()
            user_id = row["user_id"]
            if user_id in members_by_id:
                continue
            gm = interaction.guild.get_member(user_id) if interaction.guild else None
            if gm and not gm.bot:
                members_by_id[user_id] = gm

        members = list(members_by_id.values())
        if not members:
            return await interaction.followup.send(
                "No eligible raid members were found. If you are in a voice channel, click \"Update Team\" to add all members in your voice channel to the raid. Or each member can click the \"Join Raid\" button.",
                ephemeral=True,
            )

        view = DKPAdjustmentView(self.bot, action, members, group_count=group_count)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"Who do you want to {action.lower()} DKP?",
                view=view,
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Who do you want to {action.lower()} DKP?",
                view=view,
                ephemeral=True,
            )

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            try:
                await raid_cog.maybe_send_control_panel_ephemeral(interaction, raid=raid)
            except Exception:
                logging.exception("Failed to re-show control panel after award DKP")

    @discord.ui.button(label="Award DKP", style=discord.ButtonStyle.success, custom_id="raid_award_dkp", row=0)
    async def award_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_dkp_adjustment_view(interaction, "Award")

    @discord.ui.button(label="Deduct DKP", style=discord.ButtonStyle.danger, custom_id="raid_deduct_dkp", row=0)
    async def deduct_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_dkp_adjustment_view(interaction, "Deduct")

    @discord.ui.button(label="Start Auction 💎", style=discord.ButtonStyle.primary, custom_id="raid_start_auction", row=1)
    async def start_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Before opening the auction modal, ensure this is an active raid
        # thread and that there is at least one raid participant (either in
        # the raid voice channel or recorded in raid_members).
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message(
                "This is not an active raid thread.",
                ephemeral=True,
            )

        participants: set[int] = set()

        try:
            member_rows = await self.bot.db.get_raid_members(raid["id"])
        except Exception:
            member_rows = []

        for row in member_rows:
            try:
                uid = int(row["user_id"])
            except (KeyError, TypeError, ValueError):
                continue
            participants.add(uid)

        if not participants:
            return await interaction.response.send_message(
                "No eligible raid members were found. If you are in a voice channel, click \"Update Team\" to add all members in your voice channel to the raid. Or each member can click the \"Join Raid\" button. Cannot start auction.",
                ephemeral=True,
            )

        # Also block if an auction is already active for this raid so the
        # leader sees the error immediately instead of only after submitting
        # the modal.
        active_auction = await self.bot.db.get_active_auction(raid["id"])
        if active_auction:
            return await interaction.response.send_message(
                "An auction is already in progress for this raid.",
                ephemeral=True,
            )

        auction_cog = self.bot.get_cog("AuctionCog")
        modal = AuctionStartModal(auction_cog=auction_cog)
        try:
            await interaction.response.send_modal(modal)
        except (discord.InteractionResponded, discord.NotFound):
            try:
                await interaction.followup.send(
                    "This interaction has expired or already received a response. Please try again.",
                    ephemeral=True,
                )
            except Exception:
                logging.exception("Failed to send expired interaction message")  # Fully expired, ignore
        except discord.HTTPException:
            # Optionally log or handle other HTTP errors
            pass

    @discord.ui.button(label="🔄 Update Team", style=discord.ButtonStyle.secondary, custom_id="raid_update_team", row=2)
    async def update_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        await raid_cog.update_team_from_voice_channel(interaction)

    @discord.ui.button(label="🔁 Sync Voice", style=discord.ButtonStyle.secondary, custom_id="raid_sync_voice", row=2)
    async def sync_voice(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        await raid_cog.sync_raid_with_voice_channels(interaction, remove_missing=False, confirm=False)

    @discord.ui.button(label="🎙️ Voice Roster", style=discord.ButtonStyle.secondary, custom_id="raid_voice_roster", row=2)
    async def voice_roster(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        await raid_cog.show_voice_roster(interaction)

    @discord.ui.button(label="End Auction", style=discord.ButtonStyle.primary, custom_id="raid_end_auction", row=1)
    async def end_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        auction_cog = self.bot.get_cog("AuctionCog")
        await auction_cog.end_auction_from_button(interaction)

    @discord.ui.button(label="Close Raid ", style=discord.ButtonStyle.danger, custom_id="raid_close_raid", row=1)
    async def close_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        await raid_cog.close_raid(interaction)

    @discord.ui.button(label="Leave Raid", style=discord.ButtonStyle.secondary, custom_id="raid_leave_raid", row=0)
    async def leave_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        if getattr(interaction.user, "bot", False):
            return await interaction.followup.send("Bots cannot leave raids.", ephemeral=True)

        raid_id = int(raid["id"])
        user_id = int(interaction.user.id)

        try:
            removed = await self.bot.db.remove_raid_member(raid_id, user_id)
        except Exception:
            removed = False

        try:
            await self.bot.db.add_raid_member_exclusion(raid_id, user_id)
        except Exception:
            pass

        try:
            await self.bot.db.delete_raid_join_request(raid_id, user_id)
        except Exception:
            pass

        if not removed:
            return await interaction.followup.send("You are not part of this raid.", ephemeral=True)

        try:
            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(f"{interaction.user.mention} left the raid.")
        except Exception:
            logging.exception("Failed to send leave message to raid thread")

        return await interaction.followup.send("You have left the raid.", ephemeral=True)

    @discord.ui.button(label="Remove Raider", style=discord.ButtonStyle.danger, custom_id="raid_remove_raider", row=2)
    async def remove_raider(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        members_by_id: dict[int, discord.Member] = {}
        try:
            member_rows = await self.bot.db.get_raid_members(raid["id"])
        except Exception:
            member_rows = []

        for row in member_rows:
            user_id = row["user_id"]
            if user_id in members_by_id:
                continue
            gm = interaction.guild.get_member(user_id) if interaction.guild else None
            if gm and not gm.bot:
                members_by_id[user_id] = gm

        members = list(members_by_id.values())
        if not members:
            return await interaction.followup.send("No raid members were found.", ephemeral=True)

        view = RaidMemberRemoveView(self.bot, members)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Who do you want to remove from the raid?",
                view=view,
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "Who do you want to remove from the raid?",
                view=view,
                ephemeral=True,
            )

    @discord.ui.button(label="Remove from group", style=discord.ButtonStyle.secondary, custom_id="raid_remove_from_group", row=3)
    async def remove_from_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        members_by_id: dict[int, discord.Member] = {}
        try:
            member_rows = await self.bot.db.get_raid_members(raid["id"])
        except Exception:
            member_rows = []

        for row in member_rows:
            user_id = row["user_id"]
            if user_id in members_by_id:
                continue
            gm = interaction.guild.get_member(user_id) if interaction.guild else None
            if gm and not gm.bot:
                members_by_id[user_id] = gm

        members = list(members_by_id.values())
        if not members:
            return await interaction.followup.send("No raid members were found.", ephemeral=True)

        view = RaidMemberClearGroupView(self.bot, members)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Who do you want to remove from their group?",
                view=view,
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "Who do you want to remove from their group?",
                view=view,
                ephemeral=True,
            )

    @discord.ui.button(label="Groups", style=discord.ButtonStyle.secondary, custom_id="raid_show_groups", row=2)
    async def show_groups(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        raid_dict = raid
        try:
            if raid is not None and not isinstance(raid, dict):
                raid_dict = dict(raid)
        except Exception:
            raid_dict = raid

        group_count = 0
        try:
            if isinstance(raid_dict, dict):
                group_count = int(raid_dict.get("group_count") or 0)
            elif raid is not None:
                group_count = int(raid["group_count"])
        except Exception:
            group_count = 0

        admin_ok = await is_admin(interaction)
        if raid and (int(interaction.user.id) == int(raid["leader_id"]) or admin_ok) and group_count <= 0:
            modal = RaidGroupSetupModal(raid_cog=raid_cog)
            try:
                return await interaction.response.send_modal(modal)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                try:
                    return await interaction.followup.send("Please try again.", ephemeral=True)
                except discord.HTTPException:
                    return

        if group_count > 0 and interaction.guild:
            embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
            view = RaidGroupSignupView(self.bot, group_count=group_count)

            responded = False
            try:
                responded = bool(interaction.response.is_done())
            except Exception:
                responded = False

            try:
                if not responded:
                    return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                return await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            except discord.HTTPException:
                return

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                pass

        await raid_cog.show_raid_groups(interaction)

    @discord.ui.button(label="Join Group", style=discord.ButtonStyle.secondary, custom_id="raid_join_group", row=3)
    async def join_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        try:
            group_count = await self.bot.db.get_raid_group_count(int(raid["id"]))
        except Exception:
            group_count = None

        if not group_count:
            return await interaction.followup.send(
                "Raid groups have not been configured yet.",
                ephemeral=True,
            )

        view = RaidGroupJoinView(self.bot, int(raid["id"]), int(group_count))
        return await interaction.followup.send("Select your group:", view=view, ephemeral=True)

    @discord.ui.button(label="Group", style=discord.ButtonStyle.secondary, custom_id="raid_configure_groups", row=3)
    async def configure_groups(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            return await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)

        modal = RaidGroupCountModal(raid_cog)
        try:
            await interaction.response.send_modal(modal)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            try:
                await interaction.followup.send("Please try again.", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Rename Thread", style=discord.ButtonStyle.secondary, custom_id="raid_rename_thread", row=1)
    async def rename_thread(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open a modal to rename the raid thread (raid leaders/officers only)."""
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            if not interaction.response.is_done():
                return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        # Authorization check: raid leader, officer, or admin
        if not await is_officer(interaction) and interaction.user.id != raid["leader_id"]:
            if not interaction.response.is_done():
                return await interaction.response.send_message(
                    "You don't have permission to rename this thread.",
                    ephemeral=True,
                )
            return await interaction.followup.send("You don't have permission to rename this thread.", ephemeral=True)

        from ..ui.modals import ThreadRenameModal
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            if not interaction.response.is_done():
                return await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        modal = ThreadRenameModal(raid_cog=raid_cog, raid_id=raid["id"])
        try:
            await interaction.response.send_modal(modal)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            try:
                await interaction.followup.send("Please try again.", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="❓ Help", style=discord.ButtonStyle.secondary, custom_id="raid_help", row=1)
    async def raid_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        description = "\n".join(
            [
                "This panel is used to manage the current raid. Some buttons may be hidden unless you are the raid leader/admin.",
                "",
                "**Join Raid**: Adds you to the raid. If you are not the leader/admin, this sends a join request for approval.",
                "**Leave Raid**: Removes you from the raid and prevents automatic re-adding during sync.",
                "**My DKP 💰**: Shows your current DKP.",
                "",
                "**Award DKP / Deduct DKP** (leader/admin): Pick a raid member, then enter the DKP amount + reason.",
                "**Start Auction 💎** (leader/admin): Opens the auction start form. Requires at least one raid member (use **Update Team** or have people **Join Raid** first).",
                "**End Auction** (leader/admin): Ends the current auction for this raid.",
                "**Close Raid** (leader/admin): Closes out the raid when finished.",
                "",
                "**🔄 Update Team** (leader/admin): Pulls members from the raid voice channel into the raid member list. This is usually the first step before DKP changes/auctions.",
                "**🔁 Sync Voice** (leader/admin): Syncs the raid roster with the configured voice channels. Use if people moved channels after the raid started.",
                "**🎙️ Voice Roster**: Shows who is currently in the raid voice channels.",
                "**Remove Raider** (leader/admin): Removes a member from the raid roster.",
                "**Groups**: Shows the current raid groups (if your guild uses grouping features).",
                "",
                "**Rename Thread** (leader/officer/admin): Renames the raid log thread.",
            ]
        )

        embed = discord.Embed(
            title="Raid Panel Help",
            description=description,
            color=discord.Color.blurple(),
        )

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.HTTPException:
            return

    # The View Rules button is temporarily disabled. To re-enable in the future,
    # uncomment the decorator and method below.
    # @discord.ui.button(label="View Rules \ud83d\udcdd", style=discord.ButtonStyle.secondary, custom_id="raid_view_rules", row=2)
    # async def raid_view_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
    #     if not raid:
    #         return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)
    #
    #     try:
    #         rules = raid["rules"]
    #     except (KeyError, TypeError):
    #         rules = None
    #
    #     if not rules:
    #         msg = "No rules have been set for this raid yet."
    #     else:
    #         msg = f"**Raid Rules:**\n{rules}"
    #
    #     await interaction.followup.send(msg, ephemeral=True)

    # The Add Rule button is temporarily disabled. To re-enable in the future,
    # uncomment the decorator and method below.
    # @discord.ui.button(label="Add Rule \u270f\ufe0f", style=discord.ButtonStyle.primary, custom_id="raid_add_rule", row=2)
    # async def raid_add_rule(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
    #     if not raid:
    #         return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)


class RaidJoinApprovalView(discord.ui.View):
    def __init__(self, bot, raid_id: int, user_id: int):
        super().__init__(timeout=3600)
        self.bot = bot
        self.raid_id = int(raid_id)
        self.user_id = int(user_id)

    async def _get_raid_row(self):
        return await self.bot.db.fetchone(
            "SELECT id, guild_id, leader_id, is_active, thread_id FROM raids WHERE id = ?",
            (self.raid_id,),
        )

    async def _resolve_guild_and_thread(self, raid_row):
        if raid_row is None:
            return None, None

        try:
            guild_id = int(raid_row["guild_id"])
        except Exception:
            guild_id = None
        try:
            thread_id = int(raid_row["thread_id"])
        except Exception:
            thread_id = None

        guild = self.bot.get_guild(guild_id) if guild_id else None
        if guild is None and guild_id:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except Exception:
                guild = None

        thread = None
        if thread_id:
            if guild is not None:
                try:
                    thread = guild.get_thread(thread_id)
                except Exception:
                    thread = None
            if thread is None:
                try:
                    resolved = self.bot.get_channel(thread_id)
                    if resolved is None:
                        resolved = await self.bot.fetch_channel(thread_id)
                    if isinstance(resolved, discord.Thread):
                        thread = resolved
                except Exception:
                    thread = None

        return guild, thread

    async def _notify_requester(self, approved: bool, thread: discord.Thread | None):
        try:
            user = self.bot.get_user(self.user_id)
            if user is None:
                user = await self.bot.fetch_user(self.user_id)
        except Exception:
            user = None

        if user is None:
            return

        try:
            target = thread.mention if thread else "the raid"
            verb = "approved" if approved else "denied"
            await user.send(f"Your request to join {target} was {verb}.")
        except Exception:
            logging.info("Failed to DM join request outcome to user_id=%s", self.user_id)

    async def _authorize(self, interaction: discord.Interaction, raid_row) -> bool:
        if raid_row is None:
            await interaction.response.send_message("This raid was not found.", ephemeral=True)
            return False
        try:
            if int(raid_row["is_active"]) != 1:
                await interaction.response.send_message("This raid is no longer active.", ephemeral=True)
                return False
        except Exception:
            await interaction.response.send_message("This raid is no longer active.", ephemeral=True)
            return False

        admin_ok = await is_admin(interaction)
        if int(interaction.user.id) != int(raid_row["leader_id"]) and not admin_ok:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer()
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                pass
            return False

        return True

    async def _finalize(self, interaction: discord.Interaction):
        try:
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            msg = getattr(interaction, "message", None)
            if msg:
                await msg.edit(view=self)
        except Exception:
            pass

    async def _ensure_pending(self, interaction: discord.Interaction) -> bool:
        req = await self.bot.db.get_raid_join_request(self.raid_id, self.user_id)
        if req is None:
            await interaction.response.send_message("This join request no longer exists.", ephemeral=True)
            await self._finalize(interaction)
            return False
        try:
            if str(req["status"]) != "pending":
                await interaction.response.send_message("This join request is no longer pending.", ephemeral=True)
                await self._finalize(interaction)
                return False
        except Exception:
            await interaction.response.send_message("This join request is no longer pending.", ephemeral=True)
            await self._finalize(interaction)
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_row = await self._get_raid_row()
        if not await self._authorize(interaction, raid_row):
            return
        if not await self._ensure_pending(interaction):
            return

        try:
            inserted = await self.bot.db.add_raid_member(self.raid_id, self.user_id)
        except Exception:
            inserted = False

        try:
            await self.bot.db.remove_raid_member_exclusion(self.raid_id, self.user_id)
        except Exception:
            pass

        await self.bot.db.set_raid_join_request_status(
            self.raid_id,
            self.user_id,
            "approved",
            decided_by=int(interaction.user.id),
        )

        try:
            # Send approval result to the raid thread
            raid_row = await self._get_raid_row()
            guild, thread = await self._resolve_guild_and_thread(raid_row)
            mention = f"<@{self.user_id}>"
            if guild is not None:
                member = guild.get_member(self.user_id)
                if member is not None:
                    mention = member.mention
            if thread:
                if inserted:
                    await thread.send(f"{mention} joined the raid.")
                else:
                    await thread.send(f"{mention} is already part of the raid.")
            await self._notify_requester(True, thread)
        except Exception:
            logging.exception("Failed to send approval result to raid thread")

        await interaction.response.send_message("Approved.", ephemeral=True)
        await self._finalize(interaction)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_row = await self._get_raid_row()
        if not await self._authorize(interaction, raid_row):
            return
        if not await self._ensure_pending(interaction):
            return

        await self.bot.db.set_raid_join_request_status(
            self.raid_id,
            self.user_id,
            "denied",
            decided_by=int(interaction.user.id),
        )

        try:
            # Send denial result to the raid thread
            raid_row = await self._get_raid_row()
            guild, thread = await self._resolve_guild_and_thread(raid_row)
            mention = f"<@{self.user_id}>"
            if guild is not None:
                member = guild.get_member(self.user_id)
                if member is not None:
                    mention = member.mention
            if thread:
                await thread.send(f"Join request denied for {mention}.")
            await self._notify_requester(False, thread)
        except Exception:
            logging.exception("Failed to send denial result to raid thread")

        await interaction.response.send_message("Denied.", ephemeral=True)
        await self._finalize(interaction)

class AuctionBidView(discord.ui.View):
    def __init__(self, bot, auction_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.auction_id = auction_id

    @discord.ui.button(label="Bid", style=discord.ButtonStyle.success, custom_id="auction_bid")
    async def bid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_allowed_guild(interaction):
            return
        auction_cog = self.bot.get_cog("AuctionCog")
        modal = BidModal(auction_cog=auction_cog, auction_id=self.auction_id)
        await interaction.response.send_modal(modal)


class AuctionOpenPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Open Bid Panel", style=discord.ButtonStyle.primary, custom_id="auction_open_panel")
    async def open_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_allowed_guild(interaction):
            return
        auction_cog = self.bot.get_cog("AuctionCog")
        if not auction_cog:
            return await interaction.response.send_message("Auction module is currently offline.", ephemeral=True)

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                pass
        msg = getattr(interaction, "message", None)
        msg_id = getattr(msg, "id", None)
        if not msg_id:
            return await interaction.followup.send("Could not resolve this auction message.", ephemeral=True)

        auction = await self.bot.db.fetchone(
            "SELECT id FROM auctions WHERE message_id = ? AND is_active = 1",
            (int(msg_id),),
        )
        if not auction:
            return await interaction.followup.send("This auction has ended.", ephemeral=True)

        await auction_cog.send_bid_panel(interaction, int(auction["id"]))


class RaidOpenPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Open Raid Control Panel",
        style=discord.ButtonStyle.primary,
        custom_id="raid_open_panel",
    )
    async def open_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_allowed_guild(interaction):
            return
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            return await interaction.response.send_message(
                "Raid module is currently offline.",
                ephemeral=True,
            )
        await raid_cog.send_ephemeral_raid_panel(interaction)


class RaidGroupSignupSelect(discord.ui.Select):
    def __init__(self, bot, group_count: int | None = None):
        self.bot = bot
        max_groups = 25
        try:
            if group_count is not None:
                max_groups = max(1, min(int(group_count), 25))
        except Exception:
            max_groups = 25
        options = [
            discord.SelectOption(label=f"Group {i}", value=str(i))
            for i in range(1, max_groups + 1)
        ]
        super().__init__(
            placeholder="Select a group...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="raid_group_select",
        )

    async def callback(self, interaction: discord.Interaction):
        if not await ensure_allowed_guild(interaction):
            return
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)
                else:
                    await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
            except discord.HTTPException:
                pass
            return

        value = None
        try:
            value = self.values[0]
        except Exception:
            value = None

        await raid_cog.handle_group_signup(interaction, value)


class RaidGroupSignupView(discord.ui.View):
    def __init__(self, bot, group_count: int | None = None):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(RaidGroupSignupSelect(bot, group_count=group_count))

    @discord.ui.button(label="Leave group", style=discord.ButtonStyle.secondary, custom_id="raid_group_leave")
    async def leave_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_allowed_guild(interaction):
            return
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)
                else:
                    await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
            except discord.HTTPException:
                pass
            return

        await raid_cog.handle_group_signup(interaction, "0")
