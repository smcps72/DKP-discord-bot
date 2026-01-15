## How the bot decides which voice channels belong to “the raid”

A raid has a set of **linked voice channels**:

- **Primary voice channel (`raids.vc_id`)**
  - When you create a raid, the bot looks at the **raid leader’s current voice channel**.
  - If the leader is in voice at that moment, that channel becomes the raid’s initial linked VC.
- **Additional linked voice channels (`raid_voice_channels` table)**
  - The bot can store multiple linked VCs per raid.
  - You can add/remove them with:
    - `/raid_add_voice_channel`
    - `/raid_remove_voice_channel`
  - The “Update Team” button also links the **leader’s current voice channel** into the raid.

## What Sync Voice does when you press it

When you press **Sync Voice**:

- **[Adds members]** It scans all linked voice channels and **adds any non-bot users found there** into the raid roster (`raid_members`).
- **[Does not remove by default]** It **does not remove** people from the raid roster just because they’re not in voice (unless you use the slash command with removal enabled; see below).

So it’s “sync voice -> raid roster”, not “sync raid roster -> voice channels”.

## Your scenario: Raid Lobby vs General, “same raid”

If you are in **Raid Lobby** and someone else is in **General**, *and you’re talking about the same raid thread*:

### Case A: Only Raid Lobby is linked to the raid (most common)

- Pressing **Sync Voice** will:
  - **Add you** (and anyone else in Raid Lobby)
  - **Not add the person in General**
- Because General is **not a linked voice channel** for that raid.

### Case B: Both Raid Lobby and General are linked to the raid

- Pressing **Sync Voice** will:
  - **Add people from Raid Lobby**
  - **Add people from General**

In this case, “Sync Voice” effectively treats both channels as “raid voice”.

## Optional: “removing” people not in voice

There’s a slash command version:

- `/raid_sync_voice remove_missing:true confirm:true`

That one can also **remove raid members who are not currently in the linked voice channels** (it even does a safety preview if `confirm` isn’t set).

The **button** uses `remove_missing=False`, so it only adds.

## Practical takeaway / how to make General count

If you want people in **General** to be considered “in voice for this raid”, you need to **link General** to that raid first:

- **[Option 1]** `/raid_add_voice_channel` and pick the General VC
- **[Option 2]** Have the raid leader join General and click **Update Team** (this updates/links the leader’s current VC)
