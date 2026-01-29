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
 - Immutable raid log snapshots with hash-based tamper detection and verification.

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
    - The bot is configured to automatically load `secrets/.env.local` (if present), then `.env.local`, then `.env`.
    - For storing secrets in git safely, consider using **git-crypt** (encrypts selected files transparently) or **gocryptfs** (encrypted backing dir + decrypted mountpoint).

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

### Live Auction Logging (Optional)

While the bot is running, you can follow the new structured auction logs (tagged with `auction_flow`) to debug button and bidding issues in real time.

If you are logging to a file (recommended in production), for example `logs/dkp-bot.log`:

```bash
tail -F logs/dkp-bot.log | grep --line-buffered "auction_flow"
```

To focus on a specific user (replace `123456789` with their Discord user ID):

```bash
tail -F logs/dkp-bot.log \
  | grep --line-buffered "auction_flow" \
  | grep --line-buffered "user_id=123456789"
```

If you run the bot directly in a terminal without a log file, you can pipe output through `grep`:

```bash
python bot.py 2>&1 | grep --line-buffered "auction_flow"
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

### Immutable Raid Logs and Verification

- When a raid is closed via the control panel, the bot records a **canonical JSON snapshot** of the raid into the database.
- This snapshot includes raid metadata, participants, and their DKP at the time of closure.
- A **SHA-256 hash** of this JSON is stored alongside the snapshot. This allows you to detect any tampering with the stored data.
- Administrators can run `/raid_verify` inside a raid's log thread to recompute the hash and confirm that the stored JSON has not been altered.
  - If the hashes match, the command returns an "OK" result.
  - If they do not match, the command reports a **mismatch** along with both hashes.

### Optional External Anchoring (Advanced)

The bot can optionally call out to external services to anchor raid logs beyond the local database:

- **IPFS / Storage Service**: The full JSON snapshot and hash can be POSTed to an HTTP endpoint that you control. That service can pin the data to IPFS or any other storage layer.
- **EVM / Blockchain Service**: The hash can be POSTed to a separate HTTP endpoint that writes it on-chain (e.g., via a smart contract) and returns a transaction hash.

These integrations are fully disabled by default. To enable them, configure the following environment variables (see `.env.example`):

- `RAIDLOG_IPFS_ENABLED` / `RAIDLOG_IPFS_ENDPOINT` / `RAIDLOG_IPFS_AUTH_HEADER`
- `RAIDLOG_EVM_ENABLED` / `RAIDLOG_EVM_ENDPOINT`

If the endpoints are unreachable or return errors, raid closure and local logging will still succeed; the bot simply logs a warning.

## Security

### Checklist

- **Bot Permissions**: Grant only the permissions listed in the "Inviting the Bot" section. Avoid granting `Administrator`.
- **Environment Variables**: Never commit `.env.local` with real tokens. Use `.env.example` as a template.
- **Dependency Updates**: Run `pip-audit` regularly to check for known vulnerabilities.
- **Static Analysis**: Run `bandit` to catch common security issues in the code.

### Running Security Scans

A convenience script is provided to run both `bandit` (static analysis) and `pip-audit` (dependency vulnerability scan):

```bash
python security-scan.py
```

This will generate:
- `bandit-report.json` (static analysis report)
- `audit-report.json` (dependency vulnerability report)

You can also run the tools manually:
```bash
# Static analysis
python -m bandit -r discord_bot -f json -o bandit-report.json

# Dependency vulnerability scan
python -m pip_audit --format json --output audit-report.json
```

**Note:** Pre-commit hooks are not supported on Windows with Git. Run `python security-scan.py` manually before commits, or use `git commit --no-verify` to bypass if needed (not recommended).

### Least Privilege Guidance

- **Roles**: The bot creates `Officer`, `Raider`, and `Raid-Leader` roles. Only assign `Officer` to trusted users.
- **Channels**: The bot creates channels under a `DKP-System` category with read-only permissions for the default role.
- **Commands**: Sensitive commands (`/setup_dkp`, `/reset_dkp`) are restricted to users with `Administrator` permission or the `Officer` role.

## User Documentation Site (MkDocs)

The repo includes an end-user documentation site powered by MkDocs (Material theme). The docs source files live in `Documentation/`.

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements-docs.txt
python3 scripts/generate_commands_docs.py
python -m mkdocs serve
```
