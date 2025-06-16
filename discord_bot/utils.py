import discord

async def is_officer(interaction: discord.Interaction) -> bool:
    """Checks if the user is an officer or has admin permissions."""
    if interaction.user.guild_permissions.administrator:
        return True
    # In a real bot, you'd fetch the configured officer_role_id from the DB
    # and check if the user has that role. For now, we'll just check for admin.
    # config = await interaction.client.db.get_guild_config(interaction.guild.id)
    # officer_role_id = config['officer_role_id'] if config else None
    # if officer_role_id and discord.utils.get(interaction.user.roles, id=officer_role_id):
    #    return True
    return False

def create_info_embed(title: str, description: str) -> discord.Embed:
    """Creates a standard blue informational embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.blue())

def create_success_embed(title: str, description: str) -> discord.Embed:
    """Creates a standard green success embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.green())

def create_error_embed(title: str, description:str) -> discord.Embed:
    """Creates a standard red error embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.red())
