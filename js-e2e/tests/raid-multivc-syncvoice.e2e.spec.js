import { test, expect } from '@playwright/test';
import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRootEnvPath = path.resolve(__dirname, '../../.env');
dotenv.config({ path: projectRootEnvPath, override: true });

const storageRoot = path.resolve(__dirname, '..');
const storageState1 = path.join(storageRoot, 'discord-auth.json');
const storageState2 = path.join(storageRoot, 'discord-auth-2.json');

const SERVER = process.env.DISCORD_TEST_SERVER_NAME;
const CHANNEL = process.env.DISCORD_TEST_CHANNEL_NAME;
const USERNAME2 = (process.env.DISCORD_TEST_USERNAME_2 || 'sc_dkp2').trim();
const VOICE_CHANNEL = (process.env.DISCORD_TEST_VOICE_CHANNEL_NAME || 'General').trim();

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function ensureEnvAndAuth() {
  if (!SERVER || !CHANNEL) {
    test.skip(true, 'DISCORD_TEST_SERVER_NAME and DISCORD_TEST_CHANNEL_NAME must be set.');
  }

  if (!fs.existsSync(storageState1)) {
    test.skip(
      true,
      'discord-auth.json not found. Run DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed from js-e2e/ to create it.',
    );
  }

  if (!fs.existsSync(storageState2)) {
    test.skip(
      true,
      'discord-auth-2.json not found. Run DISCORD_SETUP_AUTH=1 DISCORD_AUTH_STATE_PATH=discord-auth-2.json npx playwright test tests/setup-discord-auth.spec.js --headed from js-e2e/ to create it (log in as your second test account).',
    );
  }
}

function getUserIdFromStorageState(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    const parsed = JSON.parse(raw);
    const origins = Array.isArray(parsed.origins) ? parsed.origins : [];
    const discordOrigin = origins.find((o) => o && typeof o.origin === 'string' && /https:\/\/discord\.com/i.test(o.origin));
    if (!discordOrigin || !Array.isArray(discordOrigin.localStorage)) return null;
    const entry = discordOrigin.localStorage.find((kv) => kv && kv.name === 'user_id_cache');
    if (!entry || typeof entry.value !== 'string') return null;
    try {
      return JSON.parse(entry.value);
    } catch {
      return entry.value.replace(/^"|"$/g, '') || null;
    }
  } catch {
    return null;
  }
}

async function getMessageBox(page) {
  const named = page.getByRole('textbox', { name: /message/i }).first();
  if (await named.count()) return named;

  const editable = page.locator('div[role="textbox"][contenteditable="true"]').first();
  if (await editable.count()) return editable;

  return page.getByRole('textbox').first();
}

function assertDifferentAccountsFromStorageState() {
  const id1 = getUserIdFromStorageState(storageState1);
  const id2 = getUserIdFromStorageState(storageState2);
  if (!id1 || !id2) return;
  if (String(id1) === String(id2)) {
    throw new Error(
      'Both Playwright storageState files appear to be for the same Discord account.\n\n'
        + 'Regenerate BOTH auth states using fresh contexts:\n'
        + '- User #1: DISCORD_SETUP_AUTH=1 DISCORD_AUTH_STATE_PATH=discord-auth.json npx playwright test tests/setup-discord-auth.spec.js --headed\n'
        + '- User #2: DISCORD_SETUP_AUTH=1 DISCORD_AUTH_STATE_PATH=discord-auth-2.json npx playwright test tests/setup-discord-auth.spec.js --headed\n\n'
        + 'Important: in each run, log in ONLY the intended account and then close the Playwright Inspector so it saves the file.',
    );
  }
}

async function loginAndOpenChannel(page) {
  await page.goto('https://discord.com/app', { timeout: 60000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  const currentUrl = page.url();
  if (/discord\.com\/login/i.test(currentUrl)) {
    throw new Error(
      'Discord login page detected. The storageState did not load for this account. Regenerate discord-auth.json / discord-auth-2.json from js-e2e/ using tests/setup-discord-auth.spec.js.',
    );
  }

  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 5000 }).catch(() => false)) {
    throw new Error(
      'Discord login page detected. The storageState did not load for this account. Regenerate discord-auth.json / discord-auth-2.json from js-e2e/ using tests/setup-discord-auth.spec.js.',
    );
  }

  const chooseAccount = page.getByRole('heading', { name: 'Choose an account' });
  if (await chooseAccount.isVisible({ timeout: 1500 }).catch(() => false)) {
    throw new Error(
      'Discord login chooser detected. The storageState did not load for this account. Regenerate discord-auth.json / discord-auth-2.json from js-e2e/ using tests/setup-discord-auth.spec.js.',
    );
  }

  const serverTreeItem = page.getByRole('treeitem', { name: SERVER });
  await serverTreeItem.first().waitFor({ state: 'visible', timeout: 45000 });
  await serverTreeItem.first().click({ timeout: 45000 });
  await page.waitForTimeout(2000);

  const channelPattern = new RegExp(`^(unread,\\s*)?${escapeRegExp(CHANNEL)}(\\b|\\s|\\().*`, 'i');
  const channelLink = page.getByRole('link', { name: channelPattern }).first();
  await channelLink.waitFor({ state: 'visible', timeout: 45000 });
  await channelLink.click({ timeout: 45000 });
  await page.waitForTimeout(2000);
}

async function ensureDkpSetup(page) {
  const messageBox = await getMessageBox(page);
  await messageBox.click();
  await messageBox.fill('/setup_dkp');

  const setupOption = page.getByRole('option', { name: /\/setup_dkp/ }).first();
  await setupOption.click();
  await messageBox.press('Enter');

  const setupComplete = page.getByText('DKP system setup complete!', { exact: false }).first();
  const setupRepaired = page.getByText('Setup repaired', { exact: false }).first();
  const setupExists = page.getByText('Setup already exists', { exact: false }).first();
  const setupMissingPerms = page.getByText('Missing permissions', { exact: false }).first();
  const setupNoPerms = page.getByText("You don't have permission to use this command.", { exact: false }).first();
  const setupGenericError = page.getByText('An error occurred while processing that command.', { exact: false }).first();

  await Promise.race([
    setupComplete.waitFor({ state: 'visible', timeout: 45000 }),
    setupRepaired.waitFor({ state: 'visible', timeout: 45000 }),
    setupExists.waitFor({ state: 'visible', timeout: 45000 }),
    setupMissingPerms.waitFor({ state: 'visible', timeout: 45000 }),
    setupNoPerms.waitFor({ state: 'visible', timeout: 45000 }),
    setupGenericError.waitFor({ state: 'visible', timeout: 45000 }),
  ]);
}

async function joinAnyVoiceChannel(page) {
  try {
    await page.context().grantPermissions(['microphone'], { origin: 'https://discord.com' });
  } catch {
  }

  const voiceButtonPattern = new RegExp(`^${escapeRegExp(VOICE_CHANNEL)} \\(voice channel\\)`, 'i');
  let voiceEntry = page.getByRole('button', { name: voiceButtonPattern }).first();
  if ((await voiceEntry.count()) === 0) {
    const voicePattern = new RegExp(escapeRegExp(VOICE_CHANNEL), 'i');
    voiceEntry = page.getByRole('button', { name: voicePattern }).first();
  }
  if ((await voiceEntry.count()) === 0) {
    const voicePattern = new RegExp(escapeRegExp(VOICE_CHANNEL), 'i');
    voiceEntry = page.getByRole('treeitem', { name: voicePattern }).first();
  }
  if ((await voiceEntry.count()) === 0) {
    return false;
  }

  await voiceEntry.click();

  const connectButton = page.getByRole('button', { name: /join voice|join call|connect/i }).first();
  if (await connectButton.isVisible({ timeout: 5000 }).catch(() => false)) {
    await connectButton.click();
  }

  const disconnectButton = page.getByRole('button', { name: /disconnect/i }).first();
  const connectedText = page.getByText(/voice connected|connected/i).first();

  try {
    await Promise.race([
      disconnectButton.waitFor({ state: 'visible', timeout: 15000 }),
      connectedText.waitFor({ state: 'visible', timeout: 15000 }),
    ]);
    return true;
  } catch {
    return false;
  }
}

async function createRaidAndOpenLogThread(page, raidName) {
  const messageBox = await getMessageBox(page);
  const modal = page.getByRole('dialog', { name: 'Create New Raid' });

  for (let attempt = 0; attempt < 2; attempt += 1) {
    await messageBox.click();
    await messageBox.fill('/raid_create');
    const raidCreateOption = page.getByRole('option', { name: /\/raid_create/ }).first();
    await raidCreateOption.click();
    await messageBox.press('Enter');

    try {
      await expect(modal).toBeVisible({ timeout: 15000 });
      break;
    } catch {
      const setupError = page.getByText('Setup Error', { exact: false }).first();
      const setupIncomplete = page.getByText('Setup Incomplete', { exact: false }).first();
      const noPerm = page.getByText("don't have permission", { exact: false }).first();

      if (await noPerm.isVisible().catch(() => false)) {
        throw new Error('Cannot run /raid_create as this test user (missing permissions).');
      }

      const setupBroken =
        (await setupError.isVisible().catch(() => false)) ||
        (await setupIncomplete.isVisible().catch(() => false));

      if (setupBroken && attempt === 0) {
        await ensureDkpSetup(page);
        continue;
      }

      if (setupBroken) {
        throw new Error('Raid creation failed due to DKP setup error.');
      }

      throw new Error('Create New Raid modal did not appear after running /raid_create.');
    }
  }

  const raidNameInput = modal.getByLabel('Raid Name');
  await raidNameInput.fill(raidName);

  const submitButton = modal.getByRole('button', { name: 'Submit' });
  await submitButton.click();

  const unreadActiveRaids = page.getByRole('link', { name: /unread, active-raids/i });
  if (await unreadActiveRaids.count()) {
    await unreadActiveRaids.first().click();
  } else {
    await page.getByRole('link', { name: /active-raids.*text channel/i }).last().click();
  }

  const unreadThreadButton = page
    .getByRole('button', { name: new RegExp(`^unread,\\s*${escapeRegExp(raidName)}.*Raid Log.*\\(thread\\)$`, 'i') })
    .first();
  if (await unreadThreadButton.isVisible({ timeout: 8000 }).catch(() => false)) {
    await unreadThreadButton.click();
  } else {
    const threadButton = page
      .getByRole('button', { name: new RegExp(`${escapeRegExp(raidName)}.*Raid Log.*\\(thread\\)`, 'i') })
      .last();
    await expect(threadButton).toBeVisible({ timeout: 45000 });
    await threadButton.click();
  }

  const threadHeading = page.getByRole('heading', {
    name: new RegExp(`Thread:.*${escapeRegExp(raidName)}.*Raid Log`, 'i'),
  });
  await expect(threadHeading).toBeVisible({ timeout: 15000 });
}

async function linkVoiceChannelToRaid(page) {
  const messageBox = await getMessageBox(page);
  await messageBox.click();
  await messageBox.fill('/raid_add_voice_channel');

  const cmdOption = page.getByRole('option', { name: /\/raid_add_voice_channel/ }).first();
  await cmdOption.click();

  await page.waitForTimeout(500);

  const channelArg = page.getByRole('button', { name: /channel/i }).first();
  if (await channelArg.isVisible({ timeout: 2000 }).catch(() => false)) {
    await channelArg.click({ timeout: 5000 });
  } else {
    await page.keyboard.press('Tab').catch(() => {});
  }

  await page.keyboard.type(VOICE_CHANNEL, { delay: 30 });

  let vcOption = page.getByRole('option', { name: new RegExp(escapeRegExp(VOICE_CHANNEL), 'i') }).first();
  let found = await vcOption.isVisible({ timeout: 8000 }).catch(() => false);
  if (!found) {
    await page.keyboard.press('ControlOrMeta+A').catch(() => {});
    await page.keyboard.type(`#${VOICE_CHANNEL}`, { delay: 30 });
    vcOption = page.getByRole('option', { name: new RegExp(escapeRegExp(VOICE_CHANNEL), 'i') }).first();
    found = await vcOption.isVisible({ timeout: 8000 }).catch(() => false);
  }

  if (!found) {
    const voiceArgButton = page.getByRole('button', { name: /voice|channel/i }).first();
    if (await voiceArgButton.isVisible({ timeout: 1500 }).catch(() => false)) {
      await voiceArgButton.click();
      await page.keyboard.type(VOICE_CHANNEL, { delay: 30 });
      vcOption = page.getByRole('option', { name: new RegExp(escapeRegExp(VOICE_CHANNEL), 'i') }).first();
      found = await vcOption.isVisible({ timeout: 8000 }).catch(() => false);
    }
  }

  if (!found) {
    const options = await page.locator('[role="option"]').allInnerTexts().catch(() => []);
    const buttons = await page.locator('[role="button"]').allInnerTexts().catch(() => []);
    throw new Error(
      `Voice channel option not found for ${VOICE_CHANNEL}. Visible options: ${options.slice(0, 20).join(' | ')}. Visible buttons: ${buttons.slice(0, 20).join(' | ')}`,
    );
  }

  await vcOption.click();

  await messageBox.press('Enter');

  const confirmText = page.getByText('Linked voice channel', { exact: false }).first();
  await expect(confirmText).toBeVisible({ timeout: 45000 });
}

async function listLinkedVoiceChannels(page) {
  const messageBox = await getMessageBox(page);
  await messageBox.click();
  await messageBox.fill('/raid_list_voice_channels');

  const cmdOption = page.getByRole('option', { name: /\/raid_list_voice_channels/ }).first();
  await cmdOption.click();
  await messageBox.press('Enter');

  await expect(page.getByText('Linked Raid Voice Channels', { exact: false }).first()).toBeVisible({ timeout: 45000 });
  await expect(page.getByText(VOICE_CHANNEL, { exact: false }).first()).toBeVisible({ timeout: 45000 });
}

async function syncRaidWithVoice(page) {
  const messageBox = await getMessageBox(page);
  await messageBox.click();
  await messageBox.fill('/raid_sync_voice');

  const cmdOption = page.getByRole('option', { name: /\/raid_sync_voice/ }).first();
  await cmdOption.click();
  await messageBox.press('Enter');

  await expect(page.getByText('Sync Voice complete.', { exact: false }).first()).toBeVisible({ timeout: 45000 });
}

test('multi-VC linking + Sync Voice adds members from linked VC', async ({ browser }) => {
  ensureEnvAndAuth();
  assertDifferentAccountsFromStorageState();

  test.setTimeout(5 * 60_000);

  const context1 = await browser.newContext({ storageState: storageState1 });
  const context2 = await browser.newContext({ storageState: storageState2 });

  const page1 = await context1.newPage();
  const page2 = await context2.newPage();

  page1.setDefaultTimeout(45_000);
  page2.setDefaultTimeout(45_000);
  page1.setDefaultNavigationTimeout(60_000);
  page2.setDefaultNavigationTimeout(60_000);

  const raidName = `Playwright Multi-VC Sync ${Date.now()}`;

  try {
    await loginAndOpenChannel(page1);
    await ensureDkpSetup(page1);
    await createRaidAndOpenLogThread(page1, raidName);

    await linkVoiceChannelToRaid(page1);
    await listLinkedVoiceChannels(page1);

    await loginAndOpenChannel(page2);
    const voiceOk = await joinAnyVoiceChannel(page2);
    test.skip(!voiceOk, 'Could not connect to Discord voice in this environment (headless WebRTC).');

    await syncRaidWithVoice(page1);

    await expect(page1.getByText('Current Raid Team', { exact: false }).first()).toBeVisible({ timeout: 45000 });
    await expect(page1.getByText(USERNAME2, { exact: false }).first()).toBeVisible({ timeout: 45000 });
  } finally {
    await context2.close().catch(() => {});
    await context1.close().catch(() => {});
  }
});
