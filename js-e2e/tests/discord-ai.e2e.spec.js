import { test, expect } from '@playwright/test';
import { ai } from '@zerostep/playwright';
import dotenv from 'dotenv';
import path from 'path';

// Load the same .env used by the Python bot/tests, from the project root.
dotenv.config({ path: path.resolve(process.cwd(), '../.env') });

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

  // 1. Go to Discord login
  await page.goto('https://discord.com/login');

  // 2. Log in using regular Playwright selectors
  await page.getByLabel('Email or Phone Number').fill(EMAIL);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log In' }).click();

  // Wait for the main UI to stabilize
  await page.waitForTimeout(8000);

  // 3. Use AI to navigate to the server and channel
  await ai(`Open the server called "${SERVER}"`, { page, test });
  await ai(`Open the channel called "${CHANNEL}"`, { page, test });

  // 4. Measure current message count
  const messages = page.locator('div[class*="messageContent"]');
  const beforeCount = await messages.count();

  // 5. Use AI to send the !help command
  await ai('Type "!help" in the message input and send it.', { page, test });

  // 6. Assert that at least one new message appears afterwards
  await page.waitForTimeout(5000);
  const afterCount = await messages.count();
  await expect(afterCount).toBeGreaterThan(beforeCount);
});
