import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.cogs.raid_cog import RaidCog

@pytest.fixture
def raid_cog():
    bot = MagicMock()
    bot.db = AsyncMock()
    return RaidCog(bot)

@pytest.fixture
def mock_interaction():
    interaction = MagicMock()
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.guild = MagicMock()
    return interaction

@patch('discord_bot.cogs.raid_cog.is_officer', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_award_dkp_cmd(mock_is_officer, raid_cog, mock_interaction):
    mock_is_officer.return_value = True
    member = MagicMock()
    raid_cog.process_dkp_adjustment = AsyncMock()

    await raid_cog.award_dkp_cmd.callback(raid_cog, mock_interaction, member, 5, "Reason")

    mock_is_officer.assert_called_once_with(mock_interaction)
    raid_cog.process_dkp_adjustment.assert_awaited_once_with(mock_interaction, "Award", "5", "Reason", member)

@patch('discord_bot.cogs.raid_cog.is_officer', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_award_dkp_cmd_not_officer(mock_is_officer, raid_cog, mock_interaction):
    mock_is_officer.return_value = False
    member = MagicMock()
    raid_cog.process_dkp_adjustment = AsyncMock()

    await raid_cog.award_dkp_cmd.callback(raid_cog, mock_interaction, member, 5, "Reason")

    mock_interaction.response.send_message.assert_called_once_with("You must be an officer to use this command.", ephemeral=True)
    raid_cog.process_dkp_adjustment.assert_not_called()
