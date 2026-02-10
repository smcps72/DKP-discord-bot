## Raid auto-join and auto-close

- Raiders now auto-join the raid when they enter a linked voice channel.
- Raids auto-close when the raid leader is absent from voice for 10+ minutes.

## Bulk group and DKP management

- Added bulk group assignment and voice-channel-based group assignment.
- Added multi-member DKP adjustments with member mentions in announcements (2000-char fallback).
- Excluded members are auto-included when updating team from voice.

## Timed DKP improvements

- Added configurable timed DKP interval with per-minute granularity.
- Timed DKP awards are now recorded in raid transaction history.
- Voice sync runs before timed DKP awards; added exclusion reasons and auto-rejoin logic.

## Raid panel and roster UX

- Show full roster after `update_team` command (ephemeral response).
- Show added member names in `update_team` command response.
- Reorganized raid popup button visibility and layout for main mode.
- Updated default DKP award modal placeholder text and recommendation to 6 DKP per 1 minute.

## Admin tooling

- Added `backfill_raid_dkp` command to populate missing raid transaction records.
- Added source parameter to DKP adjustment modals for award and deduct commands.

## E2E and developer workflow

- Added feature-complete-testing Playwright workflow and pre-push hook for E2E verification.
- Added multi-select DKP adjustment and Groups view E2E tests.
