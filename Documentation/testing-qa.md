# Testing / QA

This page is a practical checklist/framework for validating the bot after changes, with an emphasis on **Discord interaction reliability** (buttons, selects, modals, ephemeral flows) and reducing reliance on production testing.

## What to validate (framework)

### 1) Classify the change

- **[Interaction/UI change]** Any change to `discord.ui.View` / `Modal` / component callbacks, message content, embeds, or permission checks.
- **[Command change]** Any change to `app_commands` (slash commands) params, autocomplete, or guards.
- **[Data model / DB change]** Any change to schema, queries, or raid/auction state transitions.
- **[Infra/config change]** Any change to env vars, deploy process, workflow configs.

Your regression scope should be proportional to the class of change.

### 2) Interaction invariants (high-value checks)

- **[Respond within Discord deadlines]** Any button/select callback must acknowledge quickly (typically via `defer(...)`), or Discord will show “This interaction failed”.
- **[Modal rule]** If an interaction opens a modal, it must use the **initial** interaction response (`send_modal`). Do not `defer()` first.
- **[Ephemeral expectations]** Private panels should remain ephemeral (only visible to the clicker).
- **[Permission gates]** Confirm restricted actions deny with a clear ephemeral error and do not mutate state.
- **[State transitions]** Raid/auction start/end flows should be idempotent or fail cleanly when repeated.

### 3) Regression matrix (template)

For every interaction surface you touch, validate:

- **[Happy path]** Expected success flow.
- **[No-permission path]** A normal raider can’t do officer/admin actions.
- **[Wrong-channel path]** Command/button used outside an expected channel/thread.
- **[Expired/old message path]** Component on an old message still fails gracefully.
- **[Concurrent path]** Two users press/submit at near the same time (no crashes, clear errors).

## Interaction surfaces to validate

Use this as a checklist after changes.

### Welcome message / DKP Panel

- **[Open DKP Panel]** Opens an ephemeral panel, shows correct buttons for:
  - **[Raider]** No admin controls.
  - **[Officer]** Can create raids.
  - **[Admin]** Sees admin-only controls.
- **[Create Raid]** Officer/admin can create; raider gets a permission denial.
- **[My DKP]** Returns an ephemeral embed with DKP value.
- **[Auction Help]** Returns an ephemeral embed.
- **[Bot Status]** Returns status; admins also see env info.
- **[Change Log]** Opens changelog viewer; officers may see `Unreleased`, non-officers should not.

### Raid control panel (thread)

- **[Join Raid / Leave Raid]** Works for a normal raider; shows clear errors when not in a raid thread.
- **[Leader-only controls]** Only raid leader (or bot admin) can:
  - **[Award/Deduct DKP]** Opens modal; submit validates numeric input and applies correctly.
  - **[Start/End Auction]** Creates/ends auction; handles “auction already active / none active”.
  - **[Close Raid]** Ends raid; produces expected logs/messages.
- **[Officer-only controls]** Confirm any officer-only actions behave as intended (and deny cleanly).
- **[Update Team / Voice roster]** Produces the expected public/ephemeral behavior.

### Auction bidding

- **[Open Bid Panel]** Opens an ephemeral bid panel.
- **[Bid modal]**
  - **[Valid bid]** Accepts and records.
  - **[Invalid bid]** Rejects with a clear ephemeral error.
  - **[Duplicate bid]** Rejects cleanly.
- **[End auction]** Winner is computed; DKP deductions/notifications happen; state is closed.

### Admin panel

- **[Access gate]** Non-admin cannot open; admin can.
- **[Role selection]** Officer role assignment works and persists.

### Changelog viewer

- **[Dropdown options]** Shows released versions; `Unreleased` only when allowed.
- **[Selection]** Switching versions updates embeds and selected state.
- **[Long entries]** Long notes render across multiple embeds without truncation errors.

## Staging validation routine (reduce production testing)

### Recommended workflow

- **[Local confidence]** Run unit tests and do quick local interaction validation in a test guild.
- **[Staging validation]** Merge/fast-forward into `staging` and rely on CI + a short manual smoke in the staging guild.
- **[Production release]** Only after staging is green.

### 1) Local validation

- **[Python unit tests]**
  - Run `pytest`.
- **[Manual interaction smoke]**
  - Use a dedicated test guild.
  - Prefer using `TEST_GUILD_ID` to sync commands quickly to the test guild (the bot syncs either globally or to `TEST_GUILD_ID`).

### 2) Staging smoke (automated)

The repo includes a GitHub Actions workflow `.github/workflows/staging-smoke.yml` that runs:

- **[Unit tests]** `pytest -q`
- **[Discord UI smoke]** Playwright test `js-e2e/tests/changelog-smoke.e2e.spec.js`

This is intended to validate that the bot is up and core interaction UI flows are functional.

### 3) Staging smoke (manual, fast)

After CI passes on `staging`, do a quick 2–5 minute check in the staging guild:

- **[Welcome panel]** Confirm you can open the DKP panel and click `Change Log`.
- **[Changelog]** Confirm version dropdown opens and selections update.
- **[One raid flow]** Create a raid, join/leave once, and open the control panel.

## Playwright Discord auth state (for local/staging smoke)

The Playwright tests require `js-e2e/discord-auth.json`:

- **[Create auth state]** From `js-e2e/` run the setup test that saves `discord-auth.json` (see the test output and existing scripts/config).
- **[CI secret]** For GitHub Actions, the workflow expects a base64+gzip encoded auth state in `DISCORD_AUTH_JSON_GZ_B64`.

## When to add/expand tests

- **[New interaction surface]** Add at least one automated smoke path (Playwright or unit tests where possible).
- **[Bugfix regression]** Add a test that would have caught the bug.
- **[Permission/policy change]** Add a negative-path check (denied behavior) in a test or a documented manual step.
