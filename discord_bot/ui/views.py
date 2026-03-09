import discord
import logging
import re
import random
import subprocess
from pathlib import Path
from .modals import DKPAdjustmentModal, AuctionStartModal, BidModal, RaidRulesModal, RaidGroupCountModal, RaidGroupSetupModal, RaidTimedAwardModal, RaidReverseDKPModal, DefaultDKPAwardModal, GuildBankDepositModal, GuildBankWithdrawModal
from discord.ui import UserSelect, Select
from .. import __version__ as bot_version
from ..utils import (
    is_admin,
    is_officer,
    ensure_allowed_guild,
    create_info_embed,
)


CHANGELOG_PATH = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
CHANGELOG_DIR = Path(__file__).resolve().parents[2] / "changelog"

WORKTREE_STATUS_HEADER = "## Local worktree changes (not yet committed)"

FALLBACK_CHANGELOG_ENTRIES: dict[str, str] = {
    "Unreleased": "No changelog file was found.",
}

_CHANGELOG_CACHE: dict[str, object] = {
    "mtime": None,
    "versions": [],
    "entries": {},
}


def _safe_member_display_name(member: object) -> str:
    name = getattr(member, "display_name", None)
    if not name:
        name = getattr(member, "name", None)
    if not name:
        name = ""
    return str(name)


def _member_sort_key(member: object) -> str:
    return _safe_member_display_name(member).casefold()


def _is_random_member_order(member_list_order: object) -> bool:
    return str(member_list_order).strip().casefold() == "random"


async def _has_grouped_members(bot, raid_id: int | None) -> bool:
    if bot is None or raid_id is None:
        return False
    try:
        group_rows = await bot.db.get_raid_member_groups(int(raid_id))
    except Exception:
        return False
    for row in list(group_rows or []):
        try:
            grp = row["group_number"]
        except Exception:
            try:
                grp = row.get("group_number") if isinstance(row, dict) else None
            except Exception:
                grp = None
        if grp is not None and int(grp) > 0:
            return True
    return False


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


def _extract_path_from_porcelain_line(line: str) -> str:
    if len(line) <= 3:
        return ""
    path = line[3:].strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1].strip()
    if path.startswith('"') and path.endswith('"') and len(path) >= 2:
        path = path[1:-1]
    return path


def _categorize_path(path: str) -> str:
    p = path.replace("\\", "/")
    if p == "CHANGELOG.md" or p.startswith("changelog/"):
        return "Changelog"
    if p.startswith("discord_bot/ui/"):
        return "UI"
    if p.startswith("discord_bot/cogs/raid") or p.startswith("discord_bot/cogs/raid_"):
        return "Raids"
    if p.startswith("discord_bot/cogs/"):
        return "Bot"
    if p.startswith("discord_bot/"):
        return "Bot"
    if p.startswith("tests/"):
        return "Tests"
    if p.startswith("js-e2e/"):
        return "E2E"
    if p.startswith("Documentation/") or p == "mkdocs.yml":
        return "Docs"
    if p.startswith(".github/"):
        return "CI"
    if p.startswith("scripts/"):
        return "Dev tooling"
    if p.startswith("licensing_server/"):
        return "Licensing"
    if p.startswith("requirements"):
        return "Dependencies"
    return "Other"


def _feature_hint(area: str) -> str:
    hints = {
        "UI": "Interaction and panel UX work",
        "Raids": "Raid management, signup flows, and roster/voice tooling",
        "Bot": "Command behavior and bot logic updates",
        "Tests": "Unit/integration regression coverage",
        "E2E": "End-to-end/staging smoke coverage",
        "Docs": "User/admin documentation updates",
        "CI": "CI/staging automation improvements",
        "Dev tooling": "Local developer tooling and scripts",
        "Changelog": "Release notes and changelog maintenance",
        "Licensing": "License server / entitlement checks",
        "Dependencies": "Dependency and packaging updates",
        "Other": "Miscellaneous internal updates",
    }
    return hints.get(area, hints["Other"])


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

    combined_counts: dict[str, int] = {}
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

        counts: dict[str, int] = {}
        for ln in status_lines:
            fp = _extract_path_from_porcelain_line(ln)
            if not fp:
                continue
            cat = _categorize_path(fp)
            counts[cat] = counts.get(cat, 0) + 1

        if not counts:
            continue

        for k, v in counts.items():
            combined_counts[k] = combined_counts.get(k, 0) + v

    if not combined_counts:
        return ""

    combined_categories = [
        cat
        for cat, _n in sorted(combined_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    lines: list[str] = []
    lines.append(WORKTREE_STATUS_HEADER)
    lines.append("")
    lines.append("### In-progress summary")
    lines.append("")
    lines.append("- Areas touched:")
    for cat in combined_categories:
        lines.append(f"  - {cat}: {_feature_hint(cat)}")
    return "\n".join(lines)


def _create_changelog_embeds(version: str, entries: dict[str, str]) -> list[discord.Embed]:
    notes = entries.get(version)
    if not notes:
        notes = "No changelog entry is available for this version."

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


class RaidPointsScopeSelect(Select):
    def __init__(self, *, default_value: str = "raid"):
        options = [
            discord.SelectOption(label="raid", value="raid", default=(default_value == "raid")),
            discord.SelectOption(label="total", value="total", default=(default_value == "total")),
        ]
        super().__init__(
            placeholder="Scope",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, RaidPointsOptionsView):
            return
        view.scope = self.values[0]
        for option in self.options:
            option.default = option.value == view.scope
        await interaction.response.edit_message(view=view)


class RaidPointsSortSelect(Select):
    def __init__(self, *, default_value: str = "dkp"):
        options = [
            discord.SelectOption(label="dkp", value="dkp", default=(default_value == "dkp")),
            discord.SelectOption(label="name", value="name", default=(default_value == "name")),
        ]
        super().__init__(
            placeholder="Sort",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, RaidPointsOptionsView):
            return
        view.sort = self.values[0]
        for option in self.options:
            option.default = option.value == view.sort
        await interaction.response.edit_message(view=view)


class RaidPointsOptionsView(discord.ui.View):
    def __init__(
        self,
        bot,
        *,
        raid_cog,
        return_to_popup: bool,
        popup_can_manage: bool = False,
        popup_can_rename_thread: bool = False,
    ):
        super().__init__(timeout=180)
        self.bot = bot
        self.raid_cog = raid_cog
        self.return_to_popup = bool(return_to_popup)
        self.popup_can_manage = bool(popup_can_manage)
        self.popup_can_rename_thread = bool(popup_can_rename_thread)

        self.scope = "raid"
        self.sort = "dkp"

        self.add_item(RaidPointsScopeSelect(default_value=self.scope))
        self.add_item(RaidPointsSortSelect(default_value=self.sort))

    @discord.ui.button(label="Submit", style=discord.ButtonStyle.primary, row=2)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.raid_cog.show_raid_points(interaction, scope=self.scope, sort=self.sort)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.return_to_popup:
            return await interaction.response.edit_message(view=None)
        view = RaidPopupView(
            self.bot,
            mode="manage",
            can_manage=self.popup_can_manage,
            can_rename_thread=self.popup_can_rename_thread,
        )
        embed = view._manage_embed(interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, row=3)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)


class RaidTimedAwardControlView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=600)
        self.bot = bot

    @discord.ui.button(
        label="Stop Timed DKP",
        style=discord.ButtonStyle.danger,
        custom_id="raid_timed_dkp_stop_from_modal",
        row=0,
    )
    async def stop_timed_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog") if self.bot else None
        if not raid_cog:
            try:
                if not interaction.response.is_done():
                    return await interaction.response.send_message(
                        "Raid module is currently offline.",
                        ephemeral=True,
                    )
                return await interaction.followup.send(
                    "Raid module is currently offline.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                return

        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass

        await raid_cog.disable_timed_award(interaction)

        try:
            msg = getattr(interaction, "message", None)
            if msg is not None:
                await msg.edit(view=None)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="raid_timed_dkp_modal_close", row=1)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)


class WelcomeLegacyView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_allowed_guild(interaction)

    def _main_embed(self, interaction: discord.Interaction) -> discord.Embed:
        user = getattr(interaction, "user", None)
        display_name = getattr(user, "display_name", None) or getattr(user, "name", None) or "User"
        return create_info_embed(
            f"DKP Panel for {display_name}",
            "Use the buttons below to access DKP bot features. This panel is only visible to you.",
        )

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
    def __init__(
        self,
        bot,
        action: str,
        members: list[discord.Member],
        member_list_order: str = "name",
        *,
        max_values: int = 1,
    ):
        self.bot = bot
        self.action = action
        # Track which members are currently in the raid voice channel so we can
        # enforce that only active raiders are selected, while still allowing
        # Discord's built-in type-to-search user picker.
        self._allowed_member_ids = {m.id for m in members}

        members_sorted = list(members)
        if str(member_list_order).strip().casefold() == "random":
            random.shuffle(members_sorted)
        else:
            members_sorted.sort(key=_member_sort_key)

        options = [
            discord.SelectOption(label=_safe_member_display_name(m)[:100], value=str(m.id))
            for m in members_sorted
        ][:25]

        max_select = max(1, min(int(max_values), len(options)))
        super().__init__(
            placeholder=f"Select member(s) to {action.lower()} DKP...",
            min_values=1,
            max_values=max_select,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        raid_cog = self.bot.get_cog("RaidCog")

        selected_members: list[discord.Member] = []
        if interaction.guild:
            for raw_id in list(self.values or []):
                try:
                    selected_id = int(raw_id)
                except (ValueError, TypeError):
                    continue
                if selected_id not in self._allowed_member_ids:
                    continue
                member = interaction.guild.get_member(selected_id)
                if member is not None:
                    selected_members.append(member)

        if not selected_members:
            try:
                await interaction.response.edit_message(
                    content="That member is not an eligible raid member.",
                    view=self.view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        modal = DKPAdjustmentModal(
            action=self.action,
            raid_cog=raid_cog,
            members=selected_members,
            source="raid_panel",
        )
        await interaction.response.send_modal(modal)


class RaidMemberRemoveSelect(Select):
    def __init__(self, bot, members: list[discord.Member], member_list_order: str = "name"):
        self.bot = bot
        self._allowed_member_ids = {m.id for m in members}

        members_sorted = list(members)
        if str(member_list_order).strip().casefold() == "random":
            random.shuffle(members_sorted)
        else:
            members_sorted.sort(key=_member_sort_key)

        options = [
            discord.SelectOption(label=_safe_member_display_name(m)[:100], value=str(m.id))
            for m in members_sorted
        ][:25]

        super().__init__(
            placeholder="Select a member to remove from the raid...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        return_to_popup = bool(getattr(view, "return_to_popup", False))
        popup_can_manage = bool(getattr(view, "popup_can_manage", False))
        popup_can_rename_thread = bool(getattr(view, "popup_can_rename_thread", False))

        async def respond_notice(title: str, message: str):
            embed = create_info_embed(title, message)
            target_view = view
            if return_to_popup:
                target_view = RaidPopupView(
                    self.bot,
                    mode=("manage" if popup_can_manage else "main"),
                    can_manage=popup_can_manage,
                    can_rename_thread=popup_can_rename_thread,
                )
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=target_view)
                else:
                    await interaction.edit_original_response(embed=embed, view=target_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        if not interaction.channel:
            await respond_notice("Remove Raider", "This is not a raid thread.")
            return

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            await respond_notice("Remove Raider", "This is not an active raid thread.")
            return

        try:
            selected_id = int(self.values[0])
        except (ValueError, TypeError):
            await respond_notice("Remove Raider", "Invalid selection.")
            return

        if selected_id not in self._allowed_member_ids:
            await respond_notice("Remove Raider", "That member is not a raid member.")
            return

        raid_id = int(raid["id"])

        try:
            removed = await self.bot.db.remove_raid_member(raid_id, selected_id)
        except Exception:
            removed = False

        try:
            await self.bot.db.add_raid_member_exclusion(raid_id, selected_id, reason="manual")
        except Exception:
            pass

        try:
            await self.bot.db.delete_raid_join_request(raid_id, selected_id)
        except Exception:
            pass

        member = interaction.guild.get_member(selected_id) if interaction.guild else None
        mention = member.mention if member else f"<@{selected_id}>"

        if not removed:
            await respond_notice("Remove Raider", f"{mention} is not part of this raid.")
            return

        try:
            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(f"{mention} was removed from the raid.")
        except Exception:
            logging.exception("Failed to send removal message to raid thread")

        embed = create_info_embed("Remove Raider", f"Removed {mention} from the raid.")

        if return_to_popup:
            panel_view = RaidPopupView(
                self.bot,
                mode=("manage" if popup_can_manage else "main"),
                can_manage=popup_can_manage,
                can_rename_thread=popup_can_rename_thread,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=panel_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                try:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=panel_view)
                except Exception:
                    return
            return

        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return


class RaidMemberRemoveView(discord.ui.View):
    def __init__(
        self,
        bot,
        members: list[discord.Member],
        member_list_order: str = "name",
        *,
        return_to_popup: bool = False,
        popup_can_manage: bool = False,
        popup_can_rename_thread: bool = False,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.members = list(members)
        self.member_list_order = str(member_list_order)
        self.return_to_popup = bool(return_to_popup)
        self.popup_can_manage = bool(popup_can_manage)
        self.popup_can_rename_thread = bool(popup_can_rename_thread)

        self.add_item(
            RaidMemberRemoveSelect(
                bot,
                self.members,
                member_list_order=self.member_list_order,
            )
        )

        is_random = _is_random_member_order(self.member_list_order)
        toggle_btn = discord.ui.Button(
            label=("Sort A-Z" if is_random else "Shuffle"),
            style=discord.ButtonStyle.secondary,
            row=1,
        )

        async def _toggle_cb(interaction: discord.Interaction):
            new_order = "name" if is_random else "random"
            new_view = RaidMemberRemoveView(
                self.bot,
                self.members,
                member_list_order=new_order,
                return_to_popup=self.return_to_popup,
                popup_can_manage=self.popup_can_manage,
                popup_can_rename_thread=self.popup_can_rename_thread,
            )
            try:
                await interaction.response.edit_message(view=new_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        toggle_btn.callback = _toggle_cb
        self.add_item(toggle_btn)


class RaidMemberClearGroupSelect(Select):
    def __init__(self, bot, members: list[discord.Member], member_list_order: str = "name"):
        self.bot = bot
        self._allowed_member_ids = {m.id for m in members}

        members_sorted = list(members)
        if str(member_list_order).strip().casefold() == "random":
            random.shuffle(members_sorted)
        else:
            members_sorted.sort(key=_member_sort_key)

        options = [
            discord.SelectOption(label=_safe_member_display_name(m)[:100], value=str(m.id))
            for m in members_sorted
        ][:25]

        super().__init__(
            placeholder="Select a member to remove from their group...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        return_to_popup = bool(getattr(view, "return_to_popup", False))
        return_to_group_signup = bool(getattr(view, "return_to_group_signup", False))
        popup_can_manage = bool(getattr(view, "popup_can_manage", False))
        popup_can_rename_thread = bool(getattr(view, "popup_can_rename_thread", False))

        async def respond_notice(message: str):
            embed = create_info_embed("Remove from Group", message)
            target_view = view
            if return_to_popup:
                target_view = RaidPopupView(
                    self.bot,
                    mode=("manage" if popup_can_manage else "main"),
                    can_manage=popup_can_manage,
                    can_rename_thread=popup_can_rename_thread,
                )
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=target_view)
                else:
                    await interaction.edit_original_response(embed=embed, view=target_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        if not interaction.channel:
            await respond_notice("This is not a raid thread.")
            return

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            await respond_notice("This is not an active raid thread.")
            return

        try:
            selected_id = int(self.values[0])
        except (ValueError, TypeError):
            await respond_notice("Invalid selection.")
            return

        if selected_id not in self._allowed_member_ids:
            await respond_notice("That member is not a raid member.")
            return

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

        embed = create_info_embed("Remove from Group", f"Cleared group assignment for {mention}.")

        if return_to_group_signup:
            raid_cog = self.bot.get_cog("RaidCog")
            if raid_cog and interaction.guild:
                try:
                    raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                    raid_dict = raid
                    if raid is not None and not isinstance(raid, dict):
                        raid_dict = dict(raid)
                    group_count = 0
                    if isinstance(raid_dict, dict):
                        group_count = int(raid_dict.get("group_count") or 0)
                    signup_embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                    signup_view = RaidGroupSignupModalView(
                        self.bot,
                        group_count=group_count,
                        can_manage=bool(getattr(view, "group_signup_can_manage", False)),
                        return_to_popup=bool(getattr(view, "group_signup_return_to_popup", False)),
                        popup_can_manage=bool(getattr(view, "group_signup_popup_can_manage", False)),
                        popup_can_rename_thread=bool(getattr(view, "group_signup_popup_can_rename_thread", False)),
                    )
                    await interaction.response.edit_message(
                        content=f"Cleared group assignment for {mention}.",
                        embed=signup_embed,
                        view=signup_view,
                    )
                    return
                except Exception:
                    pass

        if return_to_popup:
            panel_view = RaidPopupView(
                self.bot,
                mode=("manage" if popup_can_manage else "main"),
                can_manage=popup_can_manage,
                can_rename_thread=popup_can_rename_thread,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=panel_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                try:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=panel_view)
                except Exception:
                    return
            return

        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return
        return


class RaidMemberClearGroupView(discord.ui.View):
    def __init__(
        self,
        bot,
        members: list[discord.Member],
        member_list_order: str = "name",
        *,
        return_to_popup: bool = False,
        popup_can_manage: bool = False,
        popup_can_rename_thread: bool = False,
        return_to_group_signup: bool = False,
        group_signup_can_manage: bool = False,
        group_signup_return_to_popup: bool = False,
        group_signup_popup_can_manage: bool = False,
        group_signup_popup_can_rename_thread: bool = False,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.members = list(members)
        self.member_list_order = str(member_list_order)
        self.return_to_popup = bool(return_to_popup)
        self.popup_can_manage = bool(popup_can_manage)
        self.popup_can_rename_thread = bool(popup_can_rename_thread)
        self.return_to_group_signup = bool(return_to_group_signup)
        self.group_signup_can_manage = bool(group_signup_can_manage)
        self.group_signup_return_to_popup = bool(group_signup_return_to_popup)
        self.group_signup_popup_can_manage = bool(group_signup_popup_can_manage)
        self.group_signup_popup_can_rename_thread = bool(group_signup_popup_can_rename_thread)

        self.add_item(
            RaidMemberClearGroupSelect(
                bot,
                self.members,
                member_list_order=self.member_list_order,
            )
        )

        is_random = _is_random_member_order(self.member_list_order)
        toggle_btn = discord.ui.Button(
            label=("Sort A-Z" if is_random else "Shuffle"),
            style=discord.ButtonStyle.secondary,
            row=1,
        )

        async def _toggle_cb(interaction: discord.Interaction):
            new_order = "name" if is_random else "random"
            new_view = RaidMemberClearGroupView(
                self.bot,
                self.members,
                member_list_order=new_order,
                return_to_popup=self.return_to_popup,
                popup_can_manage=self.popup_can_manage,
                popup_can_rename_thread=self.popup_can_rename_thread,
                return_to_group_signup=self.return_to_group_signup,
                group_signup_can_manage=self.group_signup_can_manage,
                group_signup_return_to_popup=self.group_signup_return_to_popup,
                group_signup_popup_can_manage=self.group_signup_popup_can_manage,
                group_signup_popup_can_rename_thread=self.group_signup_popup_can_rename_thread,
            )
            try:
                await interaction.response.edit_message(view=new_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        toggle_btn.callback = _toggle_cb
        self.add_item(toggle_btn)

        if self.return_to_group_signup:
            back_btn = discord.ui.Button(
                label="Back",
                style=discord.ButtonStyle.secondary,
                custom_id="raid_group_signup_modal_back_from_clear",
                row=2,
            )

            async def _back_cb(interaction: discord.Interaction):
                raid_cog = self.bot.get_cog("RaidCog")
                if not raid_cog or interaction.guild is None:
                    return

                raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                raid_dict = raid
                if raid is not None and not isinstance(raid, dict):
                    raid_dict = dict(raid)

                group_count = 0
                if isinstance(raid_dict, dict):
                    group_count = int(raid_dict.get("group_count") or 0)

                embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                view = RaidGroupSignupModalView(
                    self.bot,
                    group_count=group_count,
                    can_manage=self.group_signup_can_manage,
                    return_to_popup=self.group_signup_return_to_popup,
                    popup_can_manage=self.group_signup_popup_can_manage,
                    popup_can_rename_thread=self.group_signup_popup_can_rename_thread,
                )
                await interaction.response.edit_message(content=None, embed=embed, view=view)

            back_btn.callback = _back_cb
            self.add_item(back_btn)


class RaidMemberAssignGroupMemberSelect(Select):
    def __init__(self, bot, members: list[discord.Member], member_list_order: str = "name"):
        self.bot = bot
        self._allowed_member_ids = {m.id for m in members}

        members_sorted = list(members)
        if str(member_list_order).strip().casefold() == "random":
            random.shuffle(members_sorted)
        else:
            members_sorted.sort(key=_member_sort_key)

        options = [
            discord.SelectOption(label=_safe_member_display_name(m)[:100], value=str(m.id))
            for m in members_sorted
        ][:25]

        super().__init__(
            placeholder="Select a member...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        return_to_popup = bool(getattr(view, "return_to_popup", False))
        popup_can_manage = bool(getattr(view, "popup_can_manage", False))
        popup_can_rename_thread = bool(getattr(view, "popup_can_rename_thread", False))

        async def respond_notice(message: str):
            embed = create_info_embed("Set Group", message)
            target_view = view
            if return_to_popup:
                target_view = RaidPopupView(
                    self.bot,
                    mode=("manage" if popup_can_manage else "main"),
                    can_manage=popup_can_manage,
                    can_rename_thread=popup_can_rename_thread,
                )
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=target_view)
                else:
                    await interaction.edit_original_response(embed=embed, view=target_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        try:
            selected_id = int(self.values[0])
        except (ValueError, TypeError):
            await respond_notice("Invalid selection.")
            return

        if selected_id not in self._allowed_member_ids:
            await respond_notice("That member is not a raid member.")
            return

        if view is None or not isinstance(view, RaidMemberAssignGroupView):
            await respond_notice("Please try again.")
            return

        view.selected_member_id = int(selected_id)
        member = interaction.guild.get_member(selected_id) if interaction.guild else None
        mention = member.mention if member else f"<@{selected_id}>"

        try:
            await interaction.response.edit_message(
                content=f"Selected {mention}. Now pick a group.",
                view=view,
            )
        except discord.HTTPException:
            return


class RaidMemberAssignGroupNumberSelect(Select):
    def __init__(self, bot, group_count: int):
        self.bot = bot
        self.group_count = int(group_count)

        options: list[discord.SelectOption] = [
            discord.SelectOption(label=f"Group {i}", value=str(i))
            for i in range(1, min(self.group_count, 25) + 1)
        ]
        options.append(discord.SelectOption(label="Not in raid", value="0"))
        options.append(discord.SelectOption(label="Ungrouped", value="ungrouped"))

        super().__init__(
            placeholder="Select a group...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if view is None or not isinstance(view, RaidMemberAssignGroupView):
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("Set Group", "Please try again."),
                    view=None,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        if view.selected_member_id is None:
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("Set Group", "Select a member first."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        raw = (self.values[0] or "").strip()
        if raw == "ungrouped":
            group_number = None
        else:
            try:
                group_number = int(raw)
            except Exception:
                group_number = None
        if group_number is not None and group_number != 0 and (group_number < 1 or group_number > view.group_count):
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("Set Group", "Invalid group selection."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        try:
            await self.bot.db.set_raid_member_group(int(view.raid_id), int(view.selected_member_id), group_number)
        except Exception:
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("Set Group", "Failed to update group. Please try again."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        member = interaction.guild.get_member(int(view.selected_member_id)) if interaction.guild else None
        mention = member.mention if member else f"<@{int(view.selected_member_id)}>"

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog and interaction.guild and isinstance(interaction.channel, discord.Thread):
            try:
                raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                raid_dict = raid
                if raid is not None and not isinstance(raid, dict):
                    raid_dict = dict(raid)
                embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                await raid_cog._ensure_group_panel_message(interaction.channel, raid_dict, embed)
            except Exception:
                logging.exception("Failed to refresh group signup message after assigning member group")

        try:
            if isinstance(interaction.channel, discord.Thread):
                if group_number is None:
                    await interaction.channel.send(f"{mention} was removed from their group.")
                elif int(group_number) == 0:
                    await interaction.channel.send(f"{mention} was assigned to **Not in raid**.")
                else:
                    await interaction.channel.send(f"{mention} was assigned to **Group {int(group_number)}**.")
        except Exception:
            logging.exception("Failed to send group assignment message to raid thread")

        return_to_popup = bool(getattr(view, "return_to_popup", False))
        return_to_group_signup = bool(getattr(view, "return_to_group_signup", False))
        popup_can_manage = bool(getattr(view, "popup_can_manage", False))
        popup_can_rename_thread = bool(getattr(view, "popup_can_rename_thread", False))

        if group_number is None:
            embed = create_info_embed("Set Group", f"Cleared group assignment for {mention}.")
            content = f"Cleared group assignment for {mention}."
        elif int(group_number) == 0:
            embed = create_info_embed("Set Group", f"Assigned {mention} to **Not in raid**.")
            content = f"Assigned {mention} to **Not in raid**."
        else:
            embed = create_info_embed("Set Group", f"Assigned {mention} to **Group {int(group_number)}**.")
            content = f"Assigned {mention} to **Group {int(group_number)}**."

        if return_to_group_signup:
            raid_cog = self.bot.get_cog("RaidCog")
            if raid_cog and interaction.guild:
                try:
                    raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                    raid_dict = raid
                    if raid is not None and not isinstance(raid, dict):
                        raid_dict = dict(raid)
                    group_count = 0
                    if isinstance(raid_dict, dict):
                        group_count = int(raid_dict.get("group_count") or 0)
                    signup_embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                    signup_view = RaidGroupSignupModalView(
                        self.bot,
                        group_count=group_count,
                        can_manage=bool(getattr(view, "group_signup_can_manage", False)),
                        return_to_popup=bool(getattr(view, "group_signup_return_to_popup", False)),
                        popup_can_manage=bool(getattr(view, "group_signup_popup_can_manage", False)),
                        popup_can_rename_thread=bool(getattr(view, "group_signup_popup_can_rename_thread", False)),
                    )
                    await interaction.response.edit_message(
                        content=content,
                        embed=signup_embed,
                        view=signup_view,
                    )
                    return
                except Exception:
                    pass

        if return_to_popup:
            panel_view = RaidPopupView(
                self.bot,
                mode=("manage" if popup_can_manage else "main"),
                can_manage=popup_can_manage,
                can_rename_thread=popup_can_rename_thread,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=panel_view, content=None)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                try:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=panel_view, content=None)
                except Exception:
                    return
            return

        try:
            await interaction.response.edit_message(content=content, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return
        return


class RaidMemberAssignGroupView(discord.ui.View):
    def __init__(
        self,
        bot,
        raid_id: int,
        members: list[discord.Member],
        group_count: int,
        member_list_order: str = "name",
        *,
        show_bulk_ungrouped: bool = False,
        return_to_popup: bool = False,
        popup_can_manage: bool = False,
        popup_can_rename_thread: bool = False,
        return_to_group_signup: bool = False,
        group_signup_can_manage: bool = False,
        group_signup_return_to_popup: bool = False,
        group_signup_popup_can_manage: bool = False,
        group_signup_popup_can_rename_thread: bool = False,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.raid_id = int(raid_id)
        self.members = list(members)
        self.group_count = int(group_count)
        self.member_list_order = str(member_list_order)
        self.show_bulk_ungrouped = bool(show_bulk_ungrouped)
        self.selected_member_id: int | None = None
        self.return_to_popup = bool(return_to_popup)
        self.popup_can_manage = bool(popup_can_manage)
        self.popup_can_rename_thread = bool(popup_can_rename_thread)
        self.return_to_group_signup = bool(return_to_group_signup)
        self.group_signup_can_manage = bool(group_signup_can_manage)
        self.group_signup_return_to_popup = bool(group_signup_return_to_popup)
        self.group_signup_popup_can_manage = bool(group_signup_popup_can_manage)
        self.group_signup_popup_can_rename_thread = bool(group_signup_popup_can_rename_thread)

        self.add_item(
            RaidMemberAssignGroupMemberSelect(
                bot,
                self.members,
                member_list_order=self.member_list_order,
            )
        )
        self.add_item(RaidMemberAssignGroupNumberSelect(bot, group_count))

        is_random = _is_random_member_order(self.member_list_order)
        toggle_btn = discord.ui.Button(
            label=("Sort A-Z" if is_random else "Shuffle"),
            style=discord.ButtonStyle.secondary,
            row=2,
        )

        async def _toggle_cb(interaction: discord.Interaction):
            new_order = "name" if is_random else "random"
            new_view = RaidMemberAssignGroupView(
                self.bot,
                self.raid_id,
                self.members,
                self.group_count,
                member_list_order=new_order,
                show_bulk_ungrouped=self.show_bulk_ungrouped,
                return_to_popup=self.return_to_popup,
                popup_can_manage=self.popup_can_manage,
                popup_can_rename_thread=self.popup_can_rename_thread,
                return_to_group_signup=self.return_to_group_signup,
                group_signup_can_manage=self.group_signup_can_manage,
                group_signup_return_to_popup=self.group_signup_return_to_popup,
                group_signup_popup_can_manage=self.group_signup_popup_can_manage,
                group_signup_popup_can_rename_thread=self.group_signup_popup_can_rename_thread,
            )
            new_view.selected_member_id = self.selected_member_id
            try:
                await interaction.response.edit_message(view=new_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        toggle_btn.callback = _toggle_cb
        self.add_item(toggle_btn)

        if self.return_to_group_signup:
            back_btn = discord.ui.Button(
                label="Back",
                style=discord.ButtonStyle.secondary,
                custom_id="raid_group_signup_modal_back_from_assign",
                row=3,
            )

            async def _back_cb(interaction: discord.Interaction):
                raid_cog = self.bot.get_cog("RaidCog")
                if not raid_cog or interaction.guild is None:
                    return

                raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                raid_dict = raid
                if raid is not None and not isinstance(raid, dict):
                    raid_dict = dict(raid)

                group_count = 0
                if isinstance(raid_dict, dict):
                    group_count = int(raid_dict.get("group_count") or 0)

                embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                view = RaidGroupSignupModalView(
                    self.bot,
                    group_count=group_count,
                    can_manage=self.group_signup_can_manage,
                    return_to_popup=self.group_signup_return_to_popup,
                    popup_can_manage=self.group_signup_popup_can_manage,
                    popup_can_rename_thread=self.group_signup_popup_can_rename_thread,
                )
                await interaction.response.edit_message(content=None, embed=embed, view=view)

            back_btn.callback = _back_cb
            self.add_item(back_btn)

        if self.show_bulk_ungrouped and self.group_count > 0:
            async def _bulk_ungrouped_cb(interaction: discord.Interaction):
                raid_cog = self.bot.get_cog("RaidCog")
                if not raid_cog or interaction.guild is None:
                    return

                # Defer early to avoid the 3-second interaction deadline
                # during the DB-heavy assign_ungrouped_to_group work.
                try:
                    await interaction.response.defer()
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                    pass

                raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                if not raid:
                    return await interaction.edit_original_response(
                        content="This is not an active raid thread.",
                    )

                has_grouped = await _has_grouped_members(self.bot, int(raid["id"]))
                if not has_grouped:
                    return await interaction.edit_original_response(
                        content="At least one group must already have members before you can bulk assign ungrouped players.",
                    )

                assigned = await raid_cog.assign_ungrouped_to_group(
                    interaction,
                    raid_id=int(raid["id"]),
                    group_number=int(self.group_count),
                )

                try:
                    raid_dict = raid
                    if raid is not None and not isinstance(raid, dict):
                        raid_dict = dict(raid)
                    raid_dict["group_count"] = int(self.group_count)
                    signup_embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                    signup_view = RaidGroupSignupModalView(
                        self.bot,
                        group_count=int(self.group_count),
                        can_manage=bool(getattr(self, "group_signup_can_manage", False)),
                        return_to_popup=bool(getattr(self, "group_signup_return_to_popup", False)),
                        popup_can_manage=bool(getattr(self, "group_signup_popup_can_manage", False)),
                        popup_can_rename_thread=bool(getattr(self, "group_signup_popup_can_rename_thread", False)),
                    )
                    await interaction.edit_original_response(
                        content=None,
                        embed=signup_embed,
                        view=signup_view,
                    )
                except Exception:
                    pass

                # Send thread announcement after the UI has been updated so
                # users see the button interaction resolve before the message.
                if assigned and isinstance(interaction.channel, discord.Thread):
                    try:
                        await interaction.channel.send(
                            f"Added **{assigned}** ungrouped member(s) to **Group {int(self.group_count)}**."
                        )
                    except Exception:
                        pass

            bulk_btn = discord.ui.Button(
                label=f"Add all ungrouped → Group {self.group_count}",
                style=discord.ButtonStyle.primary,
                custom_id="raid_group_signup_modal_bulk_ungrouped",
                row=4,
            )
            bulk_btn.callback = _bulk_ungrouped_cb
            self.add_item(bulk_btn)


class RaidBulkAssignGroupMemberSelect(Select):
    def __init__(self, bot, members: list[discord.Member], member_list_order: str = "name"):
        self.bot = bot
        self._allowed_member_ids = {m.id for m in members}

        members_sorted = list(members)
        if str(member_list_order).strip().casefold() == "random":
            random.shuffle(members_sorted)
        else:
            members_sorted.sort(key=_member_sort_key)

        options = [
            discord.SelectOption(label=_safe_member_display_name(m)[:100], value=str(m.id))
            for m in members_sorted
        ][:25]

        super().__init__(
            placeholder="Select members...",
            min_values=1,
            max_values=min(len(options), 25),
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if view is None or not isinstance(view, RaidBulkAssignGroupView):
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("Bulk Set Group", "Please try again."),
                    view=None,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        selected_ids = []
        for val in self.values:
            try:
                member_id = int(val)
                if member_id in self._allowed_member_ids:
                    selected_ids.append(member_id)
            except (ValueError, TypeError):
                continue

        view.selected_member_ids = selected_ids
        count = len(selected_ids)

        try:
            await interaction.response.edit_message(
                content=f"Selected **{count}** member(s). Now pick a group.",
                view=view,
            )
        except discord.HTTPException:
            return


class RaidBulkAssignGroupNumberSelect(Select):
    def __init__(self, bot, group_count: int):
        self.bot = bot
        self.group_count = int(group_count)

        options: list[discord.SelectOption] = [
            discord.SelectOption(label=f"Group {i}", value=str(i))
            for i in range(1, min(self.group_count, 25) + 1)
        ]
        options.append(discord.SelectOption(label="Not in raid", value="0"))
        options.append(discord.SelectOption(label="Ungrouped", value="ungrouped"))

        super().__init__(
            placeholder="Select a group...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if view is None or not isinstance(view, RaidBulkAssignGroupView):
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("Bulk Set Group", "Please try again."),
                    view=None,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        if not view.selected_member_ids:
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("Bulk Set Group", "Select at least one member first."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        raw = (self.values[0] or "").strip()
        if raw == "ungrouped":
            group_number = None
        else:
            try:
                group_number = int(raw)
            except Exception:
                group_number = None
        if group_number is not None and group_number != 0 and (group_number < 1 or group_number > view.group_count):
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("Bulk Set Group", "Invalid group selection."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        success_count = 0
        for member_id in view.selected_member_ids:
            try:
                await self.bot.db.set_raid_member_group(int(view.raid_id), int(member_id), group_number)
                success_count += 1
            except Exception:
                logging.exception(f"Failed to set group for member {member_id}")

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog and interaction.guild and isinstance(interaction.channel, discord.Thread):
            try:
                raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                raid_dict = raid
                if raid is not None and not isinstance(raid, dict):
                    raid_dict = dict(raid)
                embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                await raid_cog._ensure_group_panel_message(interaction.channel, raid_dict, embed)
            except Exception:
                logging.exception("Failed to refresh group signup message after bulk assigning member groups")

        try:
            if isinstance(interaction.channel, discord.Thread):
                if group_number is None:
                    await interaction.channel.send(f"**{success_count}** member(s) were removed from their groups.")
                elif int(group_number) == 0:
                    await interaction.channel.send(f"**{success_count}** member(s) were assigned to **Not in raid**.")
                else:
                    await interaction.channel.send(f"**{success_count}** member(s) were assigned to **Group {int(group_number)}**.")
        except Exception:
            logging.exception("Failed to send bulk group assignment message to raid thread")

        if group_number is None:
            content = f"Cleared group assignment for **{success_count}** member(s)."
        elif int(group_number) == 0:
            content = f"Assigned **{success_count}** member(s) to **Not in raid**."
        else:
            content = f"Assigned **{success_count}** member(s) to **Group {int(group_number)}**."

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog and interaction.guild:
            try:
                raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                raid_dict = raid
                if raid is not None and not isinstance(raid, dict):
                    raid_dict = dict(raid)
                group_count = 0
                if isinstance(raid_dict, dict):
                    group_count = int(raid_dict.get("group_count") or 0)
                signup_embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                signup_view = RaidGroupSignupModalView(
                    self.bot,
                    group_count=group_count,
                    can_manage=bool(getattr(view, "group_signup_can_manage", False)),
                    return_to_popup=bool(getattr(view, "group_signup_return_to_popup", False)),
                    popup_can_manage=bool(getattr(view, "group_signup_popup_can_manage", False)),
                    popup_can_rename_thread=bool(getattr(view, "group_signup_popup_can_rename_thread", False)),
                )
                await interaction.response.edit_message(
                    content=content,
                    embed=signup_embed,
                    view=signup_view,
                )
                return
            except Exception:
                pass

        try:
            await interaction.response.edit_message(content=content, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return


class RaidBulkAssignGroupView(discord.ui.View):
    def __init__(
        self,
        bot,
        raid_id: int,
        members: list[discord.Member],
        group_count: int,
        member_list_order: str = "name",
        *,
        return_to_group_signup: bool = False,
        group_signup_can_manage: bool = False,
        group_signup_return_to_popup: bool = False,
        group_signup_popup_can_manage: bool = False,
        group_signup_popup_can_rename_thread: bool = False,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.raid_id = int(raid_id)
        self.members = list(members)
        self.group_count = int(group_count)
        self.member_list_order = str(member_list_order)
        self.selected_member_ids: list[int] = []
        self.return_to_group_signup = bool(return_to_group_signup)
        self.group_signup_can_manage = bool(group_signup_can_manage)
        self.group_signup_return_to_popup = bool(group_signup_return_to_popup)
        self.group_signup_popup_can_manage = bool(group_signup_popup_can_manage)
        self.group_signup_popup_can_rename_thread = bool(group_signup_popup_can_rename_thread)

        self.add_item(
            RaidBulkAssignGroupMemberSelect(
                bot,
                self.members,
                member_list_order=self.member_list_order,
            )
        )
        self.add_item(RaidBulkAssignGroupNumberSelect(bot, group_count))

        is_random = _is_random_member_order(self.member_list_order)
        toggle_btn = discord.ui.Button(
            label=("Sort A-Z" if is_random else "Shuffle"),
            style=discord.ButtonStyle.secondary,
            row=2,
        )

        async def _toggle_cb(interaction: discord.Interaction):
            new_order = "name" if is_random else "random"
            new_view = RaidBulkAssignGroupView(
                self.bot,
                self.raid_id,
                self.members,
                self.group_count,
                member_list_order=new_order,
                return_to_group_signup=self.return_to_group_signup,
                group_signup_can_manage=self.group_signup_can_manage,
                group_signup_return_to_popup=self.group_signup_return_to_popup,
                group_signup_popup_can_manage=self.group_signup_popup_can_manage,
                group_signup_popup_can_rename_thread=self.group_signup_popup_can_rename_thread,
            )
            new_view.selected_member_ids = self.selected_member_ids
            try:
                await interaction.response.edit_message(view=new_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        toggle_btn.callback = _toggle_cb
        self.add_item(toggle_btn)

        if self.return_to_group_signup:
            back_btn = discord.ui.Button(
                label="Back",
                style=discord.ButtonStyle.secondary,
                custom_id="raid_bulk_assign_back",
                row=3,
            )

            async def _back_cb(interaction: discord.Interaction):
                raid_cog = self.bot.get_cog("RaidCog")
                if not raid_cog or interaction.guild is None:
                    return

                raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                raid_dict = raid
                if raid is not None and not isinstance(raid, dict):
                    raid_dict = dict(raid)

                group_count = 0
                if isinstance(raid_dict, dict):
                    group_count = int(raid_dict.get("group_count") or 0)

                embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                view = RaidGroupSignupModalView(
                    self.bot,
                    group_count=group_count,
                    can_manage=self.group_signup_can_manage,
                    return_to_popup=self.group_signup_return_to_popup,
                    popup_can_manage=self.group_signup_popup_can_manage,
                    popup_can_rename_thread=self.group_signup_popup_can_rename_thread,
                )
                await interaction.response.edit_message(content=None, embed=embed, view=view)

            back_btn.callback = _back_cb
            self.add_item(back_btn)


class RaidVoiceChannelSelect(Select):
    def __init__(self, bot, voice_channels: list[discord.VoiceChannel]):
        self.bot = bot
        self._vc_ids = {vc.id for vc in voice_channels}

        options = [
            discord.SelectOption(label=vc.name[:100], value=str(vc.id))
            for vc in voice_channels
        ][:25]

        super().__init__(
            placeholder="Select a voice channel...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if view is None or not isinstance(view, RaidVoiceChannelGroupView):
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("From Voice Channel", "Please try again."),
                    view=None,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        try:
            vc_id = int(self.values[0])
        except (ValueError, TypeError):
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("From Voice Channel", "Invalid selection."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        if vc_id not in self._vc_ids:
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("From Voice Channel", "Invalid voice channel."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        view.selected_vc_id = vc_id
        vc = interaction.guild.get_channel(vc_id) if interaction.guild else None
        vc_name = vc.name if vc else f"Channel {vc_id}"
        member_count = len([m for m in getattr(vc, "members", []) if not getattr(m, "bot", False)]) if vc else 0

        try:
            await interaction.response.edit_message(
                content=f"Selected **{vc_name}** ({member_count} members). Now pick a group.",
                view=view,
            )
        except discord.HTTPException:
            return


class RaidVoiceChannelGroupNumberSelect(Select):
    def __init__(self, bot, group_count: int):
        self.bot = bot
        self.group_count = int(group_count)

        options: list[discord.SelectOption] = [
            discord.SelectOption(label=f"Group {i}", value=str(i))
            for i in range(1, min(self.group_count, 25) + 1)
        ]
        options.append(discord.SelectOption(label="Not in raid", value="0"))

        super().__init__(
            placeholder="Select a group...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if view is None or not isinstance(view, RaidVoiceChannelGroupView):
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("From Voice Channel", "Please try again."),
                    view=None,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        if view.selected_vc_id is None:
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("From Voice Channel", "Select a voice channel first."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        raw = (self.values[0] or "").strip()
        try:
            group_number = int(raw)
        except Exception:
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("From Voice Channel", "Invalid group selection."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        if group_number < 0 or group_number > view.group_count:
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("From Voice Channel", "Invalid group selection."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        vc = interaction.guild.get_channel(view.selected_vc_id) if interaction.guild else None
        if not vc or not isinstance(vc, discord.VoiceChannel):
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("From Voice Channel", "Voice channel not found."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        vc_members = [m for m in getattr(vc, "members", []) if not getattr(m, "bot", False)]
        if not vc_members:
            try:
                await interaction.response.edit_message(
                    embed=create_info_embed("From Voice Channel", "No members in that voice channel."),
                    view=view,
                )
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        raid_member_ids = set()
        try:
            member_rows = await self.bot.db.get_raid_members(view.raid_id)
            for row in member_rows:
                raid_member_ids.add(int(row["user_id"]))
        except Exception:
            pass

        success_count = 0
        skipped_count = 0
        for member in vc_members:
            if int(member.id) not in raid_member_ids:
                skipped_count += 1
                continue
            try:
                await self.bot.db.set_raid_member_group(int(view.raid_id), int(member.id), group_number)
                success_count += 1
            except Exception:
                logging.exception(f"Failed to set group for member {member.id} from voice channel")

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog and interaction.guild and isinstance(interaction.channel, discord.Thread):
            try:
                raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                raid_dict = raid
                if raid is not None and not isinstance(raid, dict):
                    raid_dict = dict(raid)
                embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                await raid_cog._ensure_group_panel_message(interaction.channel, raid_dict, embed)
            except Exception:
                logging.exception("Failed to refresh group signup message after voice channel group assignment")

        try:
            if isinstance(interaction.channel, discord.Thread):
                if int(group_number) == 0:
                    msg = f"**{success_count}** member(s) from **{vc.name}** were assigned to **Not in raid**."
                else:
                    msg = f"**{success_count}** member(s) from **{vc.name}** were assigned to **Group {int(group_number)}**."
                if skipped_count > 0:
                    msg += f" ({skipped_count} skipped - not in raid)"
                await interaction.channel.send(msg)
        except Exception:
            logging.exception("Failed to send voice channel group assignment message to raid thread")

        if int(group_number) == 0:
            content = f"Assigned **{success_count}** member(s) from **{vc.name}** to **Not in raid**."
        else:
            content = f"Assigned **{success_count}** member(s) from **{vc.name}** to **Group {int(group_number)}**."
        if skipped_count > 0:
            content += f" ({skipped_count} skipped - not in raid)"

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog and interaction.guild:
            try:
                raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                raid_dict = raid
                if raid is not None and not isinstance(raid, dict):
                    raid_dict = dict(raid)
                group_count = 0
                if isinstance(raid_dict, dict):
                    group_count = int(raid_dict.get("group_count") or 0)
                signup_embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                signup_view = RaidGroupSignupModalView(
                    self.bot,
                    group_count=group_count,
                    can_manage=bool(getattr(view, "group_signup_can_manage", False)),
                    return_to_popup=bool(getattr(view, "group_signup_return_to_popup", False)),
                    popup_can_manage=bool(getattr(view, "group_signup_popup_can_manage", False)),
                    popup_can_rename_thread=bool(getattr(view, "group_signup_popup_can_rename_thread", False)),
                )
                await interaction.response.edit_message(
                    content=content,
                    embed=signup_embed,
                    view=signup_view,
                )
                return
            except Exception:
                pass

        try:
            await interaction.response.edit_message(content=content, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return


class RaidVoiceChannelGroupView(discord.ui.View):
    def __init__(
        self,
        bot,
        raid_id: int,
        voice_channels: list[discord.VoiceChannel],
        group_count: int,
        *,
        return_to_group_signup: bool = False,
        group_signup_can_manage: bool = False,
        group_signup_return_to_popup: bool = False,
        group_signup_popup_can_manage: bool = False,
        group_signup_popup_can_rename_thread: bool = False,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.raid_id = int(raid_id)
        self.voice_channels = list(voice_channels)
        self.group_count = int(group_count)
        self.selected_vc_id: int | None = None
        self.return_to_group_signup = bool(return_to_group_signup)
        self.group_signup_can_manage = bool(group_signup_can_manage)
        self.group_signup_return_to_popup = bool(group_signup_return_to_popup)
        self.group_signup_popup_can_manage = bool(group_signup_popup_can_manage)
        self.group_signup_popup_can_rename_thread = bool(group_signup_popup_can_rename_thread)

        self.add_item(RaidVoiceChannelSelect(bot, self.voice_channels))
        self.add_item(RaidVoiceChannelGroupNumberSelect(bot, group_count))

        if self.return_to_group_signup:
            back_btn = discord.ui.Button(
                label="Back",
                style=discord.ButtonStyle.secondary,
                custom_id="raid_vc_group_back",
                row=2,
            )

            async def _back_cb(interaction: discord.Interaction):
                raid_cog = self.bot.get_cog("RaidCog")
                if not raid_cog or interaction.guild is None:
                    return

                raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
                raid_dict = raid
                if raid is not None and not isinstance(raid, dict):
                    raid_dict = dict(raid)

                group_count = 0
                if isinstance(raid_dict, dict):
                    group_count = int(raid_dict.get("group_count") or 0)

                embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                view = RaidGroupSignupModalView(
                    self.bot,
                    group_count=group_count,
                    can_manage=self.group_signup_can_manage,
                    return_to_popup=self.group_signup_return_to_popup,
                    popup_can_manage=self.group_signup_popup_can_manage,
                    popup_can_rename_thread=self.group_signup_popup_can_rename_thread,
                )
                await interaction.response.edit_message(content=None, embed=embed, view=view)

            back_btn.callback = _back_cb
            self.add_item(back_btn)


class DKPAdjustmentView(discord.ui.View):
    def __init__(
        self,
        bot,
        action: str,
        members: list[discord.Member],
        group_count: int | None = None,
        member_list_order: str = "name",
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.action = action
        self.members = list(members)
        self.group_count = group_count
        self.member_list_order = str(member_list_order)

        self.add_item(
            MemberSelect(
                bot,
                action,
                self.members,
                member_list_order=self.member_list_order,
                max_values=min(25, len(self.members)),
            )
        )

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

        is_random = _is_random_member_order(self.member_list_order)
        toggle_btn = discord.ui.Button(
            label=("Sort A-Z" if is_random else "Shuffle"),
            style=discord.ButtonStyle.secondary,
            row=2,
        )

        async def _toggle_cb(interaction: discord.Interaction):
            new_order = "name" if is_random else "random"
            new_view = DKPAdjustmentView(
                self.bot,
                self.action,
                self.members,
                group_count=self.group_count,
                member_list_order=new_order,
            )
            try:
                await interaction.response.edit_message(view=new_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        toggle_btn.callback = _toggle_cb
        self.add_item(toggle_btn)

    @discord.ui.button(label="All/Some Raid members", style=discord.ButtonStyle.primary, row=1)
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
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass

        if not isinstance(interaction.user, discord.Member):
            try:
                if not interaction.response.is_done():
                    return await interaction.response.send_message(
                        "This panel can only be used in a server.",
                        ephemeral=True,
                    )
                return await interaction.followup.send(
                    "This panel can only be used in a server.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                return

        admin_ok = await is_admin(interaction)
        officer_ok = await is_officer(interaction)

        embed = create_info_embed(
            f"DKP Panel for {interaction.user.display_name}",
            "Use the buttons below to access DKP bot features. This panel is only visible to you.",
        )
        view = DkpPanelView(self.bot, admin_ok=admin_ok, officer_ok=officer_ok)
        try:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return


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

    def _main_embed(self, interaction: discord.Interaction) -> discord.Embed:
        user = getattr(interaction, "user", None)
        display_name = getattr(user, "display_name", None) or getattr(user, "name", None) or "User"
        return create_info_embed(
            f"DKP Panel for {display_name}",
            "Use the buttons below to access DKP bot features. This panel is only visible to you.",
        )

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
        if interaction.guild is None:
            return await interaction.response.send_message(
                "This command cannot be used in DMs.",
                ephemeral=True,
            )

        dkp = await self.bot.db.get_user_dkp(interaction.user.id, interaction.guild.id)
        embed = create_info_embed(
            "💰 Your DKP Balance",
            f"You currently have **{dkp}** DKP.",
        )
        view = DkpPanelDetailView(self.bot, admin_ok=self.admin_ok, officer_ok=self.officer_ok)
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                msg = getattr(interaction, "message", None)
                if msg is not None:
                    await msg.edit(embed=embed, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return

    @discord.ui.button(label="Auction Help ❓", style=discord.ButtonStyle.primary, custom_id="dkp_panel_auction_help")
    async def auction_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        help_text = (
            "1. **Starting:** The Raid Leader starts an auction for an item.\n"
            "2. **Bidding:** You will receive a private message (or a hidden message in the raid thread) to bid.\n"
            "3. **Placing Bids:** Click 'Bid', enter your amount, and submit. You must have enough DKP.\n"
            "4. **Outbidding:** If someone bids higher, you'll be notified (if your DMs are open).\n"
            "5. **Winning:** The Raid Leader ends the auction. The highest bidder wins and the DKP is automatically deducted."
        )
        embed = create_info_embed("❓ Auction Help", help_text)
        view = DkpPanelDetailView(self.bot, admin_ok=self.admin_ok, officer_ok=self.officer_ok)
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                msg = getattr(interaction, "message", None)
                if msg is not None:
                    await msg.edit(embed=embed, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return

    @discord.ui.button(label="Bot Status 📈", style=discord.ButtonStyle.secondary, custom_id="dkp_panel_bot_status")
    async def bot_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        admin_cog = self.bot.get_cog("AdminCog")
        if admin_cog and interaction.guild is not None:
            embeds: list[discord.Embed] = [await admin_cog._create_status_embed(interaction.guild.id)]
            if self.admin_ok:
                embeds.append(await admin_cog._create_status_env_embed())

            view = DkpPanelDetailView(self.bot, admin_ok=self.admin_ok, officer_ok=self.officer_ok)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embeds=embeds, view=view)
                else:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embeds=embeds, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
        else:
            embed = create_info_embed("Bot Status", "Admin module is currently offline.")
            view = DkpPanelDetailView(self.bot, admin_ok=self.admin_ok, officer_ok=self.officer_ok)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

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


class DkpPanelDetailView(discord.ui.View):
    def __init__(self, bot, *, admin_ok: bool, officer_ok: bool):
        super().__init__(timeout=180)
        self.bot = bot
        self.admin_ok = bool(admin_ok)
        self.officer_ok = bool(officer_ok)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_allowed_guild(interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, custom_id="dkp_panel_detail_back")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = DkpPanelView(self.bot, admin_ok=self.admin_ok, officer_ok=self.officer_ok)
        embed = view._main_embed(interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="dkp_panel_detail_close")
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


class RaiderRoleSelect(discord.ui.RoleSelect):
    def __init__(self, bot: discord.Client):
        self.bot = bot

        super().__init__(
            placeholder="Type to search for a role to use as Raiders...",
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

        await admin_cog.set_role(interaction, "Raider", role)

        await send_admin_confirmation(
            interaction,
            panel_text=f"Raider role set to {role.mention}.",
            ephemeral_text=f"Raider role has been updated to {role.mention}.",
        )


class RaiderRoleAssignView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot
        self.add_item(RaiderRoleSelect(bot))


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

    @discord.ui.button(label="Assign Raider Role Name", style=discord.ButtonStyle.primary, row=1)
    async def assign_raider_role_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RaiderRoleAssignView(self.bot)
        await interaction.response.edit_message(
            content="Type to search for a role to use as the Raider role:",
            view=view,
        )


    @discord.ui.button(label="Default Timed DKP", style=discord.ButtonStyle.primary, row=2)
    async def set_default_timed_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        panel_message = getattr(interaction, "message", None)
        await interaction.response.send_modal(DefaultDKPAwardModal(self.bot, panel_message=panel_message))


class RaidPopupView(discord.ui.View):
    def __init__(
        self,
        bot,
        *,
        mode: str = "main",
        can_manage: bool = False,
        can_rename_thread: bool = False,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.mode = mode
        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)

        hide_ids: set[str] = set()

        if self.mode != "main":
            hide_ids |= {
                "raid_popup_join_raid",
                "raid_popup_leave_raid",
                "raid_popup_my_dkp",
                "raid_popup_voice_roster",
                "raid_popup_show_groups",
                "raid_popup_rename_thread",
                "raid_popup_open_manage",
                "raid_popup_open_help",
                "raid_popup_remove_raider",
            }

        if self.mode != "manage":
            hide_ids |= {
                "raid_popup_award_dkp",
                "raid_popup_deduct_dkp",
                "raid_popup_timed_dkp",
                "raid_popup_start_auction",
                "raid_popup_end_auction",
                "raid_popup_stop_timed_dkp",
                "raid_popup_raid_points",
                "raid_popup_reverse_dkp",
                "raid_popup_back_main",
            }

        if self.mode != "main":
            hide_ids |= {
                "raid_popup_update_team",
                "raid_popup_sync_voice",
            }

        if self.mode not in ("main", "manage"):
            hide_ids.add("raid_popup_close_raid")

        if self.mode != "help":
            hide_ids |= {"raid_popup_back_main_help"}

        if self.mode != "my_dkp":
            hide_ids |= {"raid_popup_back_main_dkp"}

        if self.mode == "main" and not self.can_manage:
            hide_ids.add("raid_popup_open_manage")
            hide_ids.add("raid_popup_remove_raider")
            hide_ids.add("raid_popup_close_raid")
            hide_ids.add("raid_popup_update_team")
            hide_ids.add("raid_popup_sync_voice")

        if self.mode == "manage" and not self.can_manage:
            hide_ids |= {
                "raid_popup_award_dkp",
                "raid_popup_deduct_dkp",
                "raid_popup_start_auction",
                "raid_popup_end_auction",
                "raid_popup_remove_raider",
                "raid_popup_close_raid",
            }

        if self.mode == "main" and not self.can_rename_thread:
            hide_ids.add("raid_popup_rename_thread")

        if hide_ids:
            to_remove: list[discord.ui.Item] = []
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.custom_id in hide_ids:
                    to_remove.append(child)
            for child in to_remove:
                self.remove_item(child)

        if self.mode == "main":
            main_row_overrides: dict[str, int] = {
                "raid_popup_update_team": 2,
                "raid_popup_sync_voice": 2,
                "raid_popup_remove_raider": 3,
                "raid_popup_close_raid": 3,
                "raid_popup_close": 4,
            }

            # Must remove and re-add buttons for row changes to take effect
            buttons_to_move: list[discord.ui.Button] = []
            for child in list(self.children):
                if isinstance(child, discord.ui.Button) and child.custom_id in main_row_overrides:
                    buttons_to_move.append(child)
                    self.remove_item(child)

            for btn in buttons_to_move:
                btn.row = main_row_overrides[btn.custom_id]
                self.add_item(btn)

        if self.mode == "manage":
            manage_row_overrides: dict[str, int] = {
                "raid_popup_award_dkp": 0,
                "raid_popup_deduct_dkp": 0,
                "raid_popup_timed_dkp": 0,
                "raid_popup_stop_timed_dkp": 0,
                "raid_popup_raid_points": 1,
                "raid_popup_reverse_dkp": 2,
                "raid_popup_start_auction": 2,
                "raid_popup_end_auction": 2,
                "raid_popup_close_raid": 2,
                "raid_popup_back_main": 3,
                "raid_popup_close": 3,
            }

            # Must remove and re-add buttons for row changes to take effect
            buttons_to_move: list[discord.ui.Button] = []
            for child in list(self.children):
                if isinstance(child, discord.ui.Button) and child.custom_id in manage_row_overrides:
                    buttons_to_move.append(child)
                    self.remove_item(child)

            for btn in buttons_to_move:
                btn.row = manage_row_overrides[btn.custom_id]
                self.add_item(btn)

    async def _defer(self, interaction: discord.Interaction, *, ephemeral: bool):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=ephemeral)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass

    async def _ensure_raid(self, interaction: discord.Interaction):
        if not await ensure_allowed_guild(interaction):
            return None
        if interaction.guild is None:
            return None
        if interaction.channel is None:
            return None
        return await self.bot.db.get_raid_by_thread(interaction.channel.id)

    async def _resolve_permissions(self, interaction: discord.Interaction):
        raid = await self._ensure_raid(interaction)
        if not raid:
            return None, False, False

        admin_ok = await is_admin(interaction)
        is_leader = int(getattr(interaction.user, "id", 0)) == int(raid["leader_id"])
        can_manage = bool(is_leader or admin_ok)

        officer_ok = await is_officer(interaction)
        can_rename_thread = bool(can_manage or officer_ok)

        return raid, can_manage, can_rename_thread

    def _main_embed(self, interaction: discord.Interaction, *, can_manage: bool) -> discord.Embed:
        user = interaction.user
        display_name = getattr(user, "display_name", None) or getattr(user, "name", None) or "User"
        title = f"Raid Panel for {display_name}"
        description = (
            "Use the buttons below to manage your raid. This panel is only visible to you."
            if can_manage
            else "Use the buttons below to view your DKP and other raid info. This panel is only visible to you."
        )
        return create_info_embed(title, description)

    def _manage_embed(self, interaction: discord.Interaction) -> discord.Embed:
        user = interaction.user
        display_name = getattr(user, "display_name", None) or getattr(user, "name", None) or "User"
        return create_info_embed(
            f"DKP for {display_name}",
            "Use the buttons below to manage DKP, auctions, and roster actions.",
        )

    def _help_embed(self) -> discord.Embed:
        description = "\n".join(
            [
                "This panel is used to manage the current raid. Some buttons may be hidden unless you are the raid leader/admin.",
                "",
                "**Join Raid**: Adds you to the raid. If you are not the leader/admin, this sends a join request for approval.",
                "**Leave Raid**: Removes you from the raid and prevents automatic re-adding during sync.",
                "**My DKP 💰**: Shows your current DKP.",
                "",
                "**DKP** (leader/admin): Opens advanced controls for DKP, auctions, and roster actions.",
                "**Award DKP / Deduct DKP** (leader/admin): Pick a raid member, then enter the DKP amount + reason.",
                "**Timed DKP / Stop Timed DKP** (leader/admin): View/configure Timed DKP for this raid, or stop it if it's running.",
                "**Raid Points** (leader/admin): View raid points for this raid (scoped/sorted).",
                "**Reverse Raid DKP** (leader/admin): Reverse DKP changes for this raid.",
                "**Start Auction 💎** (leader/admin): Opens the auction start form. Requires at least one raid member (use **Update Team** or have people **Join Raid** first).",
                "**End Auction** (leader/admin): Ends the current auction for this raid.",
                "**Close Raid** (leader/admin): Closes out the raid when finished.",
                "",
                "**🔄 Update Team** (leader/admin): Pulls members from the raid voice channel into the raid member list. This is usually the first step before DKP changes/auctions.",
                "**🔁 Sync Voice** (leader/admin): Syncs the raid roster with the configured voice channels. Use if people moved channels after the raid started.",
                "**🎙️ Voice Roster**: Shows who is currently in the raid voice channels.",
                "**Remove Raider** (leader/admin): Removes a member from the raid roster.",
                "**Groups**: Shows the current raid groups (if your guild uses grouping features).",
                "**Set group** (leader/admin): Assign a raid member to a group (or ungroup them).",
                "",
                "**Rename Thread** (leader/officer/admin): Renames the raid log thread.",
            ]
        )
        embed = discord.Embed(
            title="Raid Panel Help",
            description=description,
            color=discord.Color.blurple(),
        )
        return embed

    async def _edit_to(self, interaction: discord.Interaction, *, mode: str, embed: discord.Embed):
        view = RaidPopupView(
            self.bot,
            mode=mode,
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                msg = getattr(interaction, "message", None)
                if msg is not None:
                    await msg.edit(embed=embed, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return

    async def _popup_notice(
        self,
        interaction: discord.Interaction,
        message: str,
        *,
        mode: str | None = None,
        title: str | None = None,
    ):
        embed = create_info_embed(title or "Raid Panel", message)
        await self._edit_to(interaction, mode=(mode or self.mode), embed=embed)
        return

    @discord.ui.button(label="Join Raid", style=discord.ButtonStyle.success, custom_id="raid_popup_join_raid", row=0)
    async def join_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        delegate = RaidControlView(self.bot, show_leader_buttons=self.can_manage, show_rename_thread_button=self.can_rename_thread)
        await delegate.handle_join_raid(
            interaction,
            source="raid_popup",
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )

    @discord.ui.button(label="Leave Raid", style=discord.ButtonStyle.secondary, custom_id="raid_popup_leave_raid", row=0)
    async def leave_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        delegate = RaidControlView(self.bot, show_leader_buttons=self.can_manage, show_rename_thread_button=self.can_rename_thread)
        await delegate.handle_leave_raid(
            interaction,
            source="raid_popup",
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )

    @discord.ui.button(label="My DKP 💰", style=discord.ButtonStyle.secondary, custom_id="raid_popup_my_dkp", row=0)
    async def my_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, _can_manage, _can_rename = await self._resolve_permissions(interaction)
        if raid is None or interaction.guild is None:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")

        dkp = await self.bot.db.get_user_dkp(interaction.user.id, interaction.guild.id)
        embed = create_info_embed(
            "💰 Your DKP Balance",
            f"You currently have **{dkp}** DKP.",
        )
        await self._edit_to(interaction, mode="my_dkp", embed=embed)

    @discord.ui.button(label="🎙️ Voice Roster", style=discord.ButtonStyle.secondary, custom_id="raid_popup_voice_roster", row=1)
    async def voice_roster(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid = await self._ensure_raid(interaction)
        if not raid or interaction.guild is None:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")

        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog or not hasattr(raid_cog, "_get_linked_voice_channels"):
            embed = create_info_embed("Voice Channel Roster", "Raid module is currently offline.")
            view = RaidPopupInfoView(self.bot, can_manage=self.can_manage, can_rename_thread=self.can_rename_thread)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        linked_vcs = await raid_cog._get_linked_voice_channels(interaction.guild, raid)
        if not linked_vcs:
            embed = create_info_embed(
                "Voice Channel Roster",
                "This raid is not currently associated with any voice channels.",
            )
            view = RaidPopupInfoView(self.bot, can_manage=self.can_manage, can_rename_thread=self.can_rename_thread)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        per_vc: list[tuple[discord.VoiceChannel, list[discord.Member]]] = []
        all_members_by_id: dict[int, discord.Member] = {}
        for vc in linked_vcs:
            members = [m for m in list(getattr(vc, "members", []) or []) if not getattr(m, "bot", False)]
            per_vc.append((vc, members))
            for m in members:
                all_members_by_id[int(m.id)] = m

        vc_mentions = ", ".join([v.mention for v in linked_vcs])
        if not all_members_by_id:
            embed = create_info_embed(
                "Voice Channel Roster",
                f"No players are currently in linked raid voice channels: {vc_mentions}.",
            )
            view = RaidPopupInfoView(self.bot, can_manage=self.can_manage, can_rename_thread=self.can_rename_thread)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        lines: list[str] = [
            f"Voice channels: {vc_mentions}",
            f"Total players in voice (**{len(all_members_by_id)}**):",
        ]

        for vc, members in per_vc:
            if not members:
                continue
            mentions = ", ".join([m.mention for m in members])
            lines.append(f"**{vc.mention}** (**{len(members)}**): {mentions}")

        description = "\n".join(lines)
        if len(description) > 4096:
            description = description[:4090] + "..."

        embed = create_info_embed("Voice Channel Roster", description)
        view = RaidPopupInfoView(self.bot, can_manage=self.can_manage, can_rename_thread=self.can_rename_thread)
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                msg = getattr(interaction, "message", None)
                if msg is not None:
                    await msg.edit(embed=embed, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return

    @discord.ui.button(label="Groups", style=discord.ButtonStyle.secondary, custom_id="raid_popup_show_groups", row=1)
    async def show_groups(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid = await self._ensure_raid(interaction)
        if not raid or interaction.guild is None:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")

        raid_dict = raid
        try:
            if raid is not None and not isinstance(raid, dict):
                raid_dict = dict(raid)
        except Exception:
            raid_dict = raid

        group_count = 0
        try:
            raid_id = None
            if isinstance(raid_dict, dict):
                raid_id = raid_dict.get("id")
            if raid_id is None and raid is not None:
                try:
                    raid_id = raid["id"]
                except Exception:
                    raid_id = None
            raid_id_int = int(raid_id) if raid_id is not None else None
        except Exception:
            raid_id_int = None

        if raid_id_int is not None:
            try:
                db_count = await self.bot.db.get_raid_group_count(raid_id_int)
                group_count = int(db_count or 0)
            except Exception:
                group_count = 0

        if group_count <= 0:
            try:
                if isinstance(raid_dict, dict):
                    group_count = int(raid_dict.get("group_count") or 0)
                else:
                    group_count = int(raid["group_count"])
            except Exception:
                group_count = 0

        if isinstance(raid_dict, dict):
            raid_dict["group_count"] = int(group_count or 0)

        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            return await self._popup_notice(interaction, "Raid module is currently offline.", mode="main")

        if group_count <= 0:
            if self.can_manage:
                modal = RaidGroupSetupModal(raid_cog=raid_cog)
                try:
                    return await interaction.response.send_modal(modal)
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                    return await self._popup_notice(interaction, "Please try again.", mode="main")
            return await self._popup_notice(interaction, "Raid groups have not been created yet.", mode="main")

        await self._defer(interaction, ephemeral=False)
        embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
        view = RaidGroupSignupModalView(
            self.bot,
            group_count=group_count,
            can_manage=self.can_manage,
            return_to_popup=True,
            popup_can_manage=self.can_manage,
            popup_can_rename_thread=self.can_rename_thread,
        )
        try:
            await interaction.edit_original_response(content=None, embed=embed, view=view)
            return
        except (discord.NotFound, discord.HTTPException, AttributeError):
            pass

        msg = getattr(interaction, "message", None)
        if msg is None:
            return
        try:
            await msg.edit(content=None, embed=embed, view=view)
        except (discord.NotFound, discord.HTTPException):
            return

    @discord.ui.button(label="Rename Thread", style=discord.ButtonStyle.secondary, custom_id="raid_popup_rename_thread", row=1)
    async def rename_thread(self, interaction: discord.Interaction, button: discord.ui.Button):
        delegate = RaidControlView(self.bot, show_leader_buttons=self.can_manage, show_rename_thread_button=self.can_rename_thread)
        await delegate.handle_rename_thread(
            interaction,
            source="raid_popup",
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )

    @discord.ui.button(label="DKP", style=discord.ButtonStyle.primary, custom_id="raid_popup_open_manage", row=1)
    async def open_manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if raid is None:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")

        if not can_manage:
            return await self._popup_notice(
                interaction,
                "You must be the raid leader or a bot admin to use these controls.",
                mode="main",
            )

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        await self._edit_to(interaction, mode="manage", embed=self._manage_embed(interaction))

    @discord.ui.button(label="❓ Help", style=discord.ButtonStyle.secondary, custom_id="raid_popup_open_help", row=0)
    async def open_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._edit_to(interaction, mode="help", embed=self._help_embed())

    @discord.ui.button(label="Award DKP", style=discord.ButtonStyle.success, custom_id="raid_popup_award_dkp", row=3)
    async def award_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)

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
            return await self._popup_notice(
                interaction,
                "No eligible raid members were found. If you are in a voice channel, click \"Update Team\" to add all members in your voice channel to the raid. Or each member can click the \"Join Raid\" button.",
                mode="manage",
                title="Award DKP",
            )

        members.sort(key=lambda m: (m.display_name or "").lower())
        view = RaidPopupDKPSelectView(
            self.bot,
            action="Award",
            members=members,
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )
        embed = create_info_embed("Award DKP", "Who do you want to award DKP?")
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Deduct DKP", style=discord.ButtonStyle.danger, custom_id="raid_popup_deduct_dkp", row=3)
    async def deduct_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)

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
            return await self._popup_notice(
                interaction,
                "No eligible raid members were found. If you are in a voice channel, click \"Update Team\" to add all members in your voice channel to the raid. Or each member can click the \"Join Raid\" button.",
                mode="manage",
                title="Deduct DKP",
            )

        members.sort(key=lambda m: (m.display_name or "").lower())
        view = RaidPopupDKPSelectView(
            self.bot,
            action="Deduct",
            members=members,
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )
        embed = create_info_embed("Deduct DKP", "Who do you want to deduct DKP from?")
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Raid Points", style=discord.ButtonStyle.secondary, custom_id="raid_popup_raid_points", row=2)
    async def raid_points(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, _can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        raid_cog = self.bot.get_cog("RaidCog") if self.bot else None
        if not raid_cog:
            return await self._popup_notice(interaction, "Raid module is currently offline.", mode="manage")
        embed = create_info_embed("Raid Points", "Select scope and sort, then click Submit.")
        view = RaidPointsOptionsView(
            self.bot,
            raid_cog=raid_cog,
            return_to_popup=True,
            popup_can_manage=self.can_manage,
            popup_can_rename_thread=self.can_rename_thread,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Reverse Raid DKP", style=discord.ButtonStyle.danger, custom_id="raid_popup_reverse_dkp", row=3)
    async def reverse_raid_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, _can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        raid_cog = self.bot.get_cog("RaidCog") if self.bot else None
        if not raid_cog:
            return await self._popup_notice(interaction, "Raid module is currently offline.", mode="manage")
        modal = RaidReverseDKPModal(raid_cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Timed DKP", style=discord.ButtonStyle.primary, custom_id="raid_popup_timed_dkp", row=3)
    async def timed_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)

        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            return await self._popup_notice(interaction, "Raid module is currently offline.", mode="manage")

        row = None
        try:
            row = await self.bot.db.get_raid_timed_award(int(raid["id"]))
        except Exception:
            row = None

        amount = None
        interval_minutes = None
        is_enabled = None
        try:
            if isinstance(row, dict):
                amount = row.get("amount")
                interval_minutes = row.get("interval_minutes")
                is_enabled = row.get("is_enabled")
            elif row is not None:
                amount = row["amount"]
                interval_minutes = row["interval_minutes"]
                is_enabled = row["is_enabled"]
        except Exception:
            amount = None
            interval_minutes = None
            is_enabled = None

        if row is None:
            description = "Timed DKP is not configured for this raid yet."
        else:
            try:
                enabled = bool(int(is_enabled)) if is_enabled is not None else False
            except Exception:
                enabled = bool(is_enabled)

            if enabled and amount is not None and interval_minutes is not None:
                description = f"Currently enabled: **+{int(amount)} DKP** every **{int(interval_minutes)} minutes**."
            elif amount is not None and interval_minutes is not None:
                description = f"Currently disabled. Last settings: **+{int(amount)} DKP** every **{int(interval_minutes)} minutes**."
            else:
                description = "Timed DKP is configured, but its current settings could not be loaded."

        embed = create_info_embed("Timed DKP", description)
        view = RaidPopupTimedDKPView(
            self.bot,
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            try:
                msg = getattr(interaction, "message", None)
                if msg is not None:
                    await msg.edit(embed=embed, view=view)
            except Exception:
                return

    @discord.ui.button(label="Stop Timed DKP", style=discord.ButtonStyle.danger, custom_id="raid_popup_stop_timed_dkp", row=3)
    async def stop_timed_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        raid_cog = self.bot.get_cog("RaidCog") if self.bot else None
        if not raid_cog:
            return await self._popup_notice(interaction, "Raid module is currently offline.", mode="manage")

        await self._defer(interaction, ephemeral=True)
        await raid_cog.disable_timed_award(interaction)

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        await self._popup_notice(interaction, "Timed DKP disabled.", mode="manage", title="Timed DKP")

    @discord.ui.button(label="Start Auction 💎", style=discord.ButtonStyle.primary, custom_id="raid_popup_start_auction", row=4)
    async def start_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        delegate = RaidControlView(self.bot, show_leader_buttons=True, show_rename_thread_button=self.can_rename_thread)
        await delegate.handle_start_auction(
            interaction,
            source="raid_popup",
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )

    @discord.ui.button(label="End Auction", style=discord.ButtonStyle.primary, custom_id="raid_popup_end_auction", row=0)
    async def end_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        await self._defer(interaction, ephemeral=True)
        delegate = RaidControlView(self.bot, show_leader_buttons=True, show_rename_thread_button=self.can_rename_thread)
        await delegate.handle_end_auction(
            interaction,
            source="raid_popup",
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )

    @discord.ui.button(label="🔄 Update Team", style=discord.ButtonStyle.secondary, custom_id="raid_popup_update_team", row=2)
    async def update_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        await self._defer(interaction, ephemeral=False)
        delegate = RaidControlView(self.bot, show_leader_buttons=True, show_rename_thread_button=self.can_rename_thread)
        await delegate.handle_update_team(
            interaction,
            source="raid_popup",
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )

    @discord.ui.button(label="🔁 Sync Voice", style=discord.ButtonStyle.secondary, custom_id="raid_popup_sync_voice", row=2)
    async def sync_voice(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        await self._defer(interaction, ephemeral=False)
        delegate = RaidControlView(self.bot, show_leader_buttons=True, show_rename_thread_button=self.can_rename_thread)
        await delegate.handle_sync_voice(
            interaction,
            source="raid_popup",
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )

    @discord.ui.button(label="Remove Raider", style=discord.ButtonStyle.danger, custom_id="raid_popup_remove_raider", row=2)
    async def remove_raider(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        delegate = RaidControlView(self.bot, show_leader_buttons=True, show_rename_thread_button=self.can_rename_thread)
        await delegate.handle_remove_raider(
            interaction,
            source="raid_popup",
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )

    @discord.ui.button(label="Close Raid", style=discord.ButtonStyle.danger, custom_id="raid_popup_close_raid", row=2)
    async def close_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if not raid:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")
        if not can_manage:
            return await self._popup_notice(interaction, "You don't have permission to do that.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        await self._defer(interaction, ephemeral=True)
        delegate = RaidControlView(self.bot, show_leader_buttons=True, show_rename_thread_button=self.can_rename_thread)
        await delegate.handle_close_raid(
            interaction,
            source="raid_popup",
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, custom_id="raid_popup_back_main", row=4)
    async def back_main(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if raid is None:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        await self._edit_to(interaction, mode="main", embed=self._main_embed(interaction, can_manage=bool(can_manage)))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, custom_id="raid_popup_back_main_help", row=4)
    async def back_main_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if raid is None:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        await self._edit_to(interaction, mode="main", embed=self._main_embed(interaction, can_manage=bool(can_manage)))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, custom_id="raid_popup_back_main_dkp", row=4)
    async def back_main_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid, can_manage, can_rename_thread = await self._resolve_permissions(interaction)
        if raid is None:
            return await self._popup_notice(interaction, "This is not an active raid thread.", mode="main")

        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        await self._edit_to(interaction, mode="main", embed=self._main_embed(interaction, can_manage=bool(can_manage)))

    @discord.ui.button(label="Close Panel", style=discord.ButtonStyle.secondary, custom_id="raid_popup_close", row=4)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)


class RaidPopupInfoView(discord.ui.View):
    def __init__(self, bot, *, can_manage: bool, can_rename_thread: bool):
        super().__init__(timeout=None)
        self.bot = bot
        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, custom_id="raid_popup_info_back")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RaidPopupView(
            self.bot,
            mode="main",
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )
        embed = view._main_embed(interaction, can_manage=self.can_manage)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Close Panel", style=discord.ButtonStyle.secondary, custom_id="raid_popup_info_close", row=2)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)


class RaidPopupDKPMemberSelect(Select):
    def __init__(self, bot, *, action: str, members: list[discord.Member]):
        self.bot = bot
        self.action = str(action)
        self._allowed_member_ids = {int(m.id) for m in members}

        members_sorted = list(members)
        members_sorted.sort(key=_member_sort_key)

        options = [
            discord.SelectOption(label=_safe_member_display_name(m)[:100], value=str(m.id))
            for m in members_sorted
        ][:25]

        max_select = max(1, min(len(options), 25))
        super().__init__(
            placeholder=f"Select member(s) to {self.action.lower()} DKP...",
            min_values=1,
            max_values=max_select,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_members: list[discord.Member] = []
        if interaction.guild:
            for raw_id in list(self.values or []):
                try:
                    selected_id = int(raw_id)
                except (ValueError, TypeError):
                    continue
                if selected_id not in self._allowed_member_ids:
                    continue
                member = interaction.guild.get_member(selected_id)
                if member is not None:
                    selected_members.append(member)

        if not selected_members:
            embed = create_info_embed("DKP Selection", "That member is not an eligible raid member.")
            view = getattr(self, "view", None)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        raid_cog = self.bot.get_cog("RaidCog")
        modal = DKPAdjustmentModal(
            action=self.action,
            raid_cog=raid_cog,
            members=selected_members,
            source="raid_popup",
            popup_message=getattr(interaction, "message", None),
        )
        await interaction.response.send_modal(modal)


class RaidPopupDKPSelectView(discord.ui.View):
    def __init__(
        self,
        bot,
        *,
        action: str,
        members: list[discord.Member],
        can_manage: bool,
        can_rename_thread: bool,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.action = action
        self._allowed_member_ids = {int(m.id) for m in members}
        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        self.add_item(RaidPopupDKPMemberSelect(bot, action=action, members=list(members)))

    @discord.ui.button(label="All/Some Raid members", style=discord.ButtonStyle.primary, custom_id="raid_popup_dkp_all", row=1)
    async def all_members(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog")
        modal = DKPAdjustmentModal(
            action=self.action,
            raid_cog=raid_cog,
            member=None,
            source="raid_popup",
            popup_message=getattr(interaction, "message", None),
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, custom_id="raid_popup_dkp_back", row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RaidPopupView(
            self.bot,
            mode=("manage" if self.can_manage else "main"),
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )
        embed = create_info_embed(
            "DKP" if self.can_manage else "Raid Panel",
            "Use the buttons below to manage DKP, auctions, and roster actions."
            if self.can_manage
            else "Use the buttons below to view your DKP and other raid info. This panel is only visible to you.",
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="raid_popup_dkp_close", row=2)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)


class RaidPopupTimedDKPView(discord.ui.View):
    def __init__(self, bot, *, can_manage: bool, can_rename_thread: bool):
        super().__init__(timeout=None)
        self.bot = bot
        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)

    @discord.ui.button(
        label="Configure Timed DKP",
        style=discord.ButtonStyle.primary,
        custom_id="raid_popup_timed_dkp_configure",
        row=0,
    )
    async def configure_timed_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog") if self.bot else None
        if not raid_cog:
            try:
                if not interaction.response.is_done():
                    return await interaction.response.send_message(
                        "Raid module is currently offline.",
                        ephemeral=True,
                    )
                return await interaction.followup.send(
                    "Raid module is currently offline.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                return

        modal = RaidTimedAwardModal(
            raid_cog=raid_cog,
            source="raid_popup",
            popup_message=getattr(interaction, "message", None),
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Stop Timed DKP",
        style=discord.ButtonStyle.danger,
        custom_id="raid_popup_timed_dkp_stop",
        row=0,
    )
    async def stop_timed_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog") if self.bot else None
        if not raid_cog:
            try:
                if not interaction.response.is_done():
                    return await interaction.response.send_message(
                        "Raid module is currently offline.",
                        ephemeral=True,
                    )
                return await interaction.followup.send(
                    "Raid module is currently offline.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                return

        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass

        await raid_cog.disable_timed_award(interaction)

        try:
            msg = getattr(interaction, "message", None)
            if msg is not None:
                embed = create_info_embed("Timed DKP", "Timed DKP disabled.")
                await msg.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, custom_id="raid_popup_timed_dkp_back", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RaidPopupView(
            self.bot,
            mode=("manage" if self.can_manage else "main"),
            can_manage=self.can_manage,
            can_rename_thread=self.can_rename_thread,
        )
        embed = create_info_embed(
            "DKP" if self.can_manage else "Raid Panel",
            "Use the buttons below to manage DKP, auctions, and roster actions."
            if self.can_manage
            else "Use the buttons below to view your DKP and other raid info. This panel is only visible to you.",
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="raid_popup_timed_dkp_close", row=1)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)


class RaidSyncVoiceChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(
            placeholder="Pick a voice channel to add + sync...",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.voice],
            custom_id="raid_sync_voice_channel_select",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if view is None or not isinstance(view, RaidSyncVoicePickerView):
            try:
                await interaction.response.send_message("Please try opening Sync Voice again.", ephemeral=True)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        selected = self.values[0] if self.values else None
        selected_voice_channel = selected if isinstance(selected, discord.VoiceChannel) else None
        if selected_voice_channel is None and interaction.guild is not None:
            selected_id = getattr(selected, "id", None)
            if selected_id is not None:
                try:
                    selected_voice_channel = interaction.guild.get_channel(int(selected_id))
                except (TypeError, ValueError):
                    selected_voice_channel = None

                if selected_voice_channel is None:
                    try:
                        selected_voice_channel = await interaction.guild.fetch_channel(int(selected_id))
                    except (
                        discord.NotFound,
                        discord.Forbidden,
                        discord.HTTPException,
                        TypeError,
                        ValueError,
                    ):
                        selected_voice_channel = None

        if not isinstance(selected_voice_channel, discord.VoiceChannel):
            try:
                await interaction.response.send_message("Please choose a valid voice channel.", ephemeral=True)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        await view.run_sync(interaction, channel=selected_voice_channel)


class RaidSyncVoicePickerView(discord.ui.View):
    def __init__(self, bot, *, source: str | None = None, can_manage: bool = False, can_rename_thread: bool = False):
        super().__init__(timeout=180)
        self.bot = bot
        self.source = source
        self.can_manage = bool(can_manage)
        self.can_rename_thread = bool(can_rename_thread)
        self.add_item(RaidSyncVoiceChannelSelect(bot))

    async def run_sync(self, interaction: discord.Interaction, *, channel: discord.VoiceChannel | None):
        raid_cog = self.bot.get_cog("RaidCog") if self.bot else None
        if not raid_cog:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)
                else:
                    await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        await raid_cog.sync_raid_with_voice_channels(
            interaction,
            remove_missing=False,
            confirm=False,
            channel=channel,
        )

    @discord.ui.button(label="sync current Voice channel", style=discord.ButtonStyle.primary, custom_id="raid_sync_voice_now", row=1)
    async def sync_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_sync(interaction, channel=None)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, custom_id="raid_sync_voice_back", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.source == "raid_popup":
            embed = create_info_embed("Sync Voice", "Select an option from your raid panel.")
            view = RaidPopupView(
                self.bot,
                mode=("manage" if self.can_manage else "main"),
                can_manage=self.can_manage,
                can_rename_thread=self.can_rename_thread,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        try:
            await interaction.response.edit_message(content="Sync Voice canceled.", embed=None, view=None)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return


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
                "raid_start_auction",
                "raid_end_auction",
                "raid_close_raid",
                "raid_points",
                "raid_reverse_dkp",
                "raid_stop_timed_dkp",
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
            "raid_start_auction",
            "raid_show_groups",
            "raid_rename_thread",
            "raid_points",
            "raid_reverse_dkp",
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

    async def handle_join_raid(
        self,
        interaction: discord.Interaction,
        *,
        source: str | None = None,
        can_manage: bool = False,
        can_rename_thread: bool = False,
    ):
        async def respond_popup(message: str):
            user = getattr(interaction, "user", None)
            display_name = getattr(user, "display_name", None) or getattr(user, "name", None) or "User"
            embed = create_info_embed(f"Raid Panel for {display_name}", message)
            view = RaidPopupView(
                self.bot,
                mode=("manage" if can_manage else "main"),
                can_manage=can_manage,
                can_rename_thread=can_rename_thread,
            )
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            if source == "raid_popup":
                return await respond_popup("This is not an active raid thread.")
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        if getattr(interaction.user, "bot", False):
            return await interaction.followup.send("Bots cannot join raids.", ephemeral=True)

        raid_id = int(raid["id"])
        user_id = int(interaction.user.id)

        required_role_id = None
        try:
            if interaction.guild is not None:
                config = await self.bot.db.get_guild_config(int(interaction.guild.id))
                if config and ("raider_role_id" in getattr(config, "keys", lambda: [])()):
                    required_role_id = config.get("raider_role_id") if isinstance(config, dict) else config["raider_role_id"]
        except Exception:
            required_role_id = None
        try:
            required_role_id = int(required_role_id) if required_role_id else None
        except Exception:
            required_role_id = None

        is_eligible_raider = True
        if required_role_id and interaction.guild is not None:
            try:
                required_role = interaction.guild.get_role(required_role_id)
            except Exception:
                required_role = None
            if required_role is not None:
                member_roles = list(getattr(interaction.user, "roles", []) or [])
                is_eligible_raider = required_role in member_roles

        if not is_eligible_raider:
            message = "You do not have the required Raider role to join this raid."
            if source == "raid_popup":
                return await respond_popup(message)
            return await interaction.followup.send(message, ephemeral=True)

        try:
            if await self.bot.db.is_raid_member(raid_id, user_id):
                if source == "raid_popup":
                    return await respond_popup("You are already part of this raid.")
                return await interaction.followup.send("You are already part of this raid.", ephemeral=True)
        except Exception:
            pass

        # Check if user was manually excluded (requires approval to rejoin)
        exclusion_reason = None
        try:
            exclusion_reason = await self.bot.db.get_raid_member_exclusion_reason(raid_id, user_id)
        except Exception:
            pass

        if exclusion_reason == "manual":
            # User was manually removed by leader/admin - require approval to rejoin
            try:
                existing = await self.bot.db.get_raid_join_request(raid_id, user_id)
            except Exception:
                existing = None
            if existing is not None:
                try:
                    if str(existing["status"]) == "pending":
                        if source == "raid_popup":
                            return await respond_popup("Your join request is already pending approval.")
                        return await interaction.followup.send(
                            "Your join request is already pending approval.",
                            ephemeral=True,
                        )
                except Exception:
                    pass

            try:
                await self.bot.db.upsert_raid_join_request(raid_id, user_id, source="button")
            except Exception:
                if source == "raid_popup":
                    return await respond_popup("Failed to submit join request. Please try again.")
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
                            await interaction.channel.send(
                                f"{leader_mention} approve join request from {interaction.user.mention}?",
                                view=RaidJoinApprovalView(self.bot, raid_id, user_id),
                            )
                    else:
                        await interaction.channel.send(
                            f"{leader_mention} approve join request from {interaction.user.mention}?",
                            view=RaidJoinApprovalView(self.bot, raid_id, user_id),
                        )
            except Exception:
                logging.exception("Failed to send join approval request")

            if source == "raid_popup":
                return await respond_popup("You were previously removed from this raid. Join request sent to the raid leader for approval.")
            return await interaction.followup.send(
                "You were previously removed from this raid. Join request sent to the raid leader for approval.",
                ephemeral=True,
            )

        # Auto-add: no exclusion, or exclusion was inactivity/voluntary (can rejoin freely)
        try:
            inserted = await self.bot.db.add_raid_member(raid_id, user_id)
        except Exception:
            inserted = False
        if not inserted:
            if source == "raid_popup":
                return await respond_popup("You are already part of this raid.")
            return await interaction.followup.send("You are already part of this raid.", ephemeral=True)
        try:
            await self.bot.db.remove_raid_member_exclusion(raid_id, user_id)
        except Exception:
            pass
        try:
            await self.bot.db.delete_raid_join_request(raid_id, user_id)
        except Exception:
            pass
        try:
            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(f"{interaction.user.mention} joined the raid.")
        except Exception:
            logging.exception("Failed to send join message to raid thread")
        if source == "raid_popup":
            return await respond_popup("You have been added to the raid.")
        return await interaction.followup.send("You have been added to the raid.", ephemeral=True)

    @discord.ui.button(label="Join Raid", style=discord.ButtonStyle.success, custom_id="raid_join_raid", row=0)
    async def join_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_join_raid(interaction)

    @discord.ui.button(label="My DKP 💰", style=discord.ButtonStyle.secondary, custom_id="raid_my_dkp", row=0)
    async def raid_my_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
                else:
                    await interaction.followup.send("This command cannot be used in DMs.", ephemeral=True)
            except discord.HTTPException:
                pass
            return

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)
                else:
                    await interaction.followup.send("This is not an active raid thread.", ephemeral=True)
            except discord.HTTPException:
                pass
            return

        admin_ok = await is_admin(interaction)
        is_leader = int(interaction.user.id) == int(raid["leader_id"])
        can_manage = bool(is_leader or admin_ok)
        officer_ok = await is_officer(interaction)
        can_rename_thread = bool(can_manage or officer_ok)

        dkp = await self.bot.db.get_user_dkp(interaction.user.id, interaction.guild.id)
        embed = create_info_embed(
            "💰 Your DKP Balance",
            f"You currently have **{dkp}** DKP.",
        )
        view = RaidPopupView(self.bot, mode="my_dkp", can_manage=can_manage, can_rename_thread=can_rename_thread)
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                msg = getattr(interaction, "message", None)
                if msg is not None:
                    await msg.edit(embed=embed, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return

    async def _show_dkp_adjustment_view(self, interaction: discord.Interaction, action: str):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            try:
                if not interaction.response.is_done():
                    return await interaction.response.send_message("This raid is not active.", ephemeral=True)
                return await interaction.followup.send("This raid is not active.", ephemeral=True)
            except discord.HTTPException:
                return

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
            try:
                message = "No eligible raid members were found. If you are in a voice channel, click \"Update Team\" to add all members in your voice channel to the raid. Or each member can click the \"Join Raid\" button."
                if not interaction.response.is_done():
                    return await interaction.response.send_message(message, ephemeral=True)
                return await interaction.followup.send(message, ephemeral=True)
            except discord.HTTPException:
                return

        member_list_order = "name"
        try:
            if interaction.guild:
                config = await self.bot.db.get_guild_config(int(interaction.guild.id))
                if config and ("raid_member_list_order" in getattr(config, "keys", lambda: [])()):
                    raw = config["raid_member_list_order"]
                    if raw:
                        member_list_order = str(raw)
        except Exception:
            pass

        view = DKPAdjustmentView(
            self.bot,
            action,
            members,
            group_count=group_count,
            member_list_order=member_list_order,
        )
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

    @discord.ui.button(label="Award DKP", style=discord.ButtonStyle.success, custom_id="raid_award_dkp", row=0)
    async def award_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_dkp_adjustment_view(interaction, "Award")

    @discord.ui.button(label="Deduct DKP", style=discord.ButtonStyle.danger, custom_id="raid_deduct_dkp", row=0)
    async def deduct_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_dkp_adjustment_view(interaction, "Deduct")

    @discord.ui.button(label="Raid Points", emoji="🏅", style=discord.ButtonStyle.secondary, custom_id="raid_points", row=3)
    async def raid_points(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog") if self.bot else None
        if not raid_cog:
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        embed = create_info_embed("Raid Points", "Select scope and sort, then click Submit.")
        view = RaidPointsOptionsView(self.bot, raid_cog=raid_cog, return_to_popup=False)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Reverse Raid DKP", style=discord.ButtonStyle.danger, custom_id="raid_reverse_dkp", row=1)
    async def reverse_raid_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog") if self.bot else None
        if not raid_cog:
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        modal = RaidReverseDKPModal(raid_cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Start Auction 💎", style=discord.ButtonStyle.primary, custom_id="raid_start_auction", row=1)
    async def start_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_start_auction(interaction)

    async def handle_start_auction(
        self,
        interaction: discord.Interaction,
        *,
        source: str | None = None,
        can_manage: bool = False,
        can_rename_thread: bool = False,
    ):
        async def respond_popup(message: str):
            embed = create_info_embed("Start Auction", message)
            view = RaidPopupView(
                self.bot,
                mode=("manage" if can_manage else "main"),
                can_manage=can_manage,
                can_rename_thread=can_rename_thread,
            )
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    await interaction.edit_original_response(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        # Before opening the auction modal, ensure this is an active raid
        # thread and that there is at least one raid participant (either in
        # the raid voice channel or recorded in raid_members).
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            if source == "raid_popup":
                return await respond_popup("This is not an active raid thread.")
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

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
            message = (
                "No eligible raid members were found. If you are in a voice channel, click \"Update Team\" to add all members in your voice channel to the raid. Or each member can click the \"Join Raid\" button. Cannot start auction."
            )
            if source == "raid_popup":
                return await respond_popup(message)
            return await interaction.response.send_message(message, ephemeral=True)

        # Also block if an auction is already active for this raid so the
        # leader sees the error immediately instead of only after submitting
        # the modal.
        active_auction = await self.bot.db.get_active_auction(raid["id"])
        if active_auction:
            if source == "raid_popup":
                return await respond_popup("An auction is already in progress for this raid.")
            return await interaction.response.send_message("An auction is already in progress for this raid.", ephemeral=True)

        auction_cog = self.bot.get_cog("AuctionCog")
        modal = AuctionStartModal(
            auction_cog=auction_cog,
            source=source,
            popup_can_manage=can_manage,
            popup_can_rename_thread=can_rename_thread,
            popup_message=getattr(interaction, "message", None),
        )
        try:
            await interaction.response.send_modal(modal)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
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

    async def handle_update_team(
        self,
        interaction: discord.Interaction,
        *,
        source: str | None = None,
        can_manage: bool = False,
        can_rename_thread: bool = False,
    ):
        async def respond_popup(message: str):
            embed = create_info_embed("Update Team", message)
            view = RaidPopupView(
                self.bot,
                mode=("manage" if can_manage else "main"),
                can_manage=can_manage,
                can_rename_thread=can_rename_thread,
            )
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    await interaction.edit_original_response(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            if source == "raid_popup":
                return await respond_popup("Raid module is currently offline.")
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)

        if source == "raid_popup":
            if interaction.guild is None:
                return await respond_popup("This command can only be used inside a server.")

            raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
            if not raid:
                return await respond_popup("This raid is not active.")

            admin_ok = await is_admin(interaction)
            if int(interaction.user.id) != int(raid["leader_id"]) and not admin_ok:
                return await respond_popup("You must be the raid leader or a bot admin to update the team.")

            leader_member = interaction.guild.get_member(int(raid["leader_id"]))
            if not leader_member:
                return await respond_popup("Raid leader not found in this server.")

            leader_voice = getattr(leader_member, "voice", None)
            vc = getattr(leader_voice, "channel", None)
            if not isinstance(vc, discord.VoiceChannel):
                return await respond_popup("You must be connected to a voice channel to use Update Team.")

        await raid_cog.update_team_from_voice_channel(interaction)

        try:
            raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        except Exception:
            raid = None
        if raid:
            try:
                await self.bot.db.execute(
                    "UPDATE raids SET auto_add_from_vc = 1 WHERE id = ?",
                    (int(raid["id"]),),
                )
            except Exception:
                pass

        if source == "raid_popup":
            return await respond_popup("Update Team complete.")

    @discord.ui.button(label="🔄 Update Team", style=discord.ButtonStyle.secondary, custom_id="raid_update_team", row=2)
    async def update_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_update_team(interaction)

    async def handle_sync_voice(
        self,
        interaction: discord.Interaction,
        *,
        source: str | None = None,
        can_manage: bool = False,
        can_rename_thread: bool = False,
    ):
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            if not interaction.response.is_done():
                return await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)

        if source == "raid_popup":
            if interaction.guild is None:
                embed = create_info_embed("Sync Voice", "This command can only be used inside a server.")
                view = RaidPopupView(
                    self.bot,
                    mode=("manage" if can_manage else "main"),
                    can_manage=can_manage,
                    can_rename_thread=can_rename_thread,
                )
                try:
                    if not interaction.response.is_done():
                        await interaction.response.edit_message(embed=embed, view=view)
                    else:
                        await interaction.edit_original_response(embed=embed, view=view)
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                    return
                return

            raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
            if not raid:
                embed = create_info_embed("Sync Voice", "This raid is not active.")
                view = RaidPopupView(
                    self.bot,
                    mode=("manage" if can_manage else "main"),
                    can_manage=can_manage,
                    can_rename_thread=can_rename_thread,
                )
                try:
                    if not interaction.response.is_done():
                        await interaction.response.edit_message(embed=embed, view=view)
                    else:
                        await interaction.edit_original_response(embed=embed, view=view)
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                    return
                return

            admin_ok = await is_admin(interaction)
            officer_ok = await is_officer(interaction)
            if int(interaction.user.id) != int(raid["leader_id"]) and not admin_ok and not officer_ok:
                embed = create_info_embed("Sync Voice", "You must be the raid leader, an officer, or a bot admin to sync raid members.")
                view = RaidPopupView(
                    self.bot,
                    mode=("manage" if can_manage else "main"),
                    can_manage=can_manage,
                    can_rename_thread=can_rename_thread,
                )
                try:
                    if not interaction.response.is_done():
                        await interaction.response.edit_message(embed=embed, view=view)
                    else:
                        await interaction.edit_original_response(embed=embed, view=view)
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                    return
                return

        picker_embed = create_info_embed(
            "Sync Voice",
            "Pick a voice channel below to link it and include it in this sync.\n\n"
            "Or click **sync current Voice channel** to sync without adding a new channel.",
        )
        picker_view = RaidSyncVoicePickerView(
            self.bot,
            source=source,
            can_manage=can_manage,
            can_rename_thread=can_rename_thread,
        )

        if source == "raid_popup":
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=picker_embed, view=picker_view)
                else:
                    await interaction.edit_original_response(embed=picker_embed, view=picker_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=picker_embed, view=picker_view, ephemeral=True)
            else:
                await interaction.followup.send(embed=picker_embed, view=picker_view, ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            return

    @discord.ui.button(label="🔁 Sync Voice", style=discord.ButtonStyle.secondary, custom_id="raid_sync_voice", row=2)
    async def sync_voice(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_sync_voice(interaction)

    @discord.ui.button(label="Stop Timed DKP", style=discord.ButtonStyle.danger, custom_id="raid_stop_timed_dkp", row=3)
    async def stop_timed_dkp(self, interaction: discord.Interaction, button: discord.ui.Button):
        raid_cog = self.bot.get_cog("RaidCog") if self.bot else None
        if not raid_cog:
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        await raid_cog.disable_timed_award(interaction)

    async def handle_voice_roster(self, interaction: discord.Interaction):
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        await raid_cog.show_voice_roster(interaction)

    @discord.ui.button(label="🎙️ Voice Roster", style=discord.ButtonStyle.secondary, custom_id="raid_voice_roster", row=2)
    async def voice_roster(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_voice_roster(interaction)

    async def handle_end_auction(
        self,
        interaction: discord.Interaction,
        *,
        source: str | None = None,
        can_manage: bool = False,
        can_rename_thread: bool = False,
    ):
        async def respond_popup(message: str):
            embed = create_info_embed("End Auction", message)
            view = RaidPopupView(
                self.bot,
                mode=("manage" if can_manage else "main"),
                can_manage=can_manage,
                can_rename_thread=can_rename_thread,
            )
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    await interaction.edit_original_response(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        auction_cog = self.bot.get_cog("AuctionCog")
        if not auction_cog:
            if source == "raid_popup":
                return await respond_popup("Auction module is currently offline.")
            return await interaction.followup.send("Auction module is currently offline.", ephemeral=True)

        await auction_cog.end_auction_from_button(
            interaction,
            source=source,
            popup_can_manage=can_manage,
            popup_can_rename_thread=can_rename_thread,
            popup_message=getattr(interaction, "message", None),
        )

    @discord.ui.button(label="End Auction", style=discord.ButtonStyle.primary, custom_id="raid_end_auction", row=1)
    async def end_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_end_auction(interaction)

    async def handle_close_raid(
        self,
        interaction: discord.Interaction,
        *,
        source: str | None = None,
        can_manage: bool = False,
        can_rename_thread: bool = False,
    ):
        async def respond_popup(message: str):
            embed = create_info_embed("Close Raid", message)
            view = RaidPopupView(
                self.bot,
                mode=("manage" if can_manage else "main"),
                can_manage=can_manage,
                can_rename_thread=can_rename_thread,
            )
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    await interaction.edit_original_response(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            if source == "raid_popup":
                return await respond_popup("Raid module is currently offline.")
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)

        await raid_cog.close_raid(
            interaction,
            source=source,
            popup_can_manage=can_manage,
            popup_can_rename_thread=can_rename_thread,
            popup_message=getattr(interaction, "message", None),
        )

    @discord.ui.button(label="Close Raid", style=discord.ButtonStyle.danger, custom_id="raid_close_raid", row=1)
    async def close_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_close_raid(interaction)

    async def handle_leave_raid(
        self,
        interaction: discord.Interaction,
        *,
        source: str | None = None,
        can_manage: bool = False,
        can_rename_thread: bool = False,
    ):
        async def respond_popup(message: str):
            user = getattr(interaction, "user", None)
            display_name = getattr(user, "display_name", None) or getattr(user, "name", None) or "User"
            embed = create_info_embed(f"Raid Panel for {display_name}", message)
            view = RaidPopupView(
                self.bot,
                mode=("manage" if can_manage else "main"),
                can_manage=can_manage,
                can_rename_thread=can_rename_thread,
            )
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            if source == "raid_popup":
                return await respond_popup("This is not an active raid thread.")
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
            await self.bot.db.add_raid_member_exclusion(raid_id, user_id, reason="voluntary")
        except Exception:
            pass

        try:
            await self.bot.db.delete_raid_join_request(raid_id, user_id)
        except Exception:
            pass

        if not removed:
            if source == "raid_popup":
                return await respond_popup("You are not part of this raid.")
            return await interaction.followup.send("You are not part of this raid.", ephemeral=True)

        try:
            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(f"{interaction.user.mention} left the raid.")
        except Exception:
            logging.exception("Failed to send leave message to raid thread")

        if source == "raid_popup":
            return await respond_popup("You have left the raid.")
        return await interaction.followup.send("You have left the raid.", ephemeral=True)

    @discord.ui.button(label="Leave Raid", style=discord.ButtonStyle.secondary, custom_id="raid_leave_raid", row=0)
    async def leave_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_leave_raid(interaction)

    async def handle_remove_raider(
        self,
        interaction: discord.Interaction,
        *,
        source: str | None = None,
        can_manage: bool = False,
        can_rename_thread: bool = False,
    ):
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            if source == "raid_popup":
                embed = create_info_embed("DKP", "This is not an active raid thread.")
                view = RaidPopupView(
                    self.bot,
                    mode=("manage" if can_manage else "main"),
                    can_manage=can_manage,
                    can_rename_thread=can_rename_thread,
                )
                try:
                    if not interaction.response.is_done():
                        return await interaction.response.edit_message(embed=embed, view=view)
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        return await msg.edit(embed=embed, view=view)
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                    return
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
            if source == "raid_popup":
                embed = create_info_embed("Remove Raider", "No raid members were found.")
                view = RaidPopupView(
                    self.bot,
                    mode=("manage" if can_manage else "main"),
                    can_manage=can_manage,
                    can_rename_thread=can_rename_thread,
                )
                try:
                    if not interaction.response.is_done():
                        return await interaction.response.edit_message(embed=embed, view=view)
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        return await msg.edit(embed=embed, view=view)
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                    return
            return await interaction.followup.send("No raid members were found.", ephemeral=True)

        member_list_order = "name"
        try:
            if interaction.guild:
                config = await self.bot.db.get_guild_config(int(interaction.guild.id))
                if config and ("raid_member_list_order" in getattr(config, "keys", lambda: [])()):
                    raw = config["raid_member_list_order"]
                    if raw:
                        member_list_order = str(raw)
        except Exception:
            pass

        view = RaidMemberRemoveView(
            self.bot,
            members,
            member_list_order=member_list_order,
            return_to_popup=(source == "raid_popup"),
            popup_can_manage=can_manage,
            popup_can_rename_thread=can_rename_thread,
        )

        if source == "raid_popup":
            embed = create_info_embed("Remove Raider", "Who do you want to remove from the raid?")
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return
            return

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

    @discord.ui.button(label="Remove Raider", style=discord.ButtonStyle.danger, custom_id="raid_remove_raider", row=2)
    async def remove_raider(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_remove_raider(interaction)

    async def handle_show_groups(self, interaction: discord.Interaction):
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
                except Exception:
                    pass

        if group_count <= 0:
            responded = False
            try:
                responded = bool(interaction.response.is_done())
            except Exception:
                responded = False

            try:
                if not responded:
                    return await interaction.response.send_message(
                        "Raid groups have not been created yet.",
                        ephemeral=True,
                    )
                return await interaction.followup.send(
                    "Raid groups have not been created yet.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                return

        if group_count > 0 and interaction.guild:
            embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
            can_manage = False
            try:
                can_manage = bool(int(interaction.user.id) == int(raid["leader_id"]) or await is_admin(interaction))
            except Exception:
                can_manage = False

            view = RaidGroupSignupModalView(
                self.bot,
                group_count=group_count,
                can_manage=can_manage,
            )

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

    @discord.ui.button(label="Groups", style=discord.ButtonStyle.secondary, custom_id="raid_show_groups", row=2)
    async def show_groups(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_show_groups(interaction)

    async def handle_rename_thread(
        self,
        interaction: discord.Interaction,
        *,
        source: str | None = None,
        can_manage: bool = False,
        can_rename_thread: bool = False,
    ):
        """Open a modal to rename the raid thread (raid leaders/officers only)."""
        async def respond_popup(message: str, *, title: str = "Rename Thread"):
            if source != "raid_popup":
                return
            embed = create_info_embed(title, message)
            popup_view = RaidPopupView(
                self.bot,
                mode=("manage" if can_manage else "main"),
                can_manage=can_manage,
                can_rename_thread=can_rename_thread,
            )
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=popup_view)
                else:
                    msg = getattr(interaction, "message", None)
                    if msg is not None:
                        await msg.edit(embed=embed, view=popup_view)
            except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
                return

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            await respond_popup("This is not an active raid thread.", title="Error")
            if source == "raid_popup":
                return
            if not interaction.response.is_done():
                return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)
            return await interaction.followup.send("This is not an active raid thread.", ephemeral=True)

        # Authorization check: raid leader, officer, or admin
        if not await is_officer(interaction) and interaction.user.id != raid["leader_id"]:
            await respond_popup("You don't have permission to rename this thread.", title="Error")
            if source == "raid_popup":
                return
            if not interaction.response.is_done():
                return await interaction.response.send_message(
                    "You don't have permission to rename this thread.",
                    ephemeral=True,
                )
            return await interaction.followup.send("You don't have permission to rename this thread.", ephemeral=True)

        from ..ui.modals import ThreadRenameModal
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            await respond_popup("Raid module is currently offline.", title="Error")
            if source == "raid_popup":
                return
            if not interaction.response.is_done():
                return await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)
            return await interaction.followup.send("Raid module is currently offline.", ephemeral=True)
        modal = ThreadRenameModal(
            raid_cog=raid_cog,
            raid_id=raid["id"],
            source=source,
            popup_can_manage=can_manage,
            popup_can_rename_thread=can_rename_thread,
            popup_message=(getattr(interaction, "message", None) if source == "raid_popup" else None),
        )
        try:
            await interaction.response.send_modal(modal)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            if source == "raid_popup":
                await respond_popup("Please try again.", title="Error")
                return
            try:
                await interaction.followup.send("Please try again.", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Rename Thread", style=discord.ButtonStyle.secondary, custom_id="raid_rename_thread", row=1)
    async def rename_thread(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_rename_thread(interaction)

    @discord.ui.button(label="❓ Help", style=discord.ButtonStyle.secondary, custom_id="raid_help", row=4)
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
                "**Raid Points** (leader/admin): View raid points for this raid (scoped/sorted).",
                "**Reverse Raid DKP** (leader/admin): Reverse DKP changes for this raid.",
                "**Stop Timed DKP** (leader/admin): Stops Timed DKP if it is currently running for this raid.",
                "**Set group** (leader/admin): Assign a raid member to a group (or ungroup them).",
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

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        admin_ok = await is_admin(interaction)
        is_leader = bool(raid and int(interaction.user.id) == int(raid["leader_id"]))
        can_manage = bool(is_leader or admin_ok)
        officer_ok = await is_officer(interaction)
        can_rename_thread = bool(can_manage or officer_ok)

        view = RaidPopupView(self.bot, mode="help", can_manage=can_manage, can_rename_thread=can_rename_thread)
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                msg = getattr(interaction, "message", None)
                if msg is not None:
                    await msg.edit(embed=embed, view=view)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
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

        required_role_id = None
        try:
            if interaction.guild is not None:
                config = await self.bot.db.get_guild_config(int(interaction.guild.id))
                if config and ("raider_role_id" in getattr(config, "keys", lambda: [])()):
                    required_role_id = config["raider_role_id"]
        except Exception:
            required_role_id = None
        try:
            required_role_id = int(required_role_id) if required_role_id else None
        except Exception:
            required_role_id = None

        is_eligible_raider = True
        if required_role_id and interaction.guild is not None:
            try:
                required_role = interaction.guild.get_role(required_role_id)
            except Exception:
                required_role = None
            if required_role is not None:
                try:
                    requester = interaction.guild.get_member(int(self.user_id))
                except Exception:
                    requester = None
                if requester is not None:
                    is_eligible_raider = required_role in list(getattr(requester, "roles", []) or [])

        if not is_eligible_raider:
            await self.bot.db.set_raid_join_request_status(
                self.raid_id,
                self.user_id,
                "denied",
                decided_by=int(interaction.user.id),
            )
            try:
                raid_row = await self._get_raid_row()
                guild, thread = await self._resolve_guild_and_thread(raid_row)
                mention = f"<@{self.user_id}>"
                if guild is not None:
                    member = guild.get_member(self.user_id)
                    if member is not None:
                        mention = member.mention
                if thread:
                    await thread.send(f"Join request denied for {mention} (missing required Raider role).")
                await self._notify_requester(False, thread)
            except Exception:
                logging.exception("Failed to send denial result to raid thread")

            await interaction.response.send_message("Denied (missing required Raider role).", ephemeral=True)
            await self._finalize(interaction)
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
        try:
            logging.info(
                "raid_open_panel: received interaction guild_id=%s channel_id=%s user_id=%s",
                getattr(getattr(interaction, "guild", None), "id", None),
                getattr(getattr(interaction, "channel", None), "id", None),
                getattr(getattr(interaction, "user", None), "id", None),
            )
        except Exception:
            pass
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.InteractionResponded, discord.NotFound, discord.HTTPException):
            pass
        if not await ensure_allowed_guild(interaction):
            return
        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog:
            try:
                await interaction.followup.send(
                    "Raid module is currently offline.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass
            return
        try:
            await raid_cog.send_ephemeral_raid_panel(interaction)
        except Exception:
            logging.exception(
                "raid_open_panel: failed to send ephemeral raid panel guild_id=%s channel_id=%s user_id=%s",
                getattr(getattr(interaction, "guild", None), "id", None),
                getattr(getattr(interaction, "channel", None), "id", None),
                getattr(getattr(interaction, "user", None), "id", None),
            )
            try:
                await interaction.followup.send(
                    "Failed to open raid control panel. Please try again.",
                    ephemeral=True,
                )
            except Exception:
                pass


class RaidGroupSignupModalSelect(discord.ui.Select):
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
            custom_id="raid_group_modal_select",
            row=0,
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

        try:
            raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
            raid_dict = raid
            if raid is not None and not isinstance(raid, dict):
                raid_dict = dict(raid)
            embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
            msg = getattr(interaction, "message", None)
            if msg is not None:
                await msg.edit(embed=embed, view=getattr(self, "view", None))
        except Exception:
            pass


class RaidGroupSignupModalView(discord.ui.View):
    def __init__(
        self,
        bot,
        *,
        group_count: int | None = None,
        can_manage: bool = False,
        return_to_popup: bool = False,
        popup_can_manage: bool = False,
        popup_can_rename_thread: bool = False,
    ):
        super().__init__(timeout=600)
        self.bot = bot
        self.group_count = group_count
        self.can_manage = bool(can_manage)
        self.return_to_popup = bool(return_to_popup)
        self.popup_can_manage = bool(popup_can_manage)
        self.popup_can_rename_thread = bool(popup_can_rename_thread)

        self.add_item(RaidGroupSignupModalSelect(bot, group_count=group_count))

    @discord.ui.button(label="Ungrouped", style=discord.ButtonStyle.secondary, custom_id="raid_group_modal_leave", row=1)
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

        await raid_cog.handle_group_signup(interaction, "ungrouped")

        try:
            raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
            raid_dict = raid
            if raid is not None and not isinstance(raid, dict):
                raid_dict = dict(raid)
            embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
            msg = getattr(interaction, "message", None)
            if msg is not None:
                await msg.edit(embed=embed, view=self)
        except Exception:
            pass

    @discord.ui.button(label="Remove from group", style=discord.ButtonStyle.secondary, custom_id="raid_group_modal_remove", row=2)
    async def remove_from_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.can_manage:
            return await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

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
            return await interaction.response.send_message("No raid members were found.", ephemeral=True)

        member_list_order = "name"
        try:
            if interaction.guild:
                config = await self.bot.db.get_guild_config(int(interaction.guild.id))
                if config and ("raid_member_list_order" in getattr(config, "keys", lambda: [])()):
                    raw = config["raid_member_list_order"]
                    if raw:
                        member_list_order = str(raw)
        except Exception:
            pass

        view = RaidMemberClearGroupView(
            self.bot,
            members,
            member_list_order=member_list_order,
            return_to_group_signup=True,
            group_signup_can_manage=self.can_manage,
            group_signup_return_to_popup=self.return_to_popup,
            group_signup_popup_can_manage=self.popup_can_manage,
            group_signup_popup_can_rename_thread=self.popup_can_rename_thread,
        )

        embed = create_info_embed("Remove from Group", "Who do you want to remove from their group?")
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="Clear All Groups", style=discord.ButtonStyle.danger, custom_id="raid_group_modal_clear_all", row=2)
    async def clear_all_groups(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.can_manage:
            return await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

        raid_id = int(raid["id"])

        try:
            cleared_count = await self.bot.db.clear_all_raid_member_groups(raid_id)
        except Exception:
            logging.exception("Failed to clear all raid member groups")
            return await interaction.response.send_message("Failed to clear groups. Please try again.", ephemeral=True)

        # Respond to interaction FIRST (before it expires)
        embed = create_info_embed("Clear All Groups", f"Cleared all group assignments ({cleared_count} member(s) affected).")
        await interaction.response.edit_message(embed=embed, view=self)

        # Refresh the group signup embed (after responding)
        try:
            raid_cog = self.bot.get_cog("RaidCog")
            if raid_cog:
                raid_dict = raid if isinstance(raid, dict) else dict(raid)
                embed = await raid_cog._build_group_signup_embed(raid_dict, interaction.guild)
                await raid_cog._ensure_group_panel_message(interaction.channel, raid_dict, embed)
        except Exception:
            logging.exception("Failed to refresh group signup message after clearing all groups")

        try:
            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.send(f"All group assignments have been cleared ({cleared_count} member(s) affected).")
        except Exception:
            logging.exception("Failed to send clear all groups message to raid thread")

    @discord.ui.button(label="Set group", style=discord.ButtonStyle.secondary, custom_id="raid_group_modal_set", row=3)
    async def set_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.can_manage:
            return await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

        group_count = 0
        try:
            group_count = int(raid.get("group_count") if isinstance(raid, dict) else raid["group_count"])
        except Exception:
            group_count = 0
        if group_count <= 0:
            return await interaction.response.send_message("Raid groups have not been configured yet.", ephemeral=True)

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
            return await interaction.response.send_message("No raid members were found.", ephemeral=True)

        member_list_order = "name"
        try:
            if interaction.guild:
                config = await self.bot.db.get_guild_config(int(interaction.guild.id))
                if config and ("raid_member_list_order" in getattr(config, "keys", lambda: [])()):
                    raw = config["raid_member_list_order"]
                    if raw:
                        member_list_order = str(raw)
        except Exception:
            pass

        view = RaidMemberAssignGroupView(
            self.bot,
            int(raid["id"]),
            members,
            int(group_count),
            member_list_order=member_list_order,
            show_bulk_ungrouped=await _has_grouped_members(self.bot, int(raid["id"])),
            return_to_group_signup=True,
            group_signup_can_manage=self.can_manage,
            group_signup_return_to_popup=self.return_to_popup,
            group_signup_popup_can_manage=self.popup_can_manage,
            group_signup_popup_can_rename_thread=self.popup_can_rename_thread,
        )
        embed = create_info_embed("Set Group", "Select a member, then select a group:")
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="Bulk set group", style=discord.ButtonStyle.secondary, custom_id="raid_group_modal_bulk_set", row=3)
    async def bulk_set_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.can_manage:
            return await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

        group_count = 0
        try:
            group_count = int(raid.get("group_count") if isinstance(raid, dict) else raid["group_count"])
        except Exception:
            group_count = 0
        if group_count <= 0:
            return await interaction.response.send_message("Raid groups have not been configured yet.", ephemeral=True)

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
            return await interaction.response.send_message("No raid members were found.", ephemeral=True)

        member_list_order = "name"
        try:
            if interaction.guild:
                config = await self.bot.db.get_guild_config(int(interaction.guild.id))
                if config and ("raid_member_list_order" in getattr(config, "keys", lambda: [])()):
                    raw = config["raid_member_list_order"]
                    if raw:
                        member_list_order = str(raw)
        except Exception:
            pass

        view = RaidBulkAssignGroupView(
            self.bot,
            int(raid["id"]),
            members,
            int(group_count),
            member_list_order=member_list_order,
            return_to_group_signup=True,
            group_signup_can_manage=self.can_manage,
            group_signup_return_to_popup=self.return_to_popup,
            group_signup_popup_can_manage=self.popup_can_manage,
            group_signup_popup_can_rename_thread=self.popup_can_rename_thread,
        )
        embed = create_info_embed("Bulk Set Group", "Select multiple members, then select a group to assign them all:")
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="From voice", style=discord.ButtonStyle.secondary, custom_id="raid_group_modal_from_voice", row=3)
    async def from_voice(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.can_manage:
            return await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.response.send_message("This is not an active raid thread.", ephemeral=True)

        group_count = 0
        try:
            group_count = int(raid.get("group_count") if isinstance(raid, dict) else raid["group_count"])
        except Exception:
            group_count = 0
        if group_count <= 0:
            return await interaction.response.send_message("Raid groups have not been configured yet.", ephemeral=True)

        raid_cog = self.bot.get_cog("RaidCog")
        if not raid_cog or not hasattr(raid_cog, "_get_linked_voice_channels"):
            return await interaction.response.send_message("Raid module is currently offline.", ephemeral=True)

        linked_vcs = await raid_cog._get_linked_voice_channels(interaction.guild, raid)
        if not linked_vcs:
            return await interaction.response.send_message(
                "No voice channels are linked to this raid. Use a raid started from a voice channel.",
                ephemeral=True,
            )

        view = RaidVoiceChannelGroupView(
            self.bot,
            int(raid["id"]),
            linked_vcs,
            int(group_count),
            return_to_group_signup=True,
            group_signup_can_manage=self.can_manage,
            group_signup_return_to_popup=self.return_to_popup,
            group_signup_popup_can_manage=self.popup_can_manage,
            group_signup_popup_can_rename_thread=self.popup_can_rename_thread,
        )
        embed = create_info_embed("From Voice Channel", "Select a voice channel, then select a group to assign all its members:")
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, custom_id="raid_group_modal_back", row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.return_to_popup:
            return await interaction.response.edit_message(view=None)

        view = RaidPopupView(
            self.bot,
            mode=("manage" if self.popup_can_manage else "main"),
            can_manage=self.popup_can_manage,
            can_rename_thread=self.popup_can_rename_thread,
        )
        embed = view._manage_embed(interaction) if self.popup_can_manage else view._main_embed(interaction, can_manage=self.popup_can_manage)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="raid_group_modal_close", row=4)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)


class RaidGroupSignupSelect(discord.ui.Select):
    def __init__(self, bot, group_count: int | None = None):
        self.bot = bot
        max_groups = 25
        try:
            if group_count is not None:
                max_groups = max(1, min(int(group_count), 25))
        except Exception:
            max_groups = 25
        options = [discord.SelectOption(label="Ungrouped", value="ungrouped")]
        options.extend(
            [
                discord.SelectOption(label=f"Group {i}", value=str(i))
                for i in range(1, max_groups + 1)
            ]
        )
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

    @discord.ui.button(label="Ungrouped", style=discord.ButtonStyle.secondary, custom_id="raid_group_leave")
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

        await raid_cog.handle_group_signup(interaction, "ungrouped")


class GuildBankPanelView(discord.ui.View):
    """Persistent panel view for the guild bank channel with Deposit and Withdraw buttons."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_allowed_guild(interaction)

    @discord.ui.button(
        label="Deposit",
        style=discord.ButtonStyle.success,
        custom_id="guild_bank_deposit",
        emoji="📥",
    )
    async def deposit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        officer_ok = await is_officer(interaction)
        if not officer_ok:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Only officers can deposit items.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Only officers can deposit items.", ephemeral=True
                    )
            except discord.HTTPException:
                pass
            return

        bank_cog = self.bot.get_cog("GuildBankCog")
        if not bank_cog:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Guild bank module is currently offline.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Guild bank module is currently offline.", ephemeral=True
                    )
            except discord.HTTPException:
                pass
            return

        await interaction.response.send_modal(GuildBankDepositModal(bank_cog))

    @discord.ui.button(
        label="Withdraw",
        style=discord.ButtonStyle.danger,
        custom_id="guild_bank_withdraw",
        emoji="📤",
    )
    async def withdraw_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        officer_ok = await is_officer(interaction)
        if not officer_ok:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Only officers can withdraw items.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Only officers can withdraw items.", ephemeral=True
                    )
            except discord.HTTPException:
                pass
            return

        bank_cog = self.bot.get_cog("GuildBankCog")
        if not bank_cog:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Guild bank module is currently offline.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Guild bank module is currently offline.", ephemeral=True
                    )
            except discord.HTTPException:
                pass
            return

        await interaction.response.send_modal(GuildBankWithdrawModal(bank_cog))

