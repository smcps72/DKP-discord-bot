import pytest
from unittest.mock import MagicMock, AsyncMock
import discord

from discord_bot import utils

@pytest.mark.asyncio
async def test_is_officer_admin():
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.user = MagicMock(spec=discord.Member)
    mock_interaction.user.guild_permissions = MagicMock(spec=discord.Permissions)
    mock_interaction.user.guild_permissions.administrator = True

    assert await utils.is_officer(mock_interaction) is True

@pytest.mark.asyncio
async def test_is_officer_not_admin():
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.user = MagicMock(spec=discord.Member)
    mock_interaction.user.guild_permissions = MagicMock(spec=discord.Permissions)
    mock_interaction.user.guild_permissions.administrator = False
    mock_interaction.user.roles = []
    mock_interaction.client = MagicMock()
    mock_interaction.client.db = MagicMock()
    mock_interaction.client.db.get_guild_config = AsyncMock(return_value={'officer_role_id': 12345})

    assert await utils.is_officer(mock_interaction) is False

@pytest.mark.asyncio
async def test_is_officer_with_role():
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.user = MagicMock(spec=discord.Member)
    mock_interaction.user.guild_permissions = MagicMock(spec=discord.Permissions)
    mock_interaction.user.guild_permissions.administrator = False
    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 12345
    mock_interaction.user.roles = [mock_role]
    mock_interaction.client = MagicMock()
    mock_interaction.client.db = MagicMock()
    mock_interaction.client.db.get_guild_config = AsyncMock(return_value={'officer_role_id': 12345})

    assert await utils.is_officer(mock_interaction) is True


@pytest.mark.asyncio
async def test_is_admin_server_admin_true():
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.user = MagicMock(spec=discord.Member)
    mock_interaction.user.guild_permissions = MagicMock(spec=discord.Permissions)
    mock_interaction.user.guild_permissions.administrator = True
    mock_interaction.guild = MagicMock(spec=discord.Guild)

    assert await utils.is_admin(mock_interaction) is True


@pytest.mark.asyncio
async def test_is_admin_with_configured_role():
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.guild = MagicMock(spec=discord.Guild)
    mock_interaction.user = MagicMock(spec=discord.Member)
    mock_interaction.user.guild_permissions = MagicMock(spec=discord.Permissions)
    mock_interaction.user.guild_permissions.administrator = False

    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 999
    mock_interaction.user.roles = [mock_role]

    mock_interaction.client = MagicMock()
    mock_interaction.client.db = MagicMock()
    mock_interaction.client.db.get_guild_config = AsyncMock(return_value={'admin_role_id': 999})

    assert await utils.is_admin(mock_interaction) is True


@pytest.mark.asyncio
async def test_is_admin_without_permission_or_role():
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.guild = MagicMock(spec=discord.Guild)
    mock_interaction.user = MagicMock(spec=discord.Member)
    mock_interaction.user.guild_permissions = MagicMock(spec=discord.Permissions)
    mock_interaction.user.guild_permissions.administrator = False
    mock_interaction.user.roles = []

    mock_interaction.client = MagicMock()
    mock_interaction.client.db = MagicMock()
    mock_interaction.client.db.get_guild_config = AsyncMock(return_value={'admin_role_id': 999})

    assert await utils.is_admin(mock_interaction) is False

def test_create_info_embed():
    title = "Test Info"
    description = "This is an informational message."
    embed = utils.create_info_embed(title, description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.blue()

def test_create_success_embed():
    title = "Test Success"
    description = "This is a success message."
    embed = utils.create_success_embed(title, description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.green()

def test_create_error_embed():
    title = "Test Error"
    description = "This is an error message."
    embed = utils.create_error_embed(title, description)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == discord.Color.red()
