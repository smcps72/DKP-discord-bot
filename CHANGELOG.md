# Changelog

All notable changes to this project will be documented in this file.

## 0.1.0-alpha.6

- Added Guild Bank feature: deposit, withdraw, searchable inventory channel, and transaction log channel with auto-sync.
- Added held-by member selector (UserSelect with autocomplete) on deposit; simplified deposit modal.
- Added dedicated Guild Bank inventory and transactions channels; deposit/withdraw success messages are public.
- Reuse deleted item IDs to maintain compact slot numbering in the inventory.
- Added guild bank cleanup to the reset command.
- Added public audit message for raid DKP reversals (reason truncated to 200 chars).
- Reduced member absence threshold for auto-close from 15 to 5 minutes.
- Officers can now create raids (previously admin-only); exclusion entries now include a reason column.

## 0.1.0-alpha.5

- Added raid auto-join from voice and auto-close when raid leader absent 5+ minutes.
- Added bulk group assignment, voice-channel group assignment, and multi-member DKP adjustments with member mentions.
- Added configurable timed DKP interval with per-minute granularity; timed DKP awards now recorded in raid transaction history.
- Added exclusion reasons and auto-rejoin logic with voice sync before timed DKP awards.
- Added `backfill_raid_dkp` command to populate missing raid transaction records.
- Added source parameter to DKP adjustment modals for award and deduct commands.
- Improved raid panel and roster UX: full roster display, added member names, reorganized button layout.
- Updated default DKP award modal placeholder and recommendation to 6 DKP per 1 minute.
- Added feature-complete-testing Playwright workflow and multi-select E2E tests.
- Improved security-scan cross-platform support and command execution safety.

## 0.1.0-alpha.4

- Added bot profile selection UI for switching between bot instances (local dev).
- Added admin-configurable default timed DKP amount (was hardcoded to 5, now defaults to 10).
- Added current DKP total to raid award/deduct DM notifications.
- Improved raid panel layout: reorganized button rows for better manage mode UX.
- Improved raid panel close button visibility and labeling.
- Enforced raider role eligibility across all raid operations (join, sync, award).
- Improved group management and raid points display consolidation.
- Improved E2E test reliability for Discord channel navigation.

## 0.1.0-alpha.3

- Added raid team grouping plus group setup + signup UI.
- Officers now see and can use the **Create Raid** button; role checks refined for sensitive raid actions.
- Added timed DKP (hourly raid points) scoped to a raid, with auto-removal after 15 minutes out of linked voice.
- Added raid team tooling: exclusions when syncing from voice / awarding DKP, group-specific awarding.
- Added roster sorting options (alphabetical by default, optional random order).
- Added orphan raid management commands: `/raid_orphans` and `/raid_orphan_cleanup`.
- Improved panel UX and error handling; expanded regression and E2E coverage.
- Fixed raid control panel interaction issues and reduced redundant setup prompts.
- Improved `/status` diagnostics while hiding environment identity from non-admin users.
- Isolated deployment sqlite per environment/service.
- Improved E2E coverage for /status output and raid UI.

## 0.1.0-alpha.2

- Added an **Open DKP Panel** button which opens a per-user **ephemeral** panel for common actions.
- Added an in-bot docs viewer backed by `Documentation/*.md` (admin-only).
- Added optional PostHog analytics instrumentation (disabled unless `POSTHOG_API_KEY` is set).
- Added staging Playwright smoke tests for the changelog UI and improved CI reporting.
- Added guidance for linked raid voice channels and "Sync Voice" behavior.

## 0.1.0-alpha.1

- Added a Change Log button to the welcome panel with an ephemeral changelog viewer.
- Added version selection for changelog entries (dropdown) and improved rendering via embeds.
- Added permission gating for "Unreleased" changelog entries (officers/admins only).
- Added file-backed changelog parsing with caching (reads from repo-root CHANGELOG.md).
- Added automated versioning and release PR creation via release-please.
- Added repo-tracked version file (discord_bot/VERSION) and updated bot version resolution to read it by default.
- Bug fixes and small improvements.

## 0.1.0-alpha.0

- Initial alpha release.
