# DKP Bot Project

This project contains a fully functional Discord DKP Bot as specified.

## Features

- Automatic channel setup on server join.
- Raid creation with dedicated voice channels and text threads.
- Point awards and deductions for all members in a voice channel.
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
3.  **Configure Environment:**
    - Rename `.env.example` to `.env`.
    - Open the `.env` file and fill in the required values:
        - `DISCORD_BOT_TOKEN`: Your bot's token from the Discord Developer Portal.
        - `GUILD_LICENSE_KEY`: A secret key you create. This is what you'd "sell" to a guild.
        - `LICENSE_SERVER_URL`: The URL where your licensing server will be running. For local testing, this will be `http://127.0.0.1:5000`.

### 3. Running the Services

You need to run two services in separate terminals.

**Terminal 1: Start the Licensing Server**
```bash
cd licensing_server
python3 server.py
```
It should say it's running on http://127.0.0.1:5000.

**Terminal 2: Start the Discord Bot**
```bash
cd discord_bot
python3 bot.py
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
