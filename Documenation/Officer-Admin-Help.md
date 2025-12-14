# Officer / Admin Help – DKP Bot

## Roles

- **Officers** – pass the `is_officer` check (configured role).
- **Admins** – Discord “Administrator” permission.

---

## Raid Management

- **`/raid_create`** *(Officer/Admin)*  
  - Creates raid voice channel.  
  - Creates raid log thread.  
  - Assigns/configures Raid-Leader role.

- **`/raid_end`** *(Officer/Admin)*  
  - Marks raid inactive in DB.  
  - Moves members out / deletes raid VC.  
  - Removes Raid-Leader role.  
  - Locks and archives raid thread.

- **`/award`** *(Officer)*  
  - Award DKP to:
    - A specific member (if selected), or  
    - Everyone in the raid VC (if left blank).  
  - Amount and reason via popup modal.

- **`/deduct`** *(Officer)*  
  - Same targeting rules as `/award`, but deducts points.  
  - Amount and reason via popup modal.

- **`/raid_points`** *(Admin, use in raid thread)*  
  - Reads the raid VC members.  
  - Shows an embed listing each raider and their DKP, highest first.

---

## Setup & Status

- **`/setup_dkp`** *(Admin)*  
  - Initial or repair setup: creates DKP category, channels, and Officer/Raider/Raid-Leader roles.

- **`/status`** *(Admin)*  
  - Shows latency, license/subscription status, and number of active raids.

- **`/debug_config`** *(Admin)*  
  - Displays current DKP configuration (channels, roles, defaults, etc.).

- **`!debug_config`** *(Admin, prefix)*  
  - Same info as `/debug_config`, but with `!` prefix.

- **`/list_members`** *(Admin)*  
  - Debug: list all members from guild cache.

- **`/list_members_full`** *(Admin)*  
  - Debug: list all members using `fetch_members` (API).

---

## Export / Import (Logs & Channels)

All of these are **Admin-only**, for backups/migrations.

- **`/export_thread`** – Export one thread to ZIP (markdown, CSV, attachments).  
- **`/export_all_threads`** – Export all threads under a text channel into per-thread ZIPs (+ optional aggregate ZIP).  
- **`/export_channel`** – Export full text channel history to ZIP.  
- **`/export_test`** – Simple sanity check that export commands work.  
- **`/import_thread`** – Replay a thread from a ZIP created by `/export_thread`.  
- **`/import_channel`** – Replay a channel from a ZIP created by `/export_channel`.  
- **`/import_all_threads`** – Bulk-import multiple thread exports (ZIP-of-ZIPs or by `backup_id`).

---

## Resets & Backups (Danger Zone)

**Destructive – Admins only.**

- **`/reset`**  
  - Backs up DB, exports raid threads, deletes DKP channels/roles, and wipes DKP data for this guild.

- **`/list_backups`**  
  - Shows available DB backup IDs (timestamps).

- **`/restore_backup`**  
  - Restores DB from backup ID (requires `confirm: true`).  
  - Attempts to rerun setup and replay saved raid logs.
