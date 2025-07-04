import pytest
from unittest.mock import AsyncMock, MagicMock

from discord_bot.cogs.reset_cog import ResetCog
from discord_bot.database import Database

# Mock discord.py objects
class MockRole(MagicMock):
    def __init__(self, id, *args, **kwargs):
        name = kwargs.pop('name', None)
        super().__init__(*args, **kwargs)
        self.id = id
        self.name = name
        self.delete = AsyncMock()

class MockChannel(MagicMock):
    def __init__(self, id, *args, **kwargs):
        name = kwargs.pop('name', None)
        super().__init__(*args, **kwargs)
        self.id = id
        self.name = name
        self.delete = AsyncMock()

class MockGuild(MagicMock):
    def __init__(self, id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.id = id
        self.get_role = MagicMock()
        self.get_channel = MagicMock()

class MockInteraction(MagicMock):
    def __init__(self, guild, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guild = guild
        self.response = MagicMock()
        self.response.defer = AsyncMock()
        self.followup = MagicMock()
        self.followup.send = AsyncMock()

@pytest.mark.asyncio
async def test_reset_command():
    """Test the /reset command to ensure it cleans up all resources."""
    # 1. Setup Test Environment
    db = Database(":memory:")
    await db.connect()

    # -- Create mock discord objects --
    guild_id = 100
    category_id, dkp_channel_id, raid_channel_id = 200, 201, 202
    officer_role_id, raider_role_id = 300, 301

    mock_guild = MockGuild(guild_id)
    mock_guild.name = "Test Guild"
    mock_category = MockChannel(id=category_id, name='dkp-category')
    mock_dkp_channel = MockChannel(id=dkp_channel_id, name='dkp')
    mock_raid_channel = MockChannel(id=raid_channel_id, name='raids')
    mock_officer_role = MockRole(id=officer_role_id, name='Officer')
    mock_raider_role = MockRole(id=raider_role_id, name='Raider')

    def get_channel_side_effect(channel_id):
        if channel_id == category_id: return mock_category
        if channel_id == dkp_channel_id: return mock_dkp_channel
        if channel_id == raid_channel_id: return mock_raid_channel
        return None
    
    def get_role_side_effect(role_id):
        if role_id == officer_role_id: return mock_officer_role
        if role_id == raider_role_id: return mock_raider_role
        return None

    mock_guild.get_channel.side_effect = get_channel_side_effect
    mock_guild.get_role.side_effect = get_role_side_effect

    # -- Create mock bot and cog --
    mock_bot = MagicMock()
    mock_bot.db = db
    cog = ResetCog(mock_bot)

    # -- Populate database with fake config --
    await db.execute(
        "INSERT INTO guilds (guild_id, dkp_category_id, dkp_channel_id, raid_channel_id, officer_role_id, raider_role_id) VALUES (?, ?, ?, ?, ?, ?)",
        (guild_id, category_id, dkp_channel_id, raid_channel_id, officer_role_id, raider_role_id)
    )
    await db.execute("INSERT INTO users (user_id, guild_id, dkp) VALUES (?, ?, ?)", (123, guild_id, 50))

    # 2. Run the Command
    mock_interaction = MockInteraction(mock_guild)
    await cog.reset.callback(cog, mock_interaction)

    # 3. Assert Results
    # -- Check that discord objects were deleted --
    mock_category.delete.assert_called_once()
    mock_dkp_channel.delete.assert_called_once()
    mock_raid_channel.delete.assert_called_once()
    mock_officer_role.delete.assert_called_once()
    mock_raider_role.delete.assert_called_once()

    # -- Check that database was cleaned --
    guild_config = await db.get_guild_config(guild_id)
    assert guild_config is None, "Guild config should have been deleted"

    user_row = await db.fetchone("SELECT * FROM users WHERE guild_id = ?", (guild_id,))
    assert user_row is None, "User data for the guild should have been deleted"

    # -- Check that user was notified --
    mock_interaction.followup.send.assert_called_once_with(
        "Bot configuration has been completely reset. You can now run `/setup` again.", ephemeral=True
    )

    # 4. Teardown
    await db.conn.close()
