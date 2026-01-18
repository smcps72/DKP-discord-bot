import { test, expect } from '@playwright/test';
import fs from 'fs';
import { qase } from 'playwright-qase-reporter';

const guildId = (process.env.DISCORD_TEST_GUILD_ID || '1383966524150124604').trim();
const channelId = (process.env.DISCORD_TEST_CHANNEL_ID || '1459606597528715307').trim();

function ensureAuthState() {
  if (!fs.existsSync('discord-auth.json')) {
    test.skip(
      true,
      'discord-auth.json not found. Run DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed from js-e2e/ to create it.',
    );
  }
}

async function openChannel(page) {
  await page.goto(`https://discord.com/channels/${guildId}/${channelId}`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: /dkp-system/i }).first().waitFor({ state: 'visible', timeout: 45000 });
  await page.waitForTimeout(5000);

  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 1500 }).catch(() => false)) {
    throw new Error('Discord login page detected. The storageState did not load; regenerate discord-auth.json.');
  }
}

async function openDkpPanel(page) {
  await openChannel(page);

  const openPanelButton = page.getByRole('button', { name: /Open DKP Panel/i }).last();
  if (await openPanelButton.isVisible({ timeout: 15000 }).catch(() => false)) {
    await openPanelButton.click({ timeout: 15000 });
  } else {
    const pinnedButton = page.getByRole('button', { name: /Pinned Messages/i }).first();
    await pinnedButton.waitFor({ state: 'visible', timeout: 15000 });
    await pinnedButton.click({ timeout: 15000 });

    const pinnedOpenPanelButton = page.getByRole('button', { name: /Open DKP Panel/i }).last();
    await pinnedOpenPanelButton.waitFor({ state: 'visible', timeout: 45000 });
    await pinnedOpenPanelButton.click({ timeout: 15000 });
  }

  const panelTitle = page.getByText(/DKP Panel for/i).last();
  await panelTitle.waitFor({ state: 'visible', timeout: 45000 });
  const panel = panelTitle.locator('xpath=ancestor::li[1]');

  await expect(panel.getByText('Only you can see this', { exact: false }).first()).toBeVisible({ timeout: 45000 });

  return panel;
}

test('DKP panel shows core actions', async ({ page }) => {
  qase.suite('Discord UI\tDKP Panel');
  qase.title('DKP Panel opens and shows core buttons');

  test.setTimeout(120_000);
  ensureAuthState();

  const panel = await openDkpPanel(page);

  await expect(panel.getByRole('button', { name: /My DKP/i }).first()).toBeVisible({ timeout: 45000 });
  await expect(panel.getByRole('button', { name: /Auction Help/i }).first()).toBeVisible({ timeout: 45000 });
  await expect(panel.getByRole('button', { name: /Bot Status/i }).first()).toBeVisible({ timeout: 45000 });
  await expect(panel.getByRole('button', { name: /Change Log/i }).first()).toBeVisible({ timeout: 45000 });
});

test('DKP panel My DKP returns an ephemeral balance', async ({ page }) => {
  qase.suite('Discord UI\tDKP Panel');
  qase.title('My DKP returns an ephemeral DKP balance');

  test.setTimeout(120_000);
  ensureAuthState();

  const beforeCount = await page.getByText('Your DKP Balance', { exact: false }).count();
  const panel = await openDkpPanel(page);

  await panel.getByRole('button', { name: /My DKP/i }).first().click({ timeout: 15000 });

  await expect
    .poll(async () => page.getByText('Your DKP Balance', { exact: false }).count(), { timeout: 45000 })
    .toBeGreaterThan(beforeCount);
});

test('DKP panel Auction Help returns an ephemeral help message', async ({ page }) => {
  qase.suite('Discord UI\tDKP Panel');
  qase.title('Auction Help returns an ephemeral help message');

  test.setTimeout(120_000);
  ensureAuthState();

  const beforeCount = await page.getByText('Auction Help', { exact: false }).count();
  const panel = await openDkpPanel(page);

  await panel.getByRole('button', { name: /Auction Help/i }).first().click({ timeout: 15000 });

  await expect
    .poll(async () => page.getByText('Auction Help', { exact: false }).count(), { timeout: 45000 })
    .toBeGreaterThan(beforeCount);
});

test('DKP panel Bot Status returns an ephemeral status message', async ({ page }) => {
  qase.suite('Discord UI\tDKP Panel');
  qase.title('Bot Status returns an ephemeral status message');

  test.setTimeout(120_000);
  ensureAuthState();

  const beforeCount = await page.getByText('Bot Status', { exact: true }).count();
  const panel = await openDkpPanel(page);

  await panel.getByRole('button', { name: /Bot Status/i }).first().click({ timeout: 15000 });

  await expect
    .poll(async () => page.getByText('Bot Status', { exact: true }).count(), { timeout: 45000 })
    .toBeGreaterThan(beforeCount);
});
