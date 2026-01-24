## Raid panels (pop-up flow validation)

- Validate the new pop-up raid panel flow under real-world usage.

## Group-specific DKP awarding (validation)

- Validate group-specific awarding flow end-to-end.

- Previously-generated raid panels remain fully usable.
- A new pop-up raid panel has been introduced:
  - Supports in-place message editing for smoother updates.
  - Provides fallback messaging when interactions have already been responded to.
- Button flows now offer both “main” and “manage” modes for joining raids, adjusting DKP, and more.
- Pop-up actions now prefer updating the existing panel message (instead of sending extra ephemeral messages) for smoother UX.
- In progress: Further validation of the new pop-up flow is required.

## Timed DKP / hourly raid points

- Hourly DKP awards are now strictly **raid-specific**:
  - The timer starts when the raid begins and stops when it ends.
- If a participant leaves the linked voice channel(s) for more than **15 minutes**, they are automatically removed from the raid and must rejoin.
- Timed DKP can now be configured and stopped directly from the raid panel.

## Grouping + awarding DKP

- Raid leaders now have the ability to add members to a group.
- When syncing the team from voice, specific members can be excluded from auto-addition.
- Raid leaders and admins can remove a raider directly from the raid panel.
- Awarding DKP to all now supports exclusions:
  - Exclude an entire group or select specific members.
- Group-specific DKP awarding is supported. (Needs testing)

## Roster sorting

 - The default raid roster order is alphabetical.
 - A new option allows raid members to be listed in random order.

## /award UX

 - In the `/award` command, the label "everyone in VC" has been updated to "everyone in raid" for better clarity.

## New raid orphan management commands

 - Officers can now use **/raid_orphans** to list active raids whose raid log threads are missing.
 - The **/raid_orphan_cleanup** command lets officers force-close orphaned raids:
   - Choose between archiving (moving the raid log to completed raids) or deleting the thread.
   - This helps prevent stale raids from cluttering the system.

## Enhanced panel UX and interaction flow

 - Panel interactions now include improved error handling and context-sensitive messaging:
   - Delegated methods ensure that users receive immediate feedback.
   - Buttons support both public audit logs and ephemeral follow-up messages.

## Developer tooling & QA improvements

 - The environment loading process now auto-attempts to load from multiple .env file locations for increased robustness.
 - OpenAI chat payload configurations have been adjusted to better match model-specific requirements.
 - Local testing and QA have been ramped up:
   - New tests cover raid orphan commands, panel interactions, join/leave flows, and DKP adjustments.
   - Expanded regression tests help ensure consistency with voice roster syncing and DKP workflows.
