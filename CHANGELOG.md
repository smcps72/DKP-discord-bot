# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- Validate the new pop-up raid panel flow under real-world usage.
- Validate group-specific awarding flow end-to-end.

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
