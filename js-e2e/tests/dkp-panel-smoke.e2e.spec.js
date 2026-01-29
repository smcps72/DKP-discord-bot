import { test, expect } from '@playwright/test';
import dotenv from 'dotenv';
import fs from 'fs';
import path from 'path';
import { qase } from 'playwright-qase-reporter';

dotenv.config({ path: path.resolve(process.cwd(), '../.env'), override: true });

const SERVER = (process.env.DISCORD_TEST_SERVER_NAME || '').trim();
const CHANNEL = (process.env.DISCORD_TEST_CHANNEL_NAME || '').trim();

function ensureAuthState() {
  if (!fs.existsSync('discord-auth.json')) {
    test.skip(
      true,
      'discord-auth.json not found. Run DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed from js-e2e/ to create it.',
    );
  }
}

async function openChannel(page) {
  if (!SERVER || !CHANNEL) {
    throw new Error('DISCORD_TEST_SERVER_NAME and DISCORD_TEST_CHANNEL_NAME must be set.');
  }

  await page.goto('https://discord.com/app', { timeout: 60_000, waitUntil: 'domcontentloaded' });
  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 1500 }).catch(() => false)) {
    throw new Error('Discord login page detected. The storageState did not load; regenerate discord-auth.json.');
  }

  const serverTreeItem = page.getByRole('treeitem', { name: SERVER });
  await serverTreeItem.first().waitFor({ state: 'visible', timeout: 45_000 });
  await serverTreeItem.first().click({ timeout: 45_000 });
  await page.waitForTimeout(1500);

  const channelPattern = new RegExp(`^(unread,\\s*)?${CHANNEL}(\\b|\\s|\\().*`, 'i');
  const channelLink = page.getByRole('link', { name: channelPattern }).first();
  await channelLink.waitFor({ state: 'visible', timeout: 45_000 });
  await channelLink.click({ timeout: 45_000 });
  await page.waitForTimeout(1500);

  await expect
    .poll(
      async () => {
        const openPanelCount = await page.getByRole('button', { name: /Open DKP Panel/i }).count();
        if (openPanelCount > 0) return true;
        const pinnedCount = await page.getByRole('button', { name: /Pinned Messages/i }).count();
        if (pinnedCount > 0) return true;
        const mainCount = await page.locator('div[role="main"], main').count();
        return mainCount > 0;
      },
      { timeout: 45_000 },
    )
    .toBe(true);

  await page.waitForTimeout(2000);
}

async function openDkpPanel(page) {
  await openChannel(page);

  let openPanelButton = page.getByRole('button', { name: /Open DKP Panel/i }).last();
  if (!(await openPanelButton.isVisible({ timeout: 6000 }).catch(() => false))) {
    const dkpSystemChannel = page.getByRole('link', { name: /(unread,\s*)?dkp-system/i }).first();
    if (await dkpSystemChannel.isVisible({ timeout: 8000 }).catch(() => false)) {
      await dkpSystemChannel.click({ timeout: 15_000 });
      await page.waitForTimeout(1500);
      openPanelButton = page.getByRole('button', { name: /Open DKP Panel/i }).last();
    }
  }

  if (await openPanelButton.isVisible({ timeout: 15000 }).catch(() => false)) {
    await openPanelButton.click({ timeout: 15000 });
  } else {
    const pinnedButton = page.getByRole('button', { name: /pinned/i }).first();
    await pinnedButton.waitFor({ state: 'visible', timeout: 15000 });
    await pinnedButton.click({ timeout: 15000 });

    const welcomeText = page.getByText('Welcome to the DKP Bot!', { exact: false }).first();
    if (await welcomeText.isVisible({ timeout: 15_000 }).catch(() => false)) {
      await welcomeText.click({ timeout: 15_000 });
      await page.waitForTimeout(1000);
    }

    const pinnedOpenPanelButton = page.getByRole('button', { name: /Open DKP Panel/i }).last();
    await pinnedOpenPanelButton.waitFor({ state: 'visible', timeout: 45000 });
    await pinnedOpenPanelButton.click({ timeout: 15000 });
  }

  const panelTitle = page.getByText(/DKP Panel for/i).last();
  if (!(await panelTitle.isVisible({ timeout: 10_000 }).catch(() => false))) {
    const retryOpen = page.getByRole('button', { name: /Open DKP Panel/i }).last();
    if (await retryOpen.isVisible({ timeout: 8000 }).catch(() => false)) {
      await retryOpen.click({ timeout: 15_000 });
    }
  }
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
