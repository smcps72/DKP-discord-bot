---
description: Test a completed feature using Playwright MCP
---

# Feature Complete Testing Workflow

Use this workflow when a feature is complete and ready for E2E testing via Playwright MCP.

## Prerequisites

1. **Discord auth state must exist**: `js-e2e/discord-auth.json`
   - If missing or expired, run from `js-e2e/`:
     ```bash
     DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed
     ```
   - Log in manually in the browser, then close the Playwright inspector.
   - If the Playwright MCP browser shows the Discord login page, log in using the
     credentials from the repo-root `.env` file (`DISCORD_TEST_EMAIL` / `DISCORD_TEST_PASSWORD`).
     A second account is available as `DISCORD_TEST_EMAIL_2` / `DISCORD_TEST_PASSWORD_2`.

2. **Bot must be running** against the test guild (DKP-local or staging).

3. **Environment variables** in `.env` or `secrets/.env.local`:
   - `DISCORD_TEST_EMAIL` / `DISCORD_TEST_PASSWORD` — test account credentials
   - `DISCORD_TEST_EMAIL_2` / `DISCORD_TEST_PASSWORD_2` — second test account
   - `DISCORD_TEST_GUILD_ID` — target guild ID
   - `DISCORD_TEST_CHANNEL_ID` — target channel ID
   - `DISCORD_TEST_SERVER_NAME` / `DISCORD_TEST_CHANNEL_NAME` — human-readable names
   - `DISCORD_TEST_RAID_THREAD_URL` — URL to an active raid thread for testing

---

## Git Hook (Auto-Prompt)

A pre-push hook is available that prompts you to run this workflow before pushing feature branches.

**Install the hook:**
```bash
cp scripts/hooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push
```

When you push a `feature/*`, `fix/*`, or `feat/*` branch, you'll see:
```
🧪 Feature Branch Detected: feature/my-feature
Have you tested this feature with Playwright MCP?
Run /feature-complete-testing in Cascade to verify.
Continue with push? [y/N/skip]
```

---

## Steps

### 1. Identify the exact feature from the latest commit

**IMPORTANT:** Do NOT test random buttons. Test the specific feature that was just committed.

// turbo
```
Run: git log --oneline -1 && git diff HEAD~1 --name-only
```

This shows:
- The commit message describing the feature
- The files that were changed

Then run `git diff HEAD~1` to see the actual code changes and understand:
- What UI elements were added/modified (buttons, modals, fields)
- What behavior changed
- What text/messages to look for

### 2. Plan the test based on the feature

Based on the diff, determine:
- **Entry point:** How to access the feature (which panel, button, or command)
- **New UI elements:** What new fields, buttons, or text to verify exist
- **Expected behavior:** What should happen when interacting with the feature
- **Success criteria:** What text/state confirms the feature works

### 3. Navigate to the test channel using Playwright MCP

// turbo
```
Use mcp1_browser_navigate to open the Discord channel:
https://discord.com/channels/<GUILD_ID>/<CHANNEL_ID>
```

### 4. Take a snapshot of the page

// turbo
```
Use mcp1_browser_snapshot to capture the current accessibility tree.
Review the snapshot to locate the relevant UI elements (buttons, messages, etc.).
```

### 5. Interact with the feature

Use the appropriate Playwright MCP tools:
- **Click a button**: `mcp1_browser_click` with the `ref` from the snapshot
- **Fill a form/modal**: `mcp1_browser_type` or `mcp1_browser_fill_form`
- **Select dropdown option**: `mcp1_browser_select_option`
- **Wait for response**: `mcp1_browser_wait_for` with expected text

### 6. Verify the expected outcome

// turbo
```
Use mcp1_browser_snapshot again after the interaction.
Check that:
- Expected text/elements appear
- No error messages are shown
- Ephemeral messages display correctly (look for "Only you can see this")
```

### 7. Check console for errors (optional)

// turbo
```
Use mcp1_browser_console_messages with level "error" to check for JS errors.
```

### 8. Document results

- If the test passes, note which interactions were verified.
- If the test fails, capture:
  - The snapshot showing the unexpected state
  - Any console errors
  - Steps to reproduce

### 9. Close the browser session

// turbo
```
Use mcp1_browser_close to clean up.
```

---

## Quick Reference: Common Playwright MCP Tools

| Tool | Purpose |
|------|---------|
| `mcp1_browser_navigate` | Go to a URL |
| `mcp1_browser_snapshot` | Get accessibility tree (use this to find `ref` values) |
| `mcp1_browser_click` | Click an element by `ref` |
| `mcp1_browser_type` | Type text into an input |
| `mcp1_browser_fill_form` | Fill multiple form fields |
| `mcp1_browser_select_option` | Select from a dropdown |
| `mcp1_browser_wait_for` | Wait for text to appear/disappear |
| `mcp1_browser_console_messages` | Get console logs |
| `mcp1_browser_take_screenshot` | Capture visual screenshot |
| `mcp1_browser_close` | Close the browser |

---

## Example: Testing a new "Refresh" button on DKP Panel

1. Navigate: `mcp1_browser_navigate` → `https://discord.com/channels/1388467074346516621/1462142161448468682`
2. Snapshot: `mcp1_browser_snapshot` → find "Open DKP Panel" button ref
3. Click: `mcp1_browser_click` → open the panel
4. Snapshot: `mcp1_browser_snapshot` → find "Refresh" button ref
5. Click: `mcp1_browser_click` → click Refresh
6. Wait: `mcp1_browser_wait_for` → wait for "Refreshed" text
7. Snapshot: `mcp1_browser_snapshot` → verify updated content
8. Close: `mcp1_browser_close`
