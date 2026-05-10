import os
import logging
import inspect
import discord

def _get_allowed_guild_ids() -> set[int]:
    raw = os.getenv("ALLOWED_GUILD_IDS")
    ids: set[int] = set()
    if not raw:
        return ids
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            ids.add(int(piece))
        except ValueError:
            continue
    return ids


async def _resolve_member(guild: discord.Guild | None, user: discord.abc.User | None) -> discord.Member | None:
    if not guild or not user:
        return None
    if isinstance(user, discord.Member):
        return user
    member = guild.get_member(getattr(user, "id", 0))
    if member:
        return member
    try:
        return await guild.fetch_member(getattr(user, "id", 0))
    except Exception:
        return None


async def is_officer(interaction: discord.Interaction) -> bool:
    """Checks if the user is an officer or has admin permissions."""
    guild = getattr(interaction, "guild", None)
    user = getattr(interaction, "user", None)

    # If this interaction is not in a guild or the user is not a guild member,
    # treat them as a non-officer to avoid attribute errors in DMs.
    member = await _resolve_member(guild, user)
    if not guild or not member:
        return False

    admin_flag = getattr(getattr(member, "guild_permissions", None), "administrator", False)
    if isinstance(admin_flag, bool) and admin_flag:
        return True

    guild_roles = getattr(guild, "roles", None) or []
    if inspect.isawaitable(guild_roles):
        guild_roles = []
    member_roles = getattr(member, "roles", None) or []
    if inspect.isawaitable(member_roles):
        member_roles = []

    dkp_admin_role_id = None
    for role in list(guild_roles):
        role_name = (getattr(role, "name", "") or "").strip().casefold()
        if role_name == "dkp admin":
            dkp_admin_role_id = getattr(role, "id", None)
            break
    if dkp_admin_role_id is not None:
        for role in list(member_roles):
            if getattr(role, "id", None) == dkp_admin_role_id:
                return True

    try:
        config = await interaction.client.db.get_guild_config(guild.id)
    except Exception:
        config = None
    admin_role_id = None
    if config and ("admin_role_id" in getattr(config, "keys", lambda: [])()):
        admin_role_id = config["admin_role_id"]
    if admin_role_id:
        try:
            admin_role_id = int(admin_role_id)
        except Exception:
            admin_role_id = None
    if admin_role_id:
        for role in list(member_roles):
            if getattr(role, "id", None) == admin_role_id:
                return True

    officer_role_id = None
    if config and ("officer_role_id" in getattr(config, "keys", lambda: [])()):
        officer_role_id = config["officer_role_id"]
    if officer_role_id:
        try:
            officer_role_id = int(officer_role_id)
        except Exception:
            officer_role_id = None
    if officer_role_id:
        for role in list(member_roles):
            if getattr(role, "id", None) == officer_role_id:
                return True

    fallback_officer_role_id = None
    for role in list(guild_roles):
        role_name = (getattr(role, "name", "") or "").strip().casefold()
        if role_name == "officer":
            fallback_officer_role_id = getattr(role, "id", None)
            break
    if fallback_officer_role_id is not None:
        for role in list(member_roles):
            if getattr(role, "id", None) == fallback_officer_role_id:
                return True
    return False

async def is_admin(interaction: discord.Interaction) -> bool:
    guild = getattr(interaction, "guild", None)
    user = getattr(interaction, "user", None)

    member = await _resolve_member(guild, user)
    if not guild or not member:
        return False

    # Always allow true server admins as a backstop (e.g. initial setup).
    admin_flag = getattr(getattr(member, "guild_permissions", None), "administrator", False)
    if isinstance(admin_flag, bool) and admin_flag:
        return True

    guild_roles = getattr(guild, "roles", None) or []
    if inspect.isawaitable(guild_roles):
        guild_roles = []
    member_roles = getattr(member, "roles", None) or []
    if inspect.isawaitable(member_roles):
        member_roles = []

    dkp_admin_role_id = None
    for role in list(guild_roles):
        role_name = (getattr(role, "name", "") or "").strip().casefold()
        if role_name == "dkp admin":
            dkp_admin_role_id = getattr(role, "id", None)
            break
    if dkp_admin_role_id is not None:
        for role in list(member_roles):
            if getattr(role, "id", None) == dkp_admin_role_id:
                return True

    # Otherwise, allow users who have the configured bot-admin role.
    try:
        config = await interaction.client.db.get_guild_config(guild.id)
    except Exception:
        config = None
    admin_role_id = None
    if config and ("admin_role_id" in getattr(config, "keys", lambda: [])()):
        admin_role_id = config["admin_role_id"]
    if admin_role_id:
        try:
            admin_role_id = int(admin_role_id)
        except Exception:
            admin_role_id = None
    if admin_role_id:
        for role in list(member_roles):
            if getattr(role, "id", None) == admin_role_id:
                return True

    return False


async def is_raid_leader(interaction: discord.Interaction) -> bool:
    guild = getattr(interaction, "guild", None)
    user = getattr(interaction, "user", None)

    member = await _resolve_member(guild, user)
    if not guild or not member:
        return False

    guild_roles = getattr(guild, "roles", None) or []
    if inspect.isawaitable(guild_roles):
        guild_roles = []
    member_roles = getattr(member, "roles", None) or []
    if inspect.isawaitable(member_roles):
        member_roles = []

    try:
        config = await interaction.client.db.get_guild_config(guild.id)
    except Exception:
        config = None

    raid_leader_role_id = None
    if config and ("raid_leader_role_id" in getattr(config, "keys", lambda: [])()):
        raid_leader_role_id = config["raid_leader_role_id"]
    if raid_leader_role_id:
        try:
            raid_leader_role_id = int(raid_leader_role_id)
        except Exception:
            raid_leader_role_id = None
    if raid_leader_role_id:
        for role in list(member_roles):
            if getattr(role, "id", None) == raid_leader_role_id:
                return True

    fallback_raid_leader_role_id = None
    for role in list(guild_roles):
        role_name = (getattr(role, "name", "") or "").strip().casefold()
        if role_name in {"raid-leader", "raid leader"}:
            fallback_raid_leader_role_id = getattr(role, "id", None)
            break
    if fallback_raid_leader_role_id is not None:
        for role in list(member_roles):
            if getattr(role, "id", None) == fallback_raid_leader_role_id:
                return True

    return False


async def can_manage_raid(interaction: discord.Interaction, raid) -> bool:
    """Return True if the user is the raid leader, a bot admin, or a raid manager for this raid."""
    admin_ok = await is_admin(interaction)
    if admin_ok:
        return True
    user_id = int(getattr(interaction.user, "id", 0))
    try:
        leader_id = int(raid["leader_id"]) if raid and raid["leader_id"] else 0
    except (KeyError, TypeError):
        leader_id = 0
    if user_id == leader_id:
        return True
    try:
        raid_id = raid["id"] if raid else None
    except (KeyError, TypeError):
        raid_id = None
    if raid_id is not None:
        try:
            return await interaction.client.db.is_raid_manager(int(raid_id), user_id)
        except Exception:
            logging.warning("Failed to check raid manager status for raid %s user %s", raid_id, user_id, exc_info=True)
    return False


async def is_allowed_guild(interaction: discord.Interaction) -> bool:
    guild = getattr(interaction, "guild", None)
    allowed = _get_allowed_guild_ids()
    if not allowed:
        return True
    return bool(guild and guild.id in allowed)


async def ensure_allowed_guild(interaction: discord.Interaction) -> bool:
    if await is_allowed_guild(interaction):
        return True
    try:
        msg = "This bot is not authorized for this server."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except Exception:
        logging.exception("Failed to send ephemeral message")
    return False

async def send_dkp_change_dm(
    member: discord.abc.User,
    guild: discord.Guild | None,
    amount: int,
    reason: str,
    new_total: int | None = None,
):
    if not isinstance(member, (discord.Member, discord.User)):
        return
    guild_name = guild.name if guild else "this server"
    change_word = "increased" if amount > 0 else "decreased" if amount < 0 else "updated"
    sign = "+" if amount >= 0 else "-"
    abs_amount = abs(amount)
    lines: list[str] = [
        f"Your DKP has been {change_word} in **{guild_name}**.",
        f"Change: `{sign}{abs_amount}` DKP",
    ]
    reason = (reason or "").strip()
    if reason:
        lines.append(f"Reason: {reason}")
    if new_total is not None:
        lines.append(f"Current DKP count: `{new_total}` DKP")
    message = "\n".join(lines)
    try:
        await member.send(message)
    except Exception as e:
        logging.info("Failed to send DKP DM to user_id=%s: %s", getattr(member, "id", "unknown"), e)

def create_info_embed(title: str, description: str) -> discord.Embed:
    """Creates a standard blue informational embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.blue())

def create_success_embed(title: str, description: str) -> discord.Embed:
    """Creates a standard green success embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.green())

def create_error_embed(title: str, description:str) -> discord.Embed:
    """Creates a standard red error embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.red())
