# What the bot can see and store

## What it sees

It uses the official Discord API.

It can see basic server information it needs to work:

- Server (guild) IDs  
- User IDs and roles  
- Who is in specific voice channels  
- Some message content where needed for bot commands  

## What it stores

It keeps a local database with:

- DKP points for users  
- Raid participation and auction records  
- Configuration for each server (which channels/roles to use, etc.)

It does **not** store passwords or similar highly sensitive personal data.

## Who can do what (permissions & roles)

Built on Discord’s own permission system.

Important commands (setup, configuration, history export, status, etc.) are restricted to:

- Server administrators, or  
- Specific “officer” roles that you configure.

## Extra safety checks

The bot has its own helper checks that verify:

- The user really is a member of the server.  
- The user has the right admin/officer role before running powerful commands.

## Private responses where appropriate

Sensitive information (like status checks and history exports) is often sent as ephemeral messages:

- Only the person who ran the command can see the response in Discord.

## How secrets and connections are handled

**Bot token and keys are not hard-coded**

- The Discord bot token is read from environment variables (configuration outside the code).  
- This avoids putting secrets directly in the source code.

## Startup safety checks

- If the bot token is missing, the bot refuses to start instead of running in a broken or unsafe state.  

## Database safety basics

- All database operations use a safe pattern so user input is not directly mixed into database commands.  
- This avoids a common class of security problems where attackers try to “inject” commands into the database.


## Security hardening & automated checks

- **Code-level hardening**  
  The bot applies several defensive measures in the code itself, including strict role/permission checks for admin and raid actions, a guild allowlist driven by the `ALLOWED_GUILD_IDS` environment variable, input validation and length limits (for DKP reasons, raid names, auction item names, and rules), and cooldowns on heavier commands like DKP history exports to reduce abuse.

- **Static analysis with Bandit**  
  Bandit scans the Python source code for common security issues (unsafe function usage, insecure subprocess calls, etc.). This project includes a helper script, which runs Bandit against the `discord_bot` package and writes a machine-readable report to `bandit-report.json`. From the project root you can run:


- **Dependency vulnerability scan with pip-audit**  
  In addition to code analysis, the same script runs `pip-audit` to check installed dependencies for known vulnerabilities and writes results to `audit-report.json`. You can also invoke it manually:


  These scans are run before each commit so that new issues are caught before they are deployed.


## Reliability and error handling

**Graceful error messages**

- When something goes wrong, the bot logs the technical details internally.  
- Users in Discord only see a simple, generic error message; it does not reveal internal information.



