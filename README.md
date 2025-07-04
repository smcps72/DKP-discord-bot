# DKP Bot Project

This project contains a fully functional Discord DKP Bot as specified.

## Features

- Automatic channel setup on server join.
- Raid creation with dedicated voice channels and text threads.
- Point awards and deductions for all members in a voice channel.
- Optional single-member DKP awards via slash command or raid control panel.
- A complete, private auction system.
- Subscription-based activation checked against a simple licensing server.
- Slash commands and buttons for all major actions.
- Administrative commands for status checks and history export.

## How to Run

### 1. Prerequisites

- Python 3.10 or newer
- A Discord Bot Application and Token (see [Discord Developer Portal](https://discord.com/developers/applications))
    - Enable **Privileged Gateway Intents**:
        - `SERVER MEMBERS INTENT`
        - `MESSAGE CONTENT INTENT`
        - `PRESENCE INTENT` (sometimes helpful, but Members and Voice States are key)
    - Enable **Voice States Intent** implicitly by using voice features.

### 2. Installation

1.  **Clone/Download:** Get all the files into a folder on your server.
2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  ### 3. Configure Environment:

    - Create a copy of `.env.example` and rename it to `.env.local`.
    - Open the `.env.local` file and fill in the required values.
    - The bot is configured to automatically load this file, keeping your secrets safe.

    **Required Variables:**

    - `DISCORD_BOT_TOKEN`: Your bot's token from the Discord Developer Portal.

    **License Check (Optional):**

    - `LICENSE_CHECK_ENABLED`: Set to `false` to disable the license check for local testing. Defaults to `true`.
    - `GUILD_LICENSE_KEY`: Required if license checks are enabled.
    - `LICENSE_SERVER_URL`: Required if license checks are enabled. For local testing, use `http://127.0.0.1:5000`.

## Adding the Bot to Your Server

To invite the bot to your Discord server, use the following link:

[Add DKP Bot to your server](https://discord.com/oauth2/authorize?client_id=1383638451508871270&scope=bot+applications.commands&permissions=8)

### 3. Running the Bot

**Running with the Licensing Server:**

If you have `LICENSE_CHECK_ENABLED` set to `true` (or omitted), you need to run two services in separate terminals.

**Terminal 1: Start the Licensing Server**
```bash
cd licensing_server
python server.py
```
It should say it's running on `http://127.0.0.1:5000`.

**Terminal 2: Start the Discord Bot**
```bash
cd discord_bot
python bot.py
```

**Running in Offline Mode (No Licensing Server):**

If you have `LICENSE_CHECK_ENABLED` set to `false` in your `.env.local` file, you only need to start the bot.

**Terminal 1: Start the Discord Bot**
```bash
cd discord_bot
python bot.py
```

### 4. Inviting the Bot
- Go to your Bot's page in the Discord Developer Portal.
- Go to OAuth2 -> URL Generator.
- Select the bot and applications.commands scopes.
- Under "Bot Permissions", grant the following:
    - Manage Channels
    - Manage Roles (for officer checks)
    - Manage Messages
    - Read Message History
    - Send Messages
    - Send Messages in Threads
    - Create Public Threads
    - Embed Links
    - Attach Files
    - Connect
    - Speak
    - Move Members
- Copy the generated URL and paste it into your browser to invite the bot to your server.

Once invited, the bot will automatically set up its channels. The Admin ⚙️ button will only be visible to server administrators by default.

### Awarding DKP

- Use `/award_dkp <member> <points> [reason]` to grant DKP to a single user.
- The "Award DKP" button in a raid thread now includes a field for an optional target member. Leave it blank to adjust everyone in the raid voice channel.
