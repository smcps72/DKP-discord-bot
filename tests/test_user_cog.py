import pytest
from discord.ext import commands
from unittest.mock import AsyncMock, MagicMock

from discord_bot.cogs.user_cog import UserCog
from discord_bot.utils import create_info_embed

@pytest.fixture
def bot():
    bot_mock = AsyncMock(spec=commands.Bot)
    bot_mock.db = AsyncMock()
    return bot_mock

@pytest.fixture
def user_cog(bot):
    return UserCog(bot)

class MockGuild:
    def __init__(self, id):
        self.id = id

class MockUser:
    def __init__(self, id):
        self.id = id

class MockInteraction:
    def __init__(self, user_id, guild_id):
        self.user = MockUser(user_id)
        self.guild = MockGuild(guild_id)
        self.followup = AsyncMock()

# Tests will be added here

@pytest.mark.asyncio
async def test_my_dkp_cmd(user_cog, bot):
    mock_interaction = MockInteraction(user_id=123, guild_id=456)
    expected_dkp = 100
    bot.db.get_user_dkp.return_value = expected_dkp

    await user_cog.my_dkp_cmd.callback(user_cog, mock_interaction)

    bot.db.get_user_dkp.assert_called_once_with(123, 456)

    expected_embed = create_info_embed(
        f"💰 Your DKP Balance",
        f"You currently have **{expected_dkp}** DKP."
    )

    args, kwargs = mock_interaction.followup.send.call_args
    assert kwargs['embed'].title == expected_embed.title
    assert kwargs['embed'].description == expected_embed.description
    assert kwargs['ephemeral'] is True

@pytest.mark.asyncio
async def test_auction_help_cmd(user_cog):
    mock_interaction = MockInteraction(user_id=123, guild_id=456)

    await user_cog.auction_help_cmd.callback(user_cog, mock_interaction)

    help_text = (
        "1. **Starting:** The Raid Leader starts an auction for an item.\n"
        "2. **Bidding:** You will receive a private message (or a hidden message in the raid thread) to bid.\n"
        "3. **Placing Bids:** Click 'Bid', enter your amount, and submit. You must have enough DKP.\n"
        "4. **Outbidding:** If someone bids higher, you'll be notified (if your DMs are open).\n"
        "5. **Winning:** The Raid Leader ends the auction. The highest bidder wins and the DKP is automatically deducted."
    )
    expected_embed = create_info_embed("❓ Auction Help", help_text)

    args, kwargs = mock_interaction.followup.send.call_args
    assert kwargs['embed'].title == expected_embed.title
    assert kwargs['embed'].description == expected_embed.description
    assert kwargs['ephemeral'] is True
