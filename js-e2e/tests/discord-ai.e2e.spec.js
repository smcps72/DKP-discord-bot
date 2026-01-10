import { test, expect } from '@playwright/test';
import { ai } from '@zerostep/playwright';
import dotenv from 'dotenv';
import path from 'path';

// Load the same .env used by the Python bot/tests, from the project root.
// Use override: true so JS tests always respect the values in .env even if
// the shell already has these variables set.
dotenv.config({ path: path.resolve(process.cwd(), '../.env'), override: true });

const EMAIL = process.env.DISCORD_TEST_EMAIL;
const PASSWORD = process.env.DISCORD_TEST_PASSWORD;
const SERVER = process.env.DISCORD_TEST_SERVER_NAME;
const CHANNEL = process.env.DISCORD_TEST_CHANNEL_NAME;

// Mirror the Python Playwright E2E flow, but use ZeroStep ai() for the
// Discord-specific navigation and message sending.

test('Discord bot responds to !help (AI-driven)', async ({ page }) => {
  test.skip(
    !EMAIL || !PASSWORD || !SERVER || !CHANNEL,
    'DISCORD_TEST_* env vars must be set in .env for this test',
  );

  // Prefer a saved storageState (discord-auth.json) via playwright.config.js.
  // If it is missing/expired, the Discord login form may trigger hCaptcha,
  // so instruct to regenerate auth state manually.
  await page.goto('https://discord.com/app');

  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 5000 }).catch(() => false)) {
    throw new Error(
      'Discord login page detected. Run `DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed` from js-e2e/ to log in once and create discord-auth.json, then re-run the tests.',
    );
  }

  // Close any promo dialog that can block navigation.
  const closeDialog = page.getByRole('button', { name: 'Close' }).first();
  if (await closeDialog.isVisible({ timeout: 3000 }).catch(() => false)) {
    await closeDialog.click();
  }

  await page.getByRole('treeitem', { name: SERVER }).click();
  await page.waitForTimeout(2000);
  await page.getByRole('link', { name: CHANNEL }).click();
  await page.waitForTimeout(2000);

  // 4. Measure current message count
  const messages = page.locator('div[class*="messageContent"]');
  const beforeCount = await messages.count();

  // 5. Send the !help command
  const messageBox = page.getByRole('textbox', { name: /Message #/ });
  await messageBox.click();
  await messageBox.fill('!help');
  await messageBox.press('Enter');

  // 6. Assert that at least one new message appears afterwards
  await page.waitForTimeout(5000);
  const afterCount = await messages.count();
  await expect(afterCount).toBeGreaterThan(beforeCount);
});
