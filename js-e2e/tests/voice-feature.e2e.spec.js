import { test, expect } from '@playwright/test';
import fs from 'fs';

// Feature-complete testing for the /voice push-to-talk voice command system.
// Voice is in OPEN BETA (free for everyone; the paid gate is off unless
// VOICE_REQUIRE_PAID is set). Live audio can't be exercised here (no voice-recv
// ext / STT keys / real speech), so this verifies the observable behavior:
// /voice start passes the (now-open) gate and degrades gracefully to the
// "voice receive unavailable" path — NOT the "paid feature" gate — and the
// shared intent->dispatch core (/ai) still works after the voice changes.

const GUILD_ID = '1388467074346516621';
const CHANNEL_ID = '1433615577892520037'; // #general

function ensureAuthState() {
  if (!fs.existsSync('discord-auth.json')) {
    test.skip(true, 'discord-auth.json not found. Run the setup-discord-auth spec first.');
  }
}

async function openChannel(page) {
  await page.goto(`https://discord.com/channels/${GUILD_ID}/${CHANNEL_ID}`, {
    timeout: 60_000,
    waitUntil: 'domcontentloaded',
  });
  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 2000 }).catch(() => false)) {
    throw new Error('Discord login page detected; storageState did not load. Regenerate discord-auth.json.');
  }
  await page
    .getByRole('textbox', { name: /Message #/ })
    .first()
    .waitFor({ state: 'visible', timeout: 45_000 });
  await page.waitForTimeout(2000);
}

// Invoke a slash command. `command` is typed to trigger the picker; Enter selects
// the highlighted command; `arg` (if given) is typed into the focused option;
// Enter submits.
async function runSlash(page, command, arg) {
  const box = page.getByRole('textbox', { name: /Message #/ }).first();
  await box.click();
  await box.pressSequentially(command, { delay: 80 });
  await page.waitForTimeout(2000); // let the command autocomplete render
  await page.keyboard.press('Enter'); // select the highlighted command
  await page.waitForTimeout(1000);
  if (arg) {
    await page.keyboard.type(arg, { delay: 25 });
    await page.waitForTimeout(600);
  }
  await page.keyboard.press('Enter'); // submit
}

test('/voice start degrades gracefully and /ai core still works', async ({ page }) => {
  test.setTimeout(150_000);
  ensureAuthState();

  await page.context().grantPermissions(['microphone'], { origin: 'https://discord.com' }).catch(() => {});
  await openChannel(page);

  // Join the "General" voice channel so /voice start passes the "must be in a
  // voice channel" pre-check and reaches the substantive tier gate. (No real
  // audio is exchanged — the paid gate returns before any voice connection.)
  const vc = page.getByRole('button', { name: /General \(voice channel\)/i }).first();
  if (await vc.isVisible({ timeout: 8000 }).catch(() => false)) {
    await vc.click().catch(() => {});
    await page.waitForTimeout(4000); // let the gateway register our voice state
  }

  // --- Open beta: /voice start (in a VC, free tier) must now PASS the gate and
  // reach the "voice receive unavailable" path (the audio extension isn't
  // installed here). Waiting for that text also proves the paywall is gone — if
  // the paid gate were still active we'd get "Voice is a paid feature" and this
  // wait would time out. It must respond gracefully and never crash. ---
  await runSlash(page, '/voice start');
  const voiceReply = page
    .getByText(/voice receive unavailable|voice minutes used|couldn.?t start voice/i)
    .first();
  // Reaching this text proves the gate is open: a still-active paywall would
  // reply "Voice is a paid feature" and the wait above would have timed out.
  await voiceReply.waitFor({ state: 'visible', timeout: 30_000 });
  await page.screenshot({ path: 'voice-start.png' });
  await expect(voiceReply).toBeVisible();

  // --- Regression: the shared intent->dispatch core via /ai. Off-topic must
  // still hit the clean decline path. ---
  await runSlash(page, '/ai', 'tell me a joke about goblins');
  const aiReply = page.getByText(/couldn.?t match that to a known command/i).first();
  await aiReply.waitFor({ state: 'visible', timeout: 30_000 });
  await page.screenshot({ path: 'voice-ai-regression.png' });
  await expect(aiReply).toBeVisible();
});
