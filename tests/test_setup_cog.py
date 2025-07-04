import pytest
import discord
from discord.ext import commands
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.cogs.setup_cog import SetupCog
from discord_bot.ui.views import WelcomeView # Needed for type checking if WelcomeView is asserted

# Basic scaffolding for the test file
@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=commands.Bot)
    bot.db = AsyncMock()
    bot.license_key = "test_license_key"
    return bot

@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 12345
    guild.name = "Test Guild"
    guild.default_role = MagicMock(spec=discord.Role)
    guild.owner = AsyncMock(spec=discord.Member) # owner.send is async

    # Mock channel creation methods to return AsyncMocks
    guild.create_category = AsyncMock(spec=discord.CategoryChannel)
    # Mock the created category to have its own channel creation methods
    mock_category = AsyncMock(spec=discord.CategoryChannel)
    mock_category.id = 67890
    mock_category.create_text_channel = AsyncMock(spec=discord.TextChannel)
    mock_category.create_voice_channel = AsyncMock(spec=discord.VoiceChannel)
    guild.create_category.return_value = mock_category

    # Mock created channels to have basic attributes like id
    mock_text_channel = AsyncMock(spec=discord.TextChannel)
    mock_text_channel.id = 111
    mock_text_channel.send = AsyncMock(spec=discord.Message) # For sending welcome message
    mock_text_channel.send.return_value.pin = AsyncMock() # For pinning the message
    mock_category.create_text_channel.return_value = mock_text_channel

    mock_voice_channel = AsyncMock(spec=discord.VoiceChannel)
    mock_voice_channel.id = 222
    mock_category.create_voice_channel.return_value = mock_voice_channel

    return guild

@pytest.fixture
def mock_interaction():
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild) # Will be replaced by mock_guild in tests
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    interaction.followup = AsyncMock(spec=discord.Webhook)
    return interaction

@pytest.fixture
def setup_cog(mock_bot):
    return SetupCog(mock_bot)

# Example of a test structure (will be filled in later)
@pytest.mark.asyncio
async def test_run_setup_fresh_guild(setup_cog: SetupCog, mock_bot: MagicMock, mock_guild: MagicMock, mock_interaction: AsyncMock):
    # --- Arrange ---
    # Guild is mock_guild from fixture
    mock_interaction.guild = mock_guild

    # Ensure get_guild_config returns None (or no dkp_category_id) for fresh setup
    mock_bot.db.get_guild_config = AsyncMock(return_value=None)

    # Get the mock category and channels that are supposed to be created
    mock_category = mock_guild.create_category.return_value
    mock_dkp_channel = mock_category.create_text_channel.return_value # This will be the same mock for both text channels by default
    mock_raid_channel = AsyncMock(spec=discord.TextChannel) # Create a new one for the second call
    mock_raid_channel.id = 333
    mock_vc_template = mock_category.create_voice_channel.return_value

    # Ensure create_text_channel returns dkp_channel then raid_channel
    mock_category.create_text_channel.side_effect = [mock_dkp_channel, mock_raid_channel]

    # --- Act ---
    await setup_cog.run_setup(mock_guild, mock_interaction)

    # --- Assert ---
    # 1. Check if config was fetched
    mock_bot.db.get_guild_config.assert_called_once_with(mock_guild.id)

    # 2. Verify category creation
    mock_guild.create_category.assert_called_once()
    args, kwargs = mock_guild.create_category.call_args
    assert args[0] == "DKP-System"
    assert mock_guild.default_role in kwargs["overwrites"]
    overwrite = kwargs["overwrites"][mock_guild.default_role]
    assert overwrite.read_messages is True
    assert overwrite.send_messages is False

    # 3. Verify text channel creation
    expected_dkp_channel_name = "dkp-system"
    expected_raid_channel_name = "active-raids"

    calls = mock_category.create_text_channel.call_args_list
    assert len(calls) == 2
    calls[0].assert_called_with(expected_dkp_channel_name)
    calls[1].assert_called_with(expected_raid_channel_name)

    # 4. Verify voice channel template creation
    mock_category.create_voice_channel.assert_called_once()
    args_vc, kwargs_vc = mock_category.create_voice_channel.call_args
    assert args_vc[0] == "Raid-Template"
    assert mock_guild.default_role in kwargs_vc["overwrites"]
    overwrite_vc = kwargs_vc["overwrites"][mock_guild.default_role]
    assert overwrite_vc.view_channel is False
    # Check other permissions are not set / default if necessary
    assert overwrite_vc.read_messages is None

    # 5. Verify database execute call
    mock_bot.db.execute.assert_called_once_with(
        "INSERT OR REPLACE INTO guilds (guild_id, dkp_category_id, dkp_channel_id, raid_channel_id, raid_vc_template_id, license_key) VALUES (?, ?, ?, ?, ?, ?)",
        (mock_guild.id, mock_category.id, mock_dkp_channel.id, mock_raid_channel.id, mock_vc_template.id, mock_bot.license_key)
    )

    # 6. Verify welcome message sent to dkp_channel and pinned
    mock_dkp_channel.send.assert_called_once()
    args, kwargs = mock_dkp_channel.send.call_args
    assert "embed" in kwargs
    assert isinstance(kwargs["view"], WelcomeView)

    mock_dkp_channel.send.return_value.pin.assert_called_once()

    # 7. Verify interaction followup
    mock_interaction.followup.send.assert_called_once_with("DKP system setup complete!", ephemeral=True)

@pytest.mark.asyncio
async def test_run_setup_already_configured(setup_cog: SetupCog, mock_bot: MagicMock, mock_guild: MagicMock, mock_interaction: AsyncMock):
    # --- Arrange ---
    mock_interaction.guild = mock_guild

    # Simulate existing config
    existing_config = {'dkp_category_id': 98765}
    mock_bot.db.get_guild_config = AsyncMock(return_value=existing_config)

    # --- Act ---
    await setup_cog.run_setup(mock_guild, mock_interaction)

    # --- Assert ---
    # 1. Check if config was fetched
    mock_bot.db.get_guild_config.assert_called_once_with(mock_guild.id)

    # 2. Verify no channel/category creation methods were called
    mock_guild.create_category.assert_not_called()

    # Get the mock category from fixture to check its methods
    mock_category_fixture = mock_guild.create_category.return_value
    mock_category_fixture.create_text_channel.assert_not_called()
    mock_category_fixture.create_voice_channel.assert_not_called()

    # 3. Verify db.execute was not called to save config
    mock_bot.db.execute.assert_not_called()

    # 4. Verify "already set up" message
    mock_interaction.followup.send.assert_called_once_with(
        f"Setup already exists for {mock_guild.name}.", ephemeral=True
    )

    # 5. Verify no welcome message was sent or pinned
    mock_dkp_channel = mock_category_fixture.create_text_channel.return_value
    mock_dkp_channel.send.assert_not_called()
    mock_dkp_channel.send.return_value.pin.assert_not_called()

@pytest.mark.asyncio
async def test_run_setup_discord_forbidden_error(setup_cog: SetupCog, mock_bot: MagicMock, mock_guild: MagicMock, mock_interaction: AsyncMock):
    # --- Arrange ---
    mock_interaction.guild = mock_guild
    mock_bot.db.get_guild_config = AsyncMock(return_value=None) # Fresh setup

    # Simulate discord.Forbidden when creating category
    mock_guild.create_category = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Missing permissions"))

    # --- Act ---
    await setup_cog.run_setup(mock_guild, mock_interaction)

    # --- Assert ---
    # 1. Check if config was fetched
    mock_bot.db.get_guild_config.assert_called_once_with(mock_guild.id)

    # 2. Verify category creation was attempted
    mock_guild.create_category.assert_called_once() # It was called, but raised an error

    # 3. Verify owner was DMed
    mock_guild.owner.send.assert_called_once_with(
        "I tried to set up my channels in your server but I'm missing the 'Manage Channels' permission. Please grant it and re-invite me."
    )

    # 4. Verify interaction followup with error message
    mock_interaction.followup.send.assert_called_once_with(
        "Missing permissions to set up channels. Please grant 'Manage Channels' and try again.", ephemeral=True
    )

    # 5. Verify no DB execute call was made
    mock_bot.db.execute.assert_not_called()

    # 6. Verify no welcome message was sent or pinned (as setup failed early)
    mock_category_fixture = mock_guild.create_category.return_value # This won't be the one from side_effect
    dkp_channel_mock_from_fixture = mock_category_fixture.create_text_channel.return_value
    dkp_channel_mock_from_fixture.send.assert_not_called()
    dkp_channel_mock_from_fixture.send.return_value.pin.assert_not_called()

@pytest.mark.asyncio
async def test_run_setup_discord_forbidden_owner_dm_fails(setup_cog: SetupCog, mock_bot: MagicMock, mock_guild: MagicMock, mock_interaction: AsyncMock):
    # --- Arrange ---
    mock_interaction.guild = mock_guild
    mock_bot.db.get_guild_config = AsyncMock(return_value=None) # Fresh setup

    mock_guild.create_category = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Missing permissions"))
    mock_guild.owner.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Cannot DM owner")) # Simulate owner DM also failing

    # --- Act ---
    await setup_cog.run_setup(mock_guild, mock_interaction)

    # --- Assert ---
    mock_bot.db.get_guild_config.assert_called_once_with(mock_guild.id)
    mock_guild.create_category.assert_called_once()
    mock_guild.owner.send.assert_called_once() # Attempted
    mock_interaction.followup.send.assert_called_once_with(
        "Missing permissions to set up channels. Please grant 'Manage Channels' and try again.", ephemeral=True
    )
    mock_bot.db.execute.assert_not_called()

@pytest.mark.asyncio
async def test_on_guild_join(setup_cog: SetupCog, mock_guild: MagicMock, mock_bot: MagicMock):
    # --- Arrange ---
    # We want to check if run_setup is called. We can mock it on the instance.
    setup_cog.run_setup = AsyncMock()

    # --- Act ---
    await setup_cog.on_guild_join(mock_guild)

    # --- Assert ---
    setup_cog.run_setup.assert_called_once_with(mock_guild)

@pytest.mark.asyncio
async def test_setup_dkp_command(setup_cog: SetupCog, mock_interaction: AsyncMock, mock_guild: MagicMock):
    # --- Arrange ---
    mock_interaction.guild = mock_guild # Assign the mock_guild to the interaction

    # Mock run_setup on the cog instance for this test
    setup_cog.run_setup = AsyncMock()

    # --- Act ---
    # For app commands, we need to call the callback method directly
    await setup_cog.setup_dkp.callback(setup_cog, mock_interaction)

    # --- Assert ---
    # 1. Verify interaction.response.defer was called
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)

    # 2. Verify run_setup was called correctly
    setup_cog.run_setup.assert_called_once_with(mock_guild, interaction=mock_interaction)
