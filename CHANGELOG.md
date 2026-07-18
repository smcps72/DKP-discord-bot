# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0-alpha.5](https://github.com/smcps72/DKP-discord-bot/compare/v0.1.0-alpha.4...v0.1.0-alpha.5) (2026-07-18)


### Features

* **admin:** add backfill_raid_dkp command to populate missing raid transaction records ([8f427c4](https://github.com/smcps72/DKP-discord-bot/commit/8f427c4c5f528f1682334d569dfa3c54aaa52968))
* **admin:** add ephemeral parameter to server_points command and replace My DKP with Raid Points for raid leaders ([8b207c9](https://github.com/smcps72/DKP-discord-bot/commit/8b207c9aef3a63b30c8d079ca4f0ec254ad76044))
* **auction:** add AuctionManagePanelView response when starting auctions from auction panel ([acc7c26](https://github.com/smcps72/DKP-discord-bot/commit/acc7c26b80b091b24ba627d77c05eb0c8ff16d7e))
* **auction:** add automatic guild bank withdrawal when auction ends with winner ([f9d313f](https://github.com/smcps72/DKP-discord-bot/commit/f9d313f32e683887b9f858dfed2f5906ad5c3113))
* **auction:** add standalone guild-wide auctions independent of raids ([abfa0ac](https://github.com/smcps72/DKP-discord-bot/commit/abfa0aca20a031bf7512b812ef3b1b38bd50698e))
* **auction:** add standalone guild-wide auctions with dedicated active-auctions channel and combined DKP/Auction panel ([12d598e](https://github.com/smcps72/DKP-discord-bot/commit/12d598e73977ccbbe7647d8ca91b5cbebdd1cc34))
* **changelog:** clarify default timed DKP rate as "10/hour" instead of "10" ([961c400](https://github.com/smcps72/DKP-discord-bot/commit/961c40043ec19f2437a40279178e7e427338e046))
* **database:** add username column to users table and backfill display names across DKP operations ([78b9aaa](https://github.com/smcps72/DKP-discord-bot/commit/78b9aaa2dd1cbf7bd4bcdc97083b9d0fb6862f02))
* **dkp:** add configurable timed DKP interval with per-minute granularity ([37eb38e](https://github.com/smcps72/DKP-discord-bot/commit/37eb38e12762848ac1bdd657e628bea3c6b865cc))
* **dkp:** record timed DKP awards in raid transaction history ([0942541](https://github.com/smcps72/DKP-discord-bot/commit/09425410a5e85eb6c316defdb206872727f394a5))
* **guild_bank:** add fuzzy matching for item deposits with confirmation prompt ([fcd2d6a](https://github.com/smcps72/DKP-discord-bot/commit/fcd2d6a2c75769fcc0356ae74be909ac6b531f5d))
* **guild-bank:** add dedicated inventory/transaction channels with auto-sync and change permissions to raid leader ([decb73b](https://github.com/smcps72/DKP-discord-bot/commit/decb73b737bbfbea714396d4e287a7cf3b474607))
* **guild-bank:** add guild bank feature with deposit, withdraw, inventory, and transaction log ([990a7d2](https://github.com/smcps72/DKP-discord-bot/commit/990a7d283b5a5ea66a3e45bf26cd167d89710161))
* **guild-bank:** reuse deleted item IDs to maintain compact slot numbering ([8a264ef](https://github.com/smcps72/DKP-discord-bot/commit/8a264ef635fbcc3a4a17de10ecd51f5233b40288))
* **hooks:** add SKIP_TEST_PROMPT bypass and enforce E2E testing on staging pushes ([49b7973](https://github.com/smcps72/DKP-discord-bot/commit/49b797382fc33276c13a2bf00dd10248bd543149))
* **raid:** add auto-close when raid leader absent from voice for 10+ minutes ([9093def](https://github.com/smcps72/DKP-discord-bot/commit/9093defe37372d3d0f4efa81bea9393e28fac63b))
* **raid:** add auto-join from voice and bulk ungrouped assignment with multi-member DKP adjustments ([a287ad9](https://github.com/smcps72/DKP-discord-bot/commit/a287ad95b94d41aad0c1c62c297974d388bce69f))
* **raid:** add bulk group assignment and voice channel group assignment features ([58cc00c](https://github.com/smcps72/DKP-discord-bot/commit/58cc00c4f8bb442915a58d1d9fdfbcfb90bb0429))
* **raid:** add cutoff-based DKP reversal and refactor reversal logic to support inactive raids ([52fe728](https://github.com/smcps72/DKP-discord-bot/commit/52fe728d35b475c801b93db70d8914f290abb20f))
* **raid:** add DM notifications for DKP reversals and undo operations ([8773527](https://github.com/smcps72/DKP-discord-bot/commit/877352769697b7c4bcf995d93c8365a9fc1fdd41))
* **raid:** add emoji to Raid Points button and move it to row 0 with Add Manager button ([188f195](https://github.com/smcps72/DKP-discord-bot/commit/188f1957a5ac45d929d29205ae1b156d335238fb))
* **raid:** add exclusion reasons and auto-rejoin logic with voice sync before timed DKP awards ([c8453a0](https://github.com/smcps72/DKP-discord-bot/commit/c8453a0f90c067d30727be5266ac9b758cbe3f37))
* **raid:** add group 0 (Not in raid) to exclude members from DKP awards ([879d2f6](https://github.com/smcps72/DKP-discord-bot/commit/879d2f6549a6ff926b866ea6d3664a95d56d1735))
* **raid:** add member mentions to multi-target DKP adjustment announcements with 2000-char fallback ([da992d9](https://github.com/smcps72/DKP-discord-bot/commit/da992d9d8648f81e0e5e36b141c4ebf2d45892f3))
* **raid:** add public audit message for raid DKP reversals with 200-char reason truncation ([523c94b](https://github.com/smcps72/DKP-discord-bot/commit/523c94b7576397d4da72a3be8861e8e14cca592b))
* **raid:** add raid manager role with can_manage_raid helper and database support ([3613e36](https://github.com/smcps72/DKP-discord-bot/commit/3613e36ea194324c4a8d80776b23ca4740307e42))
* **raid:** add slash command for cutoff-based DKP reversal on archived raids and support UTC offset parsing ([0b57b05](https://github.com/smcps72/DKP-discord-bot/commit/0b57b05fd5eba90d3107fbbbf86cae06a016913c))
* **raid:** add source parameter to DKP adjustment modals for award and deduct commands ([873b31e](https://github.com/smcps72/DKP-discord-bot/commit/873b31e83561a0ef5e24aad16e11f8844a23a6e2))
* **raid:** add undo last DKP award feature with batch detection and idempotency guard ([faa01a3](https://github.com/smcps72/DKP-discord-bot/commit/faa01a3c4ab0960d5076e4d25a2d81e9c33dccda))
* **raid:** add voice channel picker to sync voice command with optional channel parameter ([6c1f00d](https://github.com/smcps72/DKP-discord-bot/commit/6c1f00df6c47c0673cd808cbd028f3af36cf8484))
* **raid:** add voice_synced flag and auto-assign group 0 to members joining after first sync ([3da8d36](https://github.com/smcps72/DKP-discord-bot/commit/3da8d36d427f531cc513251eb750c30fda1eaeb5))
* **raid:** change raid_create permission from admin to officer and add reason column to exclusions ([d24d013](https://github.com/smcps72/DKP-discord-bot/commit/d24d013631a4de703dad0306e58b20403e92b5a9))
* **raid:** replace UserSelect with paginated Select for member group assignment to scope picker to raid roster ([d78e69e](https://github.com/smcps72/DKP-discord-bot/commit/d78e69e0f3d0eac9ceb5fb12871b3f3e56b512fe))
* **raid:** show added member names in update_team command response ([dc8fe90](https://github.com/smcps72/DKP-discord-bot/commit/dc8fe906a82df46d45473c959b274e4fb0ef1c6e))
* **raid:** show full roster after update_team command and make response ephemeral ([19d112c](https://github.com/smcps72/DKP-discord-bot/commit/19d112c832090982b6f870ac36a1bcfcf9eca2c9))
* **reset:** add guild bank cleanup to reset command ([bd78936](https://github.com/smcps72/DKP-discord-bot/commit/bd78936bbc98e44cd393fc305501d6965fe33c3c))
* **security-scan:** add cross-platform support and improve command execution safety ([00f6868](https://github.com/smcps72/DKP-discord-bot/commit/00f6868e3510652dab54ae2836a85e4774e79d0c))
* **ui:** replace member dropdowns with searchable UserSelect components and add pagination to bulk group assignment ([f381ae7](https://github.com/smcps72/DKP-discord-bot/commit/f381ae7e6d1ef42261c9f2e27278e5c5176466aa))
* **voice:** add live push-to-talk voice command system with tiering, metering, and TTS personas ([83018fa](https://github.com/smcps72/DKP-discord-bot/commit/83018fa38096accef6f4aa7ac070d8e1b1ca45a1))
* **voice:** add undo system for AI commands with /undo_last_command ([b3942de](https://github.com/smcps72/DKP-discord-bot/commit/b3942dec85ad22e59bc52590eb144142f072cfa9))
* **voice:** move defer call before permission check in /undo_last_command ([8fb4c9a](https://github.com/smcps72/DKP-discord-bot/commit/8fb4c9a1d3fcb3418616c0d7f06885b65bf46169))
* **voice:** open voice AI commands to everyone during beta ([30f1b5a](https://github.com/smcps72/DKP-discord-bot/commit/30f1b5ac17ac4212e86104c42ae293d07baecd41))


### Bug Fixes

* **hooks:** add staging branch to pre-push E2E testing prompt ([f116b3d](https://github.com/smcps72/DKP-discord-bot/commit/f116b3dbbd205fad841a1dbedc5ce3f0a6f71b5c))
* **raid:** add defensive error handling for raid dict access in permission checks ([93b2dd0](https://github.com/smcps72/DKP-discord-bot/commit/93b2dd0d8d0bc058397dda2f6c025278c0bafcd5))
* **raid:** add member fetch fallback for DKP reversals and undo operations ([cc4a855](https://github.com/smcps72/DKP-discord-bot/commit/cc4a8554a0f601d448fcccee377ac6e9d4a5a3b1))
* **voice:** defer interaction before officer check in /undo_last_command ([571fe66](https://github.com/smcps72/DKP-discord-bot/commit/571fe665a3a4c8900f545ea67dafed56df4d9b1b))

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
