# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- No unreleased notes yet.

## 0.1.0-alpha.3

- Added raid team grouping plus group setup + signup UI.
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
