import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from discord_bot.ui.views import WelcomeView

# Mock objects for testing
class MockGuild(MagicMock):
    def __init__(self, id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.id = id

class MockUser(MagicMock):
    def __init__(self, id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.id = id

class MockInteraction(MagicMock):
    def __init__(self, guild, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guild = guild
        self.user = user
        self.response = MagicMock()
        self.response.defer = AsyncMock()
        self.response.send_message = AsyncMock()
        self.followup = MagicMock()
        self.followup.send = AsyncMock()

@pytest.fixture
def mock_bot():
    return MagicMock()

@pytest.fixture
def mock_interaction():
    guild = MockGuild(id=123)
    user = MockUser(id=456)
    return MockInteraction(guild=guild, user=user)

@pytest.mark.asyncio
async def test_welcome_view_create_raid_button(mock_bot, mock_interaction):
    """Tests that the 'Create Raid' button defers and calls the correct cog method."""
    # Arrange
    mock_raid_cog = MagicMock()
    mock_raid_cog.create_raid_from_interaction = AsyncMock()
    mock_bot.get_cog.return_value = mock_raid_cog
    view = WelcomeView(bot=mock_bot)

    # Act
    await view.create_raid.callback(mock_interaction, MagicMock())

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True, thinking=True)
    mock_raid_cog.create_raid_from_interaction.assert_called_once_with(mock_interaction)

@pytest.mark.asyncio
async def test_welcome_view_my_dkp_button(mock_bot, mock_interaction):
    """Tests that the 'My DKP' button defers and calls the correct cog method."""
    # Arrange
    mock_user_cog = MagicMock()
    mock_user_cog.show_my_dkp = AsyncMock()
    mock_bot.get_cog.return_value = mock_user_cog
    view = WelcomeView(bot=mock_bot)

    # Act
    await view.my_dkp.callback(mock_interaction, MagicMock())

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_user_cog.show_my_dkp.assert_called_once_with(mock_interaction)

@patch('discord_bot.ui.views.is_officer', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_welcome_view_admin_button_as_officer(mock_is_officer, mock_bot, mock_interaction):
    """Tests the admin button for an authorized officer."""
    # Arrange
    mock_is_officer.return_value = True
    mock_admin_cog = MagicMock()
    mock_admin_cog._create_status_embed = AsyncMock(return_value="embed_content")
    mock_bot.get_cog.return_value = mock_admin_cog
    view = WelcomeView(bot=mock_bot)

    # Act
    await view.admin_panel.callback(mock_interaction, MagicMock())

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_is_officer.assert_called_once_with(mock_interaction)
    mock_admin_cog._create_status_embed.assert_called_once_with(mock_interaction.guild.id)
    mock_interaction.followup.send.assert_called_once_with(embed="embed_content", ephemeral=True)

@patch('discord_bot.ui.views.is_officer', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_welcome_view_admin_button_as_non_officer(mock_is_officer, mock_bot, mock_interaction):
    """Tests the admin button for a non-officer."""
    # Arrange
    mock_is_officer.return_value = False
    view = WelcomeView(bot=mock_bot)

    # Act
    await view.admin_panel.callback(mock_interaction, MagicMock())

    # Assert
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_is_officer.assert_called_once_with(mock_interaction)
    mock_interaction.followup.send.assert_called_once_with("You must be an officer to use this.", ephemeral=True)
