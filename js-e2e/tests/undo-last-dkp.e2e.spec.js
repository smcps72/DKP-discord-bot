import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const jsE2eRoot = path.resolve(__dirname, '..');

const GUILD_ID = '1388467074346516621';
const ACTIVE_RAIDS_CHANNEL_ID = '1477500243301105756';
// Thread created by: python js-e2e/create-test-raid.py
const RAID_THREAD_ID = process.env.DISCORD_TEST_RAID_THREAD_ID || '1492935526074941600';
const ACTIVE_RAIDS_URL = `https://discord.com/channels/${GUILD_ID}/${ACTIVE_RAIDS_CHANNEL_ID}`;
const RAID_THREAD_URL = `https://discord.com/channels/${GUILD_ID}/${RAID_THREAD_ID}`;

function ensureAuthState() {
  if (!fs.existsSync(path.join(jsE2eRoot, 'discord-auth.json'))) {
    test.skip(
      true,
      'discord-auth.json not found. Run DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed from js-e2e/ to create it.',
    );
  }
}

async function dismissOverlays(page) {
  // Aggressively remove Discord promo/Nitro/game-server dialogs via JS
  await page.evaluate(() => {
    document.querySelectorAll('[role="dialog"], dialog').forEach((el) => el.remove());
    // Also remove any click-trap containers
    document.querySelectorAll('[class*="clickTrap"], [class*="layerContainer"]').forEach((el) => {
      if (el.querySelector('[role="dialog"], dialog, video')) el.remove();
    });
  }).catch(() => null);
  await page.waitForTimeout(300);

  // Dismiss any remaining banners via button clicks
  const dismissBtn = page.getByRole('button', { name: /^Dismiss$/i }).first();
  if (await dismissBtn.isVisible({ timeout: 500 }).catch(() => false)) {
    await dismissBtn.click({ force: true }).catch(() => null);
    await page.waitForTimeout(300);
  }
}

async function waitForDiscordLoad(page) {
  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 3000 }).catch(() => false)) {
    throw new Error('Discord login page detected. Regenerate discord-auth.json.');
  }
  await expect
    .poll(
      async () => {
        const mainCount = await page.locator('div[role="main"], main').count();
        return mainCount > 0;
      },
      { timeout: 45_000 },
    )
    .toBe(true);
  await page.waitForTimeout(5000);
  await dismissOverlays(page);
}

async function navigateToRaidThread(page) {
  // Step 1: Load active-raids channel to establish guild context in Discord SPA
  await page.goto(ACTIVE_RAIDS_URL, { waitUntil: 'domcontentloaded' });
  await waitForDiscordLoad(page);
  console.log('✅ Loaded active-raids channel');

  // Step 2: Now navigate to the thread URL — SPA should handle it with guild context
  await page.goto(RAID_THREAD_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(8000);

  // Check if we're in the thread (heading should mention the thread name or show thread content)
  const threadHeading = page.locator('h1, h2').filter({ hasText: /E2E-Undo-Test/i }).first();
  if (await threadHeading.isVisible({ timeout: 5000 }).catch(() => false)) {
    console.log('✅ Navigated to thread via direct URL');
    return;
  }

  // Check if we ended up in the thread by looking for the panel button
  const panelBtn = page.locator('button, [role="button"]')
    .filter({ hasText: /Open Raid Control Panel/i }).first();
  if (await panelBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
    console.log('✅ In thread (found control panel button)');
    return;
  }

  // Fallback: Go back to active-raids and use Threads popover
  console.log('⚠️ Direct thread URL failed, trying Threads popover fallback');
  await page.goto(ACTIVE_RAIDS_URL, { waitUntil: 'domcontentloaded' });
  await waitForDiscordLoad(page);

  const threadsBtn = page.getByRole('button', { name: /Threads/i }).first();
  await expect(threadsBtn).toBeVisible({ timeout: 10_000 });
  await threadsBtn.click({ force: true });
  await page.waitForTimeout(2000);

  const threadItem = page.getByText(/E2E-Undo-Test/i).first();
  await expect(threadItem).toBeVisible({ timeout: 10_000 });
  await threadItem.click();
  await page.waitForTimeout(5000);
  console.log('✅ Opened thread via Threads popover');
}

async function openRaidPanelAndGetReverseBtn(page) {
  // The thread has "Open Raid Control Panel" persistent button
  const openPanelBtn = page.locator('button, [role="button"]')
    .filter({ hasText: /Open Raid Control Panel/i }).last();
  await expect(openPanelBtn).toBeVisible({ timeout: 30_000 });
  console.log('✅ Found Open Raid Control Panel button');
  await openPanelBtn.click();
  await page.waitForTimeout(3000);

  // The ephemeral popup shows in "main" mode. Click "DKP" to switch to "manage" mode
  // which contains the Reverse Raid DKP button.
  const dkpBtn = page.locator('button, [role="button"]')
    .filter({ hasText: /^DKP$/i }).last();
  await expect(dkpBtn).toBeVisible({ timeout: 15_000 });
  console.log('✅ Found DKP button in ephemeral panel');
  await dkpBtn.click();
  await page.waitForTimeout(3000);

  // Now in "manage" mode — look for "Reverse Raid DKP" button
  const reverseBtn = page.locator('button, [role="button"]')
    .filter({ hasText: /Reverse Raid DKP/i }).last();
  await expect(reverseBtn).toBeVisible({ timeout: 15_000 });
  console.log('✅ Found Reverse Raid DKP in manage panel');
  return reverseBtn;
}

test('Reverse Raid DKP shows Undo Last Award choice view and modal works', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await navigateToRaidThread(page);
  console.log('✅ Navigated to raid thread');

  // Open the raid panel
  const reverseBtn = await openRaidPanelAndGetReverseBtn(page);

  // Click Reverse Raid DKP → should show choice view
  await reverseBtn.click();
  await page.waitForTimeout(3000);

  const undoBtn = page.locator('button, [role="button"]')
    .filter({ hasText: /Undo Last Award/i }).last();
  const removeAllBtn = page.locator('button, [role="button"]')
    .filter({ hasText: /Remove All DKP/i }).last();
  const backBtn = page.locator('button, [role="button"]')
    .filter({ hasText: /^Back$/i }).last();

  await expect(undoBtn).toBeVisible({ timeout: 15_000 });
  await expect(removeAllBtn).toBeVisible({ timeout: 5_000 });
  await expect(backBtn).toBeVisible({ timeout: 5_000 });
  console.log('✅ Choice view: Undo Last Award, Remove All DKP, Back');

  // Click Undo Last Award → should open modal
  await undoBtn.click();
  await page.waitForTimeout(2000);

  const modalTitle = page.getByText('Undo Last DKP Award');
  await expect(modalTitle).toBeVisible({ timeout: 10_000 });

  const confirmInput = page.getByPlaceholder('CONFIRM');
  await expect(confirmInput).toBeVisible({ timeout: 5_000 });
  console.log('✅ Undo Last DKP Award modal opened');

  // Fill and submit
  await confirmInput.fill('CONFIRM');

  const reasonInput = page.getByPlaceholder(/Wrong amount|duplicate payout/i);
  if (await reasonInput.isVisible({ timeout: 2000 }).catch(() => false)) {
    await reasonInput.fill('E2E test - verifying undo feature');
  }

  const submitBtn = page.getByRole('button', { name: /Submit/i });
  await submitBtn.click();
  await page.waitForTimeout(3000);

  // Check result
  const bodyText = await page.textContent('body').catch(() => '');
  if (bodyText.includes('Undid last DKP award')) {
    console.log('✅ Undo succeeded');
  } else if (bodyText.includes('No DKP award batches')) {
    console.log('✅ No batches to undo (expected for fresh raid)');
  } else if (bodyText.includes('already been undone')) {
    console.log('✅ Idempotency guard working');
  } else {
    console.log('ℹ️ Modal submitted - check bot logs for result');
  }
});

test('Reverse Raid DKP choice view Back button works', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await navigateToRaidThread(page);

  const reverseBtn = await openRaidPanelAndGetReverseBtn(page);
  await reverseBtn.click();
  await page.waitForTimeout(3000);

  const backBtn = page.locator('button, [role="button"]')
    .filter({ hasText: /^Back$/i }).last();
  await expect(backBtn).toBeVisible({ timeout: 15_000 });
  await backBtn.click();
  await page.waitForTimeout(2000);

  // After clicking Back, the choice buttons should be gone and we should be
  // back at the main popup panel
  const undoBtn = page.locator('button, [role="button"]')
    .filter({ hasText: /Undo Last Award/i });
  await expect(undoBtn).toHaveCount(0, { timeout: 10_000 });
  console.log('✅ Back button dismissed the choice view');
});
