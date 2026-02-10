/**
 * E2E tests for multi-select DKP adjustment and Groups/bulk-ungrouped features.
 *
 * These tests create a fresh raid each run (requires voice channel → headed mode).
 * In headless environments the tests skip cleanly.
 *
 * Helpers are intentionally duplicated from raid-controls-smoke.e2e.spec.js so
 * this file is fully self-contained.
 */
import { test, expect } from '@playwright/test';
import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';

dotenv.config({ path: path.resolve(process.cwd(), '../.env'), override: true });

const SERVER = process.env.DISCORD_TEST_SERVER_NAME;
const CHANNEL = process.env.DISCORD_TEST_CHANNEL_NAME;
const VOICE_CHANNEL = (process.env.DISCORD_TEST_VOICE_CHANNEL_NAME || 'General').trim();
const STORAGE_STATE_1 = path.resolve(process.cwd(), 'discord-auth.json');

// ── tiny helpers ──────────────────────────────────────────────────────────────

function esc(v) { return v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

function ensureEnvAndAuth() {
  if (!SERVER || !CHANNEL) test.skip(true, 'DISCORD_TEST_SERVER_NAME / CHANNEL not set.');
  if (!fs.existsSync(STORAGE_STATE_1)) test.skip(true, 'discord-auth.json not found.');
}

async function dumpButtons(page, max = 60) {
  const labels = await page.evaluate((lim) => {
    return Array.from(document.querySelectorAll('button,[role="button"]'))
      .filter(el => { const s = getComputedStyle(el); return s.display !== 'none' && s.visibility !== 'hidden'; })
      .map(el => (el.textContent || '').trim())
      .filter(Boolean)
      .filter((v, i, a) => a.indexOf(v) === i)
      .slice(0, lim);
  }, max).catch(() => []);
  console.log(`Buttons (${labels.length}): ${labels.join(' | ')}`);
}

// ── Discord navigation ────────────────────────────────────────────────────────

async function loginAndOpenChannel(page) {
  await page.goto('https://discord.com/app', { timeout: 60_000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  if (/discord\.com\/login/i.test(page.url())) throw new Error('Auth expired – regenerate discord-auth.json.');

  const srv = page.getByRole('treeitem', { name: SERVER }).first();
  await srv.waitFor({ state: 'visible', timeout: 45_000 });
  await srv.click({ timeout: 45_000 });
  await page.waitForTimeout(2000);

  const pat = new RegExp(`^(unread,\\s*)?${esc(CHANNEL)}(\\b|\\s|\\().*`, 'i');
  const ch = page.getByRole('link', { name: pat }).first();
  if (await ch.isVisible({ timeout: 5000 }).catch(() => false)) {
    await ch.click({ timeout: 45_000 });
  } else {
    await page.keyboard.press('ControlOrMeta+K');
    const qs = page.locator('input[placeholder*="Where would you like to go"]').first();
    if (await qs.isVisible({ timeout: 5000 }).catch(() => false)) {
      await qs.fill(CHANNEL);
      await page.waitForTimeout(750);
      await page.keyboard.press('Enter');
    } else {
      await ch.click({ force: true, noWaitAfter: true, timeout: 15_000 }).catch(() => null);
    }
  }
  await page.waitForTimeout(2000);
}

async function joinVoice(page) {
  try { await page.context().grantPermissions(['microphone'], { origin: 'https://discord.com' }); } catch {}
  const pat = new RegExp(`^${esc(VOICE_CHANNEL)} \\(voice channel\\)`, 'i');
  let vc = page.getByRole('button', { name: pat }).first();
  if (!(await vc.count())) vc = page.getByRole('button', { name: new RegExp(esc(VOICE_CHANNEL), 'i') }).first();
  if (!(await vc.count())) vc = page.getByRole('treeitem', { name: new RegExp(esc(VOICE_CHANNEL), 'i') }).first();
  if (!(await vc.count())) return false;
  await vc.click();
  const conn = page.getByRole('button', { name: /join voice|join call|connect/i }).first();
  if (await conn.isVisible({ timeout: 5000 }).catch(() => false)) await conn.click();
  try {
    await Promise.race([
      page.getByRole('button', { name: /disconnect/i }).first().waitFor({ state: 'visible', timeout: 15_000 }),
      page.getByText(/voice connected|connected/i).first().waitFor({ state: 'visible', timeout: 15_000 }),
    ]);
    return true;
  } catch { return false; }
}

// ── DKP panel / raid creation ─────────────────────────────────────────────────

async function openDkpChannel(page) {
  const links = page.getByRole('link').filter({ hasText: /dkp/i });
  const n = await links.count();
  for (let i = 0; i < n; i++) {
    const name = ((await links.nth(i).innerText().catch(() => '')) || '').toLowerCase();
    if (name.includes('active-raids') || name.includes('archive')) continue;
    if (!(await links.nth(i).isVisible({ timeout: 1000 }).catch(() => false))) continue;
    await links.nth(i).click();
    await page.waitForTimeout(1500);
    return;
  }
}

async function openCreateRaidModal(page) {
  await openDkpChannel(page);

  // Click "Open DKP Panel" from the pinned welcome message
  const openPanel = page.locator('button,[role="button"]').filter({ hasText: /^Open DKP Panel$/i }).first();
  if (!(await openPanel.isVisible({ timeout: 6000 }).catch(() => false))) {
    const pins = page.locator('button,[role="button"]').filter({ hasText: /pins|pinned/i }).first();
    if (await pins.isVisible({ timeout: 6000 }).catch(() => false)) {
      await pins.click();
      await page.waitForTimeout(1500);
      const welcome = page.getByText('Welcome to the DKP Bot!', { exact: false }).first();
      if (await welcome.isVisible({ timeout: 8000 }).catch(() => false)) {
        await welcome.click();
        await page.waitForTimeout(1000);
      }
    }
  }
  await expect(openPanel).toBeVisible({ timeout: 45_000 });

  for (let i = 0; i < 3; i++) {
    await page.keyboard.press('Escape').catch(() => null);
    await openPanel.click({ force: true, noWaitAfter: true, timeout: 15_000 }).catch(() =>
      openPanel.evaluate(el => el.click()).catch(() => null));
    const ok = await expect.poll(async () =>
      (await page.getByText(/DKP Panel for/i).count()) > 0 ||
      (await page.getByText('Only you can see this', { exact: false }).count()) > 0,
    { timeout: 8000 }).toBe(true).then(() => true).catch(() => false);
    if (ok) break;
    await page.waitForTimeout(1200);
  }

  // Find and click Create Raid inside the DKP panel
  const panelTitle = page.getByText(/DKP Panel for/i).last();
  await panelTitle.scrollIntoViewIfNeeded().catch(() => null);
  const panelContainer = panelTitle.locator('xpath=ancestor::li[1]');
  const createBtn = panelContainer.locator('button,[role="button"]').filter({ hasText: /^Create Raid/i }).first();
  await expect(createBtn).toBeVisible({ timeout: 15_000 });
  await createBtn.click();
}

async function createRaid(page, name) {
  await openCreateRaidModal(page);
  const modal = page.getByRole('dialog', { name: 'Create New Raid' });
  await expect(modal).toBeVisible({ timeout: 20_000 });
  await modal.getByLabel('Raid Name').fill(name);
  await modal.getByRole('button', { name: 'Submit' }).click();

  // Navigate to the new raid's thread
  const activeRaids = page.getByRole('link', { name: /unread, active-raids/i });
  if (await activeRaids.count()) await activeRaids.first().click();
  else await page.getByRole('link', { name: /active-raids.*text channel/i }).last().click();

  const threadBtn = page.getByRole('button', { name: new RegExp(`${esc(name)}.*Raid Log.*\\(thread\\)`, 'i') }).last();
  await expect(threadBtn).toBeVisible({ timeout: 45_000 });
  await threadBtn.click();
  await expect(page.getByRole('heading', { name: new RegExp(`Thread:.*${esc(name)}.*Raid Log`, 'i') })).toBeVisible({ timeout: 15_000 });
}

// ── Open Raid Control Panel (fresh thread — button is near the bottom) ────────

async function openRaidPanel(page) {
  const btnRole = page.getByRole('button', { name: /Open Raid Control Panel/i }).first();
  const btnFallback = page.locator('button,[role="button"]').filter({ hasText: /Open Raid Control Panel/i }).first();
  const failed = page.getByText(/This interaction failed/i).last();

  const find = async () => {
    if (await btnRole.isVisible({ timeout: 300 }).catch(() => false)) return btnRole;
    if (await btnFallback.isVisible({ timeout: 300 }).catch(() => false)) return btnFallback;
    return null;
  };

  // Scroll to bottom so the button (near thread start in a fresh thread) is visible
  await page.evaluate(() => {
    const chat = document.querySelector('[data-list-id="chat-messages"]');
    if (chat) { let s = chat; while (s?.parentElement && !(s.scrollHeight > s.clientHeight + 50)) s = s.parentElement; if (s) s.scrollTop = s.scrollHeight; }
  }).catch(() => null);

  await expect.poll(async () => {
    await page.evaluate(() => {
      const chat = document.querySelector('[data-list-id="chat-messages"]');
      if (chat) { let s = chat; while (s?.parentElement && !(s.scrollHeight > s.clientHeight + 50)) s = s.parentElement; if (s) s.scrollTop = s.scrollHeight; }
    }).catch(() => null);
    return Boolean(await find());
  }, { timeout: 90_000 }).toBe(true);

  const btn = (await find()) || btnFallback;
  await btn.scrollIntoViewIfNeeded().catch(() => null);

  for (let attempt = 0; attempt < 3; attempt++) {
    await page.keyboard.press('Escape').catch(() => null);
    await btn.click({ force: true, noWaitAfter: true, timeout: 15_000 }).catch(() =>
      btn.evaluate(el => el.click()).catch(() => null));
    await page.waitForTimeout(1500);

    const ok = await expect.poll(async () => {
      const d = await page.locator('button,[role="button"]').filter({ hasText: /^DKP$/i }).count();
      const j = await page.locator('button,[role="button"]').filter({ hasText: /^Join Raid$/i }).count();
      const g = await page.locator('button,[role="button"]').filter({ hasText: /^Groups$/i }).count();
      return d + j + g;
    }, { timeout: 15_000 }).toBeGreaterThan(0).then(() => true).catch(() => false);
    if (ok) return;

    if (await failed.isVisible({ timeout: 500 }).catch(() => false)) {
      console.log(`  Interaction failed attempt ${attempt + 1}`);
    }
    await page.waitForTimeout(1000);
  }
  await dumpButtons(page);
  throw new Error('Raid control panel did not appear.');
}

// ── Navigate to DKP manage view ──────────────────────────────────────────────

async function openDkpManageView(page) {
  const dkpBtn = page.locator('button,[role="button"]').filter({ hasText: /^DKP$/i }).first();
  if (await dkpBtn.isVisible({ timeout: 8000 }).catch(() => false)) {
    await dkpBtn.click();
    await page.waitForTimeout(2000);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// TEST: Multi-select DKP Award
// ═══════════════════════════════════════════════════════════════════════════════

test('Award DKP button shows member select and opens DKP adjustment modal', async ({ page }) => {
  ensureEnvAndAuth();
  test.setTimeout(10 * 60_000);

  await loginAndOpenChannel(page);
  const voiceOk = await joinVoice(page);
  test.skip(!voiceOk, 'Voice not available (headless WebRTC). Run with --headed.');

  const raidName = `PW DKP Award ${Date.now()}`;
  await createRaid(page, raidName);
  await openRaidPanel(page);
  // Add the leader as a raid member via Update Team
  console.log('[Award DKP] Clicking Update Team to add leader as member');
  const updateTeam = page.locator('button,[role="button"]').filter({ hasText: /Update Team/i }).first();
  // Button may be off-viewport in the ephemeral panel — use count + scroll
  const hasUpdateTeam = await expect.poll(async () =>
    (await updateTeam.count()) > 0, { timeout: 10_000 }
  ).toBe(true).then(() => true).catch(() => false);
  if (hasUpdateTeam) {
    await updateTeam.scrollIntoViewIfNeeded().catch(() => null);
    await page.waitForTimeout(500);
    await updateTeam.click({ force: true, timeout: 15_000 });
    console.log('[Award DKP] Clicked Update Team');
    await page.waitForTimeout(5000);
    // Re-open panel after Update Team response
    await openRaidPanel(page);
  } else {
    console.log('[Award DKP] Update Team not found — proceeding anyway');
  }

  await openDkpManageView(page);

  // Click "Award DKP"
  console.log('[Award DKP] Clicking Award DKP button');
  const awardBtn = page.locator('button,[role="button"]').filter({ hasText: /^Award DKP$/i }).first();
  await expect(awardBtn).toBeVisible({ timeout: 30_000 });
  await awardBtn.click();
  await page.waitForTimeout(2000);

  // The member select dropdown should appear
  console.log('[Award DKP] Checking for member select');
  const selectText = page.getByText(/Select member\(s\) to award DKP/i).first();
  const hasSelect = await selectText.isVisible({ timeout: 15_000 }).catch(() => false);

  if (hasSelect) {
    console.log('[Award DKP] Member select visible — clicking to open dropdown');
    // Click the Discord select component to open the dropdown
    const selectComponent = selectText.locator('xpath=ancestor::div[.//div[@role="listbox" or @role="menu"]]').first();
    const selectFallback = page.locator('div[class*="select" i], div[class*="Select"]').filter({ has: selectText }).first();
    const target = (await selectComponent.count()) > 0 ? selectComponent
      : (await selectFallback.count()) > 0 ? selectFallback
      : selectText;
    await target.click();
    await page.waitForTimeout(1500);

    const options = page.locator('[role="option"]');
    const optCount = await options.count();
    console.log(`[Award DKP] Found ${optCount} member option(s)`);

    // In a fresh single-user raid, there should be at least 1 option (the leader)
    expect(optCount).toBeGreaterThanOrEqual(1);

    // Select the first option
    await options.first().click();
    await page.waitForTimeout(1000);

    // The DKP Adjustment modal should appear
    console.log('[Award DKP] Waiting for DKP Adjustment modal');
    const modal = page.getByRole('dialog').filter({ hasText: /DKP|Amount|Reason/i }).first();
    const modalVisible = await modal.isVisible({ timeout: 15_000 }).catch(() => false);

    if (modalVisible) {
      console.log('[Award DKP] Modal appeared — verifying fields');
      const amount = modal.getByLabel(/Amount/i).first();
      const reason = modal.getByLabel(/Reason/i).first();
      await expect(amount).toBeVisible({ timeout: 5000 });
      await expect(reason).toBeVisible({ timeout: 5000 });

      await amount.fill('10');
      await reason.fill('PW E2E test award');
      await modal.getByRole('button', { name: /submit/i }).first().click();

      // Wait for success confirmation in the thread
      await expect.poll(async () =>
        await page.getByText(/awarded.*DKP/i).count(),
      { timeout: 30_000 }).toBeGreaterThan(0);
      console.log('[Award DKP] PASS — DKP awarded successfully');
    } else {
      await dumpButtons(page);
      expect(modalVisible, '[Award DKP] Modal did not appear after member selection').toBe(true);
    }
  } else {
    // If no member select, Award DKP may have opened a modal directly (single-member shortcut)
    console.log('[Award DKP] No member select — checking for direct modal');
    const modal = page.getByRole('dialog').filter({ hasText: /DKP|Amount|Reason/i }).first();
    const modalVisible = await modal.isVisible({ timeout: 10_000 }).catch(() => false);
    expect(modalVisible).toBe(true);
    console.log('[Award DKP] PASS — direct modal opened');
    await page.keyboard.press('Escape'); // close without submitting
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// TEST: Groups view + bulk ungrouped
// ═══════════════════════════════════════════════════════════════════════════════

test('Groups view shows group signups and bulk ungrouped button when applicable', async ({ page }) => {
  ensureEnvAndAuth();
  test.setTimeout(10 * 60_000);

  await loginAndOpenChannel(page);
  const voiceOk = await joinVoice(page);
  test.skip(!voiceOk, 'Voice not available (headless WebRTC). Run with --headed.');

  const raidName = `PW Groups ${Date.now()}`;
  await createRaid(page, raidName);
  await openRaidPanel(page);

  // Navigate to Groups view
  console.log('[Groups] Clicking Groups button');
  let groupsBtn = page.locator('button,[role="button"]').filter({ hasText: /^Groups$/i }).first();
  if (!(await groupsBtn.isVisible({ timeout: 5000 }).catch(() => false))) {
    await openRaidPanel(page);
  }
  await expect(groupsBtn).toBeVisible({ timeout: 15_000 });
  await groupsBtn.click();
  await page.waitForTimeout(2000);

  // Groups button opens a "Set Up Raid Groups" modal first
  console.log('[Groups] Handling Set Up Raid Groups modal');
  const setupModal = page.getByRole('dialog', { name: /Set Up Raid Groups/i });
  const hasSetupModal = await setupModal.isVisible({ timeout: 10_000 }).catch(() => false);

  if (hasSetupModal) {
    console.log('[Groups] Setup modal appeared — entering 2 groups');
    const numInput = setupModal.getByRole('textbox', { name: /Number of groups/i }).first();
    await expect(numInput).toBeVisible({ timeout: 5000 });
    await numInput.fill('2');
    await setupModal.getByRole('button', { name: /Submit/i }).click();
    await page.waitForTimeout(3000);
  }

  // After setup, the Group Signups view should appear (either in-panel or as updated ephemeral)
  console.log('[Groups] Checking for Group Signups');
  const signups = page.getByText(/Group Signups|Group 1|Ungrouped/i).first();
  await expect(signups).toBeVisible({ timeout: 15_000 });
  console.log('[Groups] Group Signups visible');

  // Check for Ungrouped and bulk assign buttons
  const ungroupedBtn = page.locator('button,[role="button"]').filter({ hasText: /Ungrouped/i }).first();
  const bulkBtn = page.locator('button,[role="button"]').filter({ hasText: /Add all ungrouped/i }).first();
  const hasUngrouped = await ungroupedBtn.isVisible({ timeout: 5000 }).catch(() => false);
  const hasBulk = await bulkBtn.isVisible({ timeout: 5000 }).catch(() => false);
  console.log(`[Groups] Ungrouped visible: ${hasUngrouped}, Bulk assign visible: ${hasBulk}`);

  if (hasBulk) {
    console.log('[Groups] Clicking bulk assign');
    await bulkBtn.click();
    await expect.poll(async () => {
      const assigned = await page.getByText(/Added.*ungrouped member/i).count();
      const noGrouped = await page.getByText(/At least one group must already have members/i).count();
      const refreshed = await page.getByText(/Group Signups/i).count();
      return assigned + noGrouped + refreshed;
    }, { timeout: 30_000 }).toBeGreaterThan(0);
    console.log('[Groups] PASS — bulk ungrouped responded');
  } else {
    console.log('[Groups] PASS — bulk assign not shown (expected for fresh raid with no grouped members)');
  }

  await dumpButtons(page);
});
