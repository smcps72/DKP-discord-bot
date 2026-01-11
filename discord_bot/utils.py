import os
import logging
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


async def is_officer(interaction: discord.Interaction) -> bool:
    """Checks if the user is an officer or has admin permissions."""
    guild = getattr(interaction, "guild", None)
    user = getattr(interaction, "user", None)

    # If this interaction is not in a guild or the user is not a guild member,
    # treat them as a non-officer to avoid attribute errors in DMs.
    if not guild or not isinstance(user, discord.Member):
        return False

    if user.guild_permissions.administrator:
        return True

    dkp_admin_role = discord.utils.get(guild.roles, name="DKP-Admin")
    if dkp_admin_role and discord.utils.get(user.roles, id=dkp_admin_role.id):
        return True

    config = await interaction.client.db.get_guild_config(guild.id)
    admin_role_id = None
    if config and ("admin_role_id" in getattr(config, "keys", lambda: [])()):
        admin_role_id = config["admin_role_id"]
    if admin_role_id and discord.utils.get(user.roles, id=admin_role_id):
        return True

    officer_role_id = None
    if config and ("officer_role_id" in getattr(config, "keys", lambda: [])()):
        officer_role_id = config["officer_role_id"]
    if officer_role_id and discord.utils.get(user.roles, id=officer_role_id):
        return True
    return False

async def is_admin(interaction: discord.Interaction) -> bool:
    guild = getattr(interaction, "guild", None)
    user = getattr(interaction, "user", None)

    if not guild or not isinstance(user, discord.Member):
        return False

    # Always allow true server admins as a backstop (e.g. initial setup).
    if bool(getattr(user, "guild_permissions", None) and user.guild_permissions.administrator):
        return True

    dkp_admin_role = discord.utils.get(guild.roles, name="DKP-Admin")
    if dkp_admin_role and discord.utils.get(user.roles, id=dkp_admin_role.id):
        return True

    # Otherwise, allow users who have the configured bot-admin role.
    config = await interaction.client.db.get_guild_config(guild.id)
    admin_role_id = None
    if config and ("admin_role_id" in getattr(config, "keys", lambda: [])()):
        admin_role_id = config["admin_role_id"]
    if admin_role_id and discord.utils.get(user.roles, id=admin_role_id):
        return True

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
        lines.append(f"New total: `{new_total}` DKP")
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
