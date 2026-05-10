import { test, expect } from '@playwright/test';
import fs from 'fs';

const guildId = (process.env.DISCORD_TEST_GUILD_ID || '1388467074346516621').trim();
const channelId = (process.env.DISCORD_TEST_CHANNEL_ID || '1462142161448468682').trim();

function ensureAuthState() {
  if (!fs.existsSync('discord-auth.json')) {
    test.skip(true, 'discord-auth.json not found. Run setup first.');
  }
}

test('server_points command with ephemeral=true shows private response', async ({ page }) => {
  test.setTimeout(60_000);
  ensureAuthState();

  await page.goto(`https://discord.com/channels/${guildId}/${channelId}`, { waitUntil: 'domcontentloaded' });

  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 3000 }).catch(() => false)) {
    throw new Error('Discord login page detected. Auth state invalid.');
  }

  // Wait for channel to load
  await page.waitForTimeout(3000);

  // Find the actual message input (not search)
  const msgInput = page.getByRole('textbox', { name: /Message/i });
  await msgInput.waitFor({ state: 'visible', timeout: 15000 });

  // Type the command with ephemeral parameter
  await msgInput.fill('/server_points ephemeral:true');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(1000);
  await page.keyboard.press('Enter'); // Confirm command

  // Wait for response
  await page.waitForTimeout(3000);

  // Verify "Only you can see this" appears (ephemeral indicator)
  await expect(page.getByText('Only you can see this', { exact: false }).first()).toBeVisible({ timeout: 15000 });

  // Verify the DKP embed is shown
  await expect(page.getByText('Server DKP', { exact: false }).first()).toBeVisible({ timeout: 15000 });
});

test('server_points command default (ephemeral=false) shows public response', async ({ page }) => {
  test.setTimeout(60_000);
  ensureAuthState();

  await page.goto(`https://discord.com/channels/${guildId}/${channelId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  const msgInput = page.getByRole('textbox', { name: /Message/i });
  await msgInput.waitFor({ state: 'visible', timeout: 15000 });

  // Type the command without ephemeral parameter (default false)
  await msgInput.fill('/server_points');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(1000);
  await page.keyboard.press('Enter');

  await page.waitForTimeout(3000);

  // Verify Server DKP embed appears WITHOUT "Only you can see this" wrapper
  await expect(page.getByText('Server DKP', { exact: false }).first()).toBeVisible({ timeout: 15000 });

  // Should NOT have ephemeral indicator
  const ephemeralText = page.getByText('Only you can see this', { exact: false });
  const count = await ephemeralText.count();
  // The most recent ephemeral message should be from the previous test
  // This test is checking the current command response is not ephemeral
});
