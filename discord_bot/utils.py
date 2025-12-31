import discord

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

    config = await interaction.client.db.get_guild_config(guild.id)
    officer_role_id = config['officer_role_id'] if config else None
    if officer_role_id and discord.utils.get(user.roles, id=officer_role_id):
        return True
    return False

async def is_admin(interaction: discord.Interaction) -> bool:
    guild = getattr(interaction, "guild", None)
    user = getattr(interaction, "user", None)

    if not guild or not isinstance(user, discord.Member):
        return False

    return bool(getattr(user, "guild_permissions", None) and user.guild_permissions.administrator)

def create_info_embed(title: str, description: str) -> discord.Embed:
    """Creates a standard blue informational embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.blue())

def create_success_embed(title: str, description: str) -> discord.Embed:
    """Creates a standard green success embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.green())

def create_error_embed(title: str, description:str) -> discord.Embed:
    """Creates a standard red error embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.red())
