import pytest
import discord
from discord.ext import commands
from unittest.mock import AsyncMock, MagicMock, patch
import io

from discord_bot.cogs.admin_cog import AdminCog
from discord_bot.utils import create_info_embed # Used by the cog

# Basic scaffolding for the test file
@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=commands.Bot)
    bot.db = AsyncMock()
    bot.latency = 0.12345 # Example latency
    return bot

@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 12345
    guild.name = "Test Guild"
    guild.get_member = MagicMock(return_value=None) # Default mock for get_member
    return guild

@pytest.fixture
def mock_interaction(mock_guild): # Depends on mock_guild to set interaction.guild
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = mock_guild
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    interaction.followup = AsyncMock(spec=discord.Webhook)
    interaction.user = MagicMock(spec=discord.Member) # For permission checks if needed later
    return interaction

@pytest.fixture
def admin_cog(mock_bot):
    return AdminCog(mock_bot)

# Example test structure
@pytest.mark.asyncio
async def test_create_status_embed_with_config_and_raids(admin_cog: AdminCog, mock_bot: MagicMock, mock_guild: MagicMock):
    # --- Arrange ---
    guild_id = mock_guild.id
    mock_bot.db.get_guild_config = AsyncMock(return_value={'license_status': 'active'})
    mock_bot.db.fetchone = AsyncMock(return_value={'count': 5})
    expected_latency_ms = mock_bot.latency * 1000

    # --- Act ---
    embed = await admin_cog._create_status_embed(guild_id)

    # --- Assert ---
    mock_bot.db.get_guild_config.assert_called_once_with(guild_id)
    mock_bot.db.fetchone.assert_called_once_with(
        "SELECT COUNT(*) as count FROM raids WHERE guild_id = ? AND is_active = 1",
        (guild_id,)
    )

    assert embed.title == "Bot Status"
    assert f"• **Discord API:** {expected_latency_ms:.2f}ms" in embed.description
    assert "• **Subscription:** `Active`" in embed.description # Capitalized by the method
    assert "• **Active Raids:** 5" in embed.description

@pytest.mark.asyncio
async def test_create_status_embed_no_config_no_raids(admin_cog: AdminCog, mock_bot: MagicMock, mock_guild: MagicMock):
    # --- Arrange ---
    guild_id = mock_guild.id
    mock_bot.db.get_guild_config = AsyncMock(return_value=None) # No config
    mock_bot.db.fetchone = AsyncMock(return_value={'count': 0}) # No active raids
    expected_latency_ms = mock_bot.latency * 1000

    # --- Act ---
    embed = await admin_cog._create_status_embed(guild_id)

    # --- Assert ---
    mock_bot.db.get_guild_config.assert_called_once_with(guild_id)
    mock_bot.db.fetchone.assert_called_once_with(
        "SELECT COUNT(*) as count FROM raids WHERE guild_id = ? AND is_active = 1",
        (guild_id,)
    )

    assert embed.title == "Bot Status"
    assert f"• **Discord API:** {expected_latency_ms:.2f}ms" in embed.description
    assert "• **Subscription:** `Unknown`" in embed.description # Default when no config
    assert "• **Active Raids:** 0" in embed.description

@pytest.mark.asyncio
async def test_status_cmd(admin_cog: AdminCog, mock_interaction: AsyncMock, mock_bot: MagicMock):
    # --- Arrange ---
    # guild.id is already part of mock_interaction via mock_guild fixture

    # Mock the _create_status_embed method on the cog instance for this test
    # to avoid re-testing its internal logic here.
    # We just need to ensure it's called and its result is used.
    expected_embed = discord.Embed(title="Mocked Status Embed")
    admin_cog._create_status_embed = AsyncMock(return_value=expected_embed)

    # --- Act ---
    # For app commands, call the callback: cog_instance.command_name.callback(cog_instance, interaction, ...args)
    await admin_cog.status_cmd.callback(admin_cog, mock_interaction)

    # --- Assert ---
    # 1. Verify interaction.response.defer was called
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)

    # 2. Verify _create_status_embed was called with the correct guild_id
    admin_cog._create_status_embed.assert_called_once_with(mock_interaction.guild.id)

    # 3. Verify interaction.followup.send was called with the embed from _create_status_embed
    mock_interaction.followup.send.assert_called_once_with(embed=expected_embed, ephemeral=True)

@pytest.mark.asyncio
async def test_history_cmd_with_records(admin_cog: AdminCog, mock_interaction: AsyncMock, mock_bot: MagicMock, mock_guild: MagicMock):
    # --- Arrange ---
    mock_interaction.guild = mock_guild # Ensure interaction has the guild from fixture

    timestamp_str = "2023-10-26 10:00:00"
    mock_records = [
        {'user_id': 111, 'change': 10, 'reason': 'Raid A Win', 'timestamp': timestamp_str},
        {'user_id': 222, 'change': -5, 'reason': 'Purchase Item X', 'timestamp': timestamp_str},
    ]
    mock_bot.db.fetchall = AsyncMock(return_value=mock_records)

    mock_member_111 = MagicMock(spec=discord.Member)
    mock_member_111.id = 111
    mock_member_111.__str__ = MagicMock(return_value="User111") # Mock how member is stringified

    def get_member_side_effect(user_id):
        if user_id == 111:
            return mock_member_111
        return None # For user_id 222, simulate not found

    mock_guild.get_member = MagicMock(side_effect=get_member_side_effect)

    # --- Act ---
    await admin_cog.history_cmd.callback(admin_cog, mock_interaction)

    # --- Assert ---
    # 1. Verify defer
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)

    # 2. Verify db call
    mock_bot.db.fetchall.assert_called_once_with(
        "SELECT user_id, change, reason, timestamp FROM transactions WHERE guild_id = ? AND timestamp >= date('now', '-30 days')",
        (mock_guild.id,)
    )

    # 3. Verify get_member calls
    assert mock_guild.get_member.call_count == len(mock_records)
    mock_guild.get_member.assert_any_call(111)
    mock_guild.get_member.assert_any_call(222)

    # 4. Verify followup.send with file
    mock_interaction.followup.send.assert_called_once()
    args, kwargs = mock_interaction.followup.send.call_args
    assert args[0] == "Here is the DKP transaction history for the last 30 days:"
    assert "file" in kwargs
    assert isinstance(kwargs["file"], discord.File)
    assert kwargs["file"].filename == "dkp_history.csv"
    assert kwargs["ephemeral"] is True

    # (Optional advanced) Verify CSV content
    # To do this, we need access to the BytesIO stream passed to discord.File
    # The discord.File constructor takes a file-like object.
    # We can capture it if we mock discord.File or patch io.BytesIO

    # For simplicity here, we'll trust the csv module and the data transformation.
    # A more involved test could mock discord.File and inspect its fp attribute.
    # Example (conceptual, would require more setup or a helper):
    # file_arg = kwargs["file"]
    # file_content_bytes = file_arg.fp.getvalue() # fp is the file pointer
    # file_content_str = file_content_bytes.decode()
    # assert "Timestamp,User ID,User Name,DKP Change,Reason" in file_content_str
    # assert f"{timestamp_str},111,User111,10,Raid A Win" in file_content_str
    # assert f"{timestamp_str},222,Unknown User (222),-5,Purchase Item X" in file_content_str

@pytest.mark.asyncio
async def test_history_cmd_no_records(admin_cog: AdminCog, mock_interaction: AsyncMock, mock_bot: MagicMock, mock_guild: MagicMock):
    # --- Arrange ---
    mock_interaction.guild = mock_guild
    mock_bot.db.fetchall = AsyncMock(return_value=[]) # No records

    # --- Act ---
    await admin_cog.history_cmd.callback(admin_cog, mock_interaction)

    # --- Assert ---
    # 1. Verify defer
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)

    # 2. Verify db call
    mock_bot.db.fetchall.assert_called_once_with(
        "SELECT user_id, change, reason, timestamp FROM transactions WHERE guild_id = ? AND timestamp >= date('now', '-30 days')",
        (mock_guild.id,)
    )

    # 3. Verify followup.send with "no history" message
    mock_interaction.followup.send.assert_called_once_with(
        "No transaction history found for the last 30 days.", ephemeral=True
    )

    # 4. Ensure get_member was not called if no records
    mock_guild.get_member.assert_not_called()
