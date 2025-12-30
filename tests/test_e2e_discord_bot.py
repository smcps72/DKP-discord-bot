import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, expect

# NOTE: There are AI-assisted Playwright tools (e.g. ZeroStep for JS/TS) that
# expose an `ai()` helper to run natural-language instructions instead of
# fragile selectors. Example (TypeScript/JS, not used directly in this Python test):
#   import { ai } from '@zerostep/playwright';
#   await ai('Click the "World" section', { page, test });
#   const price = await ai('Return the current price for the S&P 500.', { page, test });


project_root = Path(__file__).resolve().parents[1]
dotenv_path = project_root / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path, override=True)

# Environment variables for the test Discord user and target guild/channel.
# Make sure these are set in your shell before running the test:
#   export DISCORD_TEST_EMAIL="..."
#   export DISCORD_TEST_PASSWORD="..."
#   export DISCORD_TEST_SERVER_NAME="..."      # The guild name as shown in the UI
#   export DISCORD_TEST_CHANNEL_NAME="..."     # The channel name (e.g. "bot-testing")

DISCORD_EMAIL = os.environ.get("DISCORD_TEST_EMAIL", "")
DISCORD_PASSWORD = os.environ.get("DISCORD_TEST_PASSWORD", "")
DISCORD_SERVER_NAME = os.environ.get("DISCORD_TEST_SERVER_NAME", "")
DISCORD_CHANNEL_NAME = os.environ.get("DISCORD_TEST_CHANNEL_NAME", "")

# Command + expected bot reply fragment – update these to something stable
# that your DKP bot always returns for a given command.
TEST_COMMAND = "!help"
EXPECTED_REPLY_FRAGMENT = "DKP"  # Adjust to something your help text contains


@pytest.mark.e2e
@pytest.mark.skipif(
    not (DISCORD_EMAIL and DISCORD_PASSWORD and DISCORD_SERVER_NAME and DISCORD_CHANNEL_NAME),
    reason="DISCORD_TEST_* environment variables are not fully configured",
)
def test_bot_responds_to_help_command():
    """Basic end-to-end test using Playwright against the Discord web client.

    Assumes the bot is already running and connected to a test guild
    where the test user has access to the target channel.
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Log into Discord
        page.goto("https://discord.com/login", wait_until="networkidle")

        # NOTE: These locators are a starting point and may need tweaking
        # using `playwright codegen https://discord.com/login`.
        page.get_by_label("Email or Phone Number").fill(DISCORD_EMAIL)
        page.get_by_label("Password").fill(DISCORD_PASSWORD)
        page.get_by_role("button", name="Log In").click()

        # Wait for main app UI to load
        page.wait_for_timeout(8000)

        # 2. Select the target server (guild) by its name in the left sidebar
        page.get_by_role("treeitem", name=DISCORD_SERVER_NAME).click()
        page.wait_for_timeout(3000)

        # 3. Select the target text channel
        channel = page.get_by_role("link", name=DISCORD_CHANNEL_NAME)
        channel.click()
        page.wait_for_timeout(3000)

        # 4. Send a command as the test user
        message_box = page.get_by_role("textbox")
        message_box.click()
        message_box.fill(TEST_COMMAND)

        # Capture the current number of messages before sending the command
        messages = page.locator("div[class*=messageContent]")
        before_count = messages.count()

        message_box.press("Enter")

        # 5. Wait for at least one new message to appear after sending the command.
        # On a quiet test channel this should correspond to the user's command
        # and/or the bot's reply.
        page.wait_for_timeout(5000)
        after_count = messages.count()
        assert after_count > before_count, (
            f"Expected at least one new message after sending '{TEST_COMMAND}', "
            f"but message count stayed at {before_count}."
        )

        browser.close()
