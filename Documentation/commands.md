# Commands

This page is generated from the current bot code.

To regenerate it locally:

```bash
python3 scripts/generate_commands_docs.py
```

## Slash commands

| Command | Description | Source |
| --- | --- | --- |
| `/admin_adjust_dkp` | Manually adjust a member's DKP (admin only). | `discord_bot/cogs/admin_cog.py` |
| `/auction_help` | Explains how the auction system works. | `discord_bot/cogs/user_cog.py` |
| `/award` | Award DKP to a member or the entire raid. | `discord_bot/cogs/raid_cog.py` |
| `/debug_config` | Show DKP configuration for this server. | `discord_bot/cogs/admin_cog.py` |
| `/deduct` | Deduct DKP from a member or the entire raid. | `discord_bot/cogs/raid_cog.py` |
| `/export_all_threads` | Export all threads under a text channel to ZIPs in the backups folder. | `discord_bot/cogs/export_cog.py` |
| `/export_channel` | Export a text channel to a ZIP (Markdown + CSV + attachments). | `discord_bot/cogs/export_cog.py` |
| `/export_test` | Test command to verify export cog slash commands are synced. | `discord_bot/cogs/export_cog.py` |
| `/export_thread` | Export this thread to a ZIP (Markdown + CSV + attachments). | `discord_bot/cogs/export_cog.py` |
| `/history` | Downloads a CSV of the last 30 days of DKP transactions. | `discord_bot/cogs/admin_cog.py` |
| `/import_all_threads` | Bulk-import multiple thread exports from a ZIP-of-ZIPs or a backups timestamp. | `discord_bot/cogs/export_cog.py` |
| `/import_channel` | Import a text channel from an exported ZIP (replay messages and attachments). | `discord_bot/cogs/export_cog.py` |
| `/import_thread` | Import a thread from an exported ZIP (replay messages and attachments). | `discord_bot/cogs/export_cog.py` |
| `/list_backups` | Lists database backup IDs (timestamps) for this server. | `discord_bot/cogs/reset_cog.py` |
| `/list_members` | List members who participated in this raid log thread. | `discord_bot/cogs/admin_cog.py` |
| `/my_bid` | Check your bid in the active raid auction (if any). | `discord_bot/cogs/user_cog.py` |
| `/my_dkp` | Check your DKP balance. | `discord_bot/cogs/user_cog.py` |
| `/my_history` | View your recent DKP history. | `discord_bot/cogs/user_cog.py` |
| `/ping` | Simple connectivity check | `discord_bot/bot.py` |
| `/raid_add_member` | Admin only: add a member to the current raid without requiring them to be in the voice channel. | `discord_bot/cogs/raid_cog.py` |
| `/raid_add_voice_channel` | Link an additional voice channel to the current raid. | `discord_bot/cogs/raid_cog.py` |
| `/raid_clear_group` | Remove a raid member from any group. | `discord_bot/cogs/raid_cog.py` |
| `/raid_create` | Creates a new raid channel and control thread. | `discord_bot/cogs/raid_cog.py` |
| `/raid_end` | Ends and closes the current raid. | `discord_bot/cogs/raid_cog.py` |
| `/raid_list_voice_channels` | List voice channels linked to the current raid. | `discord_bot/cogs/raid_cog.py` |
| `/raid_points` | Show DKP for all members in the current raid. | `discord_bot/cogs/admin_cog.py` |
| `/raid_remove_member` | Remove a member from the current raid (prevents them from receiving raid DKP). | `discord_bot/cogs/raid_cog.py` |
| `/raid_remove_voice_channel` | Unlink a voice channel from the current raid. | `discord_bot/cogs/raid_cog.py` |
| `/raid_set_group` | Assign a raid member to a group number. | `discord_bot/cogs/raid_cog.py` |
| `/raid_status` | Show status of the current raid and any active auction. | `discord_bot/cogs/admin_cog.py` |
| `/raid_sync_voice` | Sync raid membership with linked voice channels. | `discord_bot/cogs/raid_cog.py` |
| `/reset` | Resets the DKP bot's configuration on this server. | `discord_bot/cogs/reset_cog.py` |
| `/restore_backup` | Restores the database from a backup ID (timestamp) for this server. | `discord_bot/cogs/reset_cog.py` |
| `/server_points` | Show DKP for all members in this server. | `discord_bot/cogs/admin_cog.py` |
| `/setup_dkp` | Manually (re)run the DKP system setup. Admins only. | `discord_bot/cogs/setup_cog.py` |
| `/status` | Check the bot's operational status. | `discord_bot/cogs/admin_cog.py` |

## Prefix commands

| Command | Description | Source |
| --- | --- | --- |
| `!debug_config` | Show DKP configuration for this server (prefix version). | `discord_bot/cogs/admin_cog.py` |
