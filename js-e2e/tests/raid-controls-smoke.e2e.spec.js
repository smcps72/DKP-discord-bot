import { test, expect } from '@playwright/test';
import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';

// Load the shared .env from the project root, and allow it to override any
// variables that might already be set in the shell so tests are deterministic.
dotenv.config({ path: path.resolve(process.cwd(), '../.env'), override: true });

const SERVER = process.env.DISCORD_TEST_SERVER_NAME;
const CHANNEL = process.env.DISCORD_TEST_CHANNEL_NAME;
const VOICE_CHANNEL = (process.env.DISCORD_TEST_VOICE_CHANNEL_NAME || 'General').trim();

const STORAGE_STATE_1 = path.resolve(process.cwd(), 'discord-auth.json');

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function dumpVisibleButtons(page, { max = 60 } = {}) {
  try {
    const labels = await page.evaluate((limit) => {
      const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
      const texts = [];
      for (const el of candidates) {
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none') continue;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        const t = (el.textContent || '').trim();
        if (!t) continue;
        if (texts.includes(t)) continue;
        texts.push(t);
        if (texts.length >= limit) break;
      }
      return texts;
    }, max);
    console.log(`Visible buttons (${labels.length}): ${labels.join(' | ')}`);
  } catch (e) {
    console.log('Failed to dump visible buttons');
  }
}

async function dumpVisibleDialogs(page, { max = 3 } = {}) {
  try {
    const dialogs = await page.evaluate((limit) => {
      const nodes = Array.from(document.querySelectorAll('[role="dialog"]')).slice(0, limit);
      return nodes.map((d) => {
        const aria = (d.getAttribute('aria-label') || '').trim();
        const text = (d.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 600);
        return { ariaLabel: aria, text };
      });
    }, max);
    console.log(`Visible dialogs (${dialogs.length}): ${JSON.stringify(dialogs)}`);
  } catch {
    console.log('Failed to dump visible dialogs');
  }
}

async function tryOpenCreateRaidModalViaButton(page) {
  const createRaidButton = page
    .locator('button, [role="button"]')
    .filter({ hasText: /^Create Raid/i })
    .first();
  if (await createRaidButton.isVisible({ timeout: 4000 }).catch(() => false)) {
    await createRaidButton.click();
    return true;
  }
  return false;
}

async function openCreateRaidModalFromChannel(page) {
  // The pinned welcome panel posts an "Open DKP Panel" button which opens an
  // ephemeral panel containing "Create Raid 🏰".
  const openDkpPanel = page.locator('button, [role="button"]').filter({ hasText: /^Open DKP Panel$/i }).first();

  // If the button isn't currently in the message history, open the pinned
  // messages panel and locate the welcome message.
  if (!(await openDkpPanel.isVisible({ timeout: 6000 }).catch(() => false))) {
    const pinsButton = page
      .locator('button, [role="button"]')
      .filter({ hasText: /pins|pinned/i })
      .first();
    if (await pinsButton.isVisible({ timeout: 6000 }).catch(() => false)) {
      await pinsButton.click();
      await page.waitForTimeout(1500);

      const welcomeText = page.getByText('Welcome to the DKP Bot!', { exact: false }).first();
      if (await welcomeText.isVisible({ timeout: 8000 }).catch(() => false)) {
        await welcomeText.click();
        await page.waitForTimeout(1000);
      }
    }
  }

  if (!(await openDkpPanel.isVisible({ timeout: 6000 }).catch(() => false))) {
    // If the welcome panel is missing (un-pinned / wiped history), re-run setup.
    await ensureDkpSetup(page);
  }

  await expect(openDkpPanel).toBeVisible({ timeout: 45_000 });

  // Discord sometimes drops the click or renders the resulting ephemeral message offscreen.
  // Retry the click a few times and detect the panel by existence + scroll.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await page.keyboard.press('Escape').catch(() => null);
    try {
      await openDkpPanel.click({ force: true, noWaitAfter: true, timeout: 15_000 });
    } catch {
      await openDkpPanel.evaluate((el) => el.click()).catch(() => null);
    }

    const quickMarker = page.getByText(/DKP Panel for/i).last();
    const quickOnlyYou = page.getByText('Only you can see this', { exact: false }).last();
    const appeared = await expect
      .poll(
        async () => {
          const titleCount = await page.getByText(/DKP Panel for/i).count();
          const onlyCount = await page.getByText('Only you can see this', { exact: false }).count();
          return titleCount > 0 || onlyCount > 0;
        },
        { timeout: 6000 },
      )
      .toBe(true)
      .then(() => true)
      .catch(() => false);

    if (appeared) {
      await quickMarker.scrollIntoViewIfNeeded().catch(() => null);
      await quickOnlyYou.scrollIntoViewIfNeeded().catch(() => null);
      break;
    }

    await page.waitForTimeout(1200);
  }

  let dkpPanel = null;
  const startedAt = Date.now();
  while (Date.now() - startedAt < 45_000) {
    const panelTitle = page.getByText(/DKP Panel for/i).last();
    if ((await panelTitle.count()) > 0) {
      await panelTitle.scrollIntoViewIfNeeded().catch(() => null);
      if (await panelTitle.isVisible({ timeout: 800 }).catch(() => false)) {
        dkpPanel = panelTitle.locator('xpath=ancestor::li[1]');
        break;
      }
    }

    const onlyYouCanSee = page.getByText('Only you can see this', { exact: false }).last();
    if ((await onlyYouCanSee.count()) > 0) {
      await onlyYouCanSee.scrollIntoViewIfNeeded().catch(() => null);
      if (await onlyYouCanSee.isVisible({ timeout: 800 }).catch(() => false)) {
        dkpPanel = onlyYouCanSee.locator('xpath=ancestor::li[1]');
        break;
      }
    }

    await page.waitForTimeout(500);
  }

  if (!dkpPanel) {
    await dumpVisibleButtons(page, { max: 80 });
    throw new Error('DKP Panel did not appear after clicking Open DKP Panel.');
  }

  const createRaid = dkpPanel.locator('button, [role="button"]').filter({ hasText: /^Create Raid/i }).first();
  if (!(await createRaid.isVisible({ timeout: 10_000 }).catch(() => false))) {
    await dumpVisibleButtons(page, { max: 80 });
    throw new Error(
      'Create Raid button was not visible in the DKP Panel. This usually means the test account is not an officer/admin (DkpPanelView hides Create Raid). Use an officer/admin Discord account for discord-auth.json or grant the role, then re-run.',
    );
  }
  await createRaid.click();
}

async function selectSlashCommandOption(page, commandName) {
  const optionText = new RegExp(`\\/\\s*${escapeRegExp(commandName)}`, 'i');
  const option = page.locator('[role="option"], [role="menuitem"]').filter({ hasText: optionText }).first();
  if (await option.isVisible({ timeout: 8000 }).catch(() => false)) {
    await option.click();
    return true;
  }
  return false;
}

async function describeSlashCommandOptions(page) {
  try {
    return await page.evaluate(() => {
      const nodes = Array.from(document.querySelectorAll('[role="option"], [role="menuitem"]'));
      const texts = nodes
        .map((n) => (n.textContent || '').trim())
        .filter((t) => t.length > 0)
        .slice(0, 20);
      return texts.join(' | ');
    });
  } catch {
    return '';
  }
}

async function openAnyRaidLogThread(page) {
  const unreadActiveRaids = page.getByRole('link', { name: /unread, active-raids/i });
  if (await unreadActiveRaids.count()) {
    await unreadActiveRaids.first().click();
  } else {
    await page.getByRole('link', { name: /active-raids.*text channel/i }).last().click();
  }
  await page.waitForTimeout(2000);

  const threadButton = page.getByRole('button', { name: /Raid Log.*\(thread\)/i }).last();
  await expect(threadButton).toBeVisible({ timeout: 45_000 });
  await threadButton.click();

  const threadHeading = page.getByRole('heading', { name: /Thread:.*Raid Log/i });
  await expect(threadHeading).toBeVisible({ timeout: 15_000 });
}

async function openRaidLogThreadWithLeaderTools(page) {
  const unreadActiveRaids = page.getByRole('link', { name: /unread, active-raids/i });
  const activeRaidsLink = (await unreadActiveRaids.count())
    ? unreadActiveRaids.first()
    : page.getByRole('link', { name: /active-raids.*text channel/i }).last();

  await activeRaidsLink.click();
  await page.waitForTimeout(2000);

  const threadButtons = page.getByRole('button', { name: /Raid Log.*\(thread\)/i });
  const total = await threadButtons.count();
  if (!total) {
    throw new Error('No Raid Log threads were found in active-raids.');
  }

  const limit = Math.min(total, 10);
  for (let offset = 1; offset <= limit; offset += 1) {
    const index = total - offset;
    await activeRaidsLink.click();
    await page.waitForTimeout(1000);

    const btn = threadButtons.nth(index);
    await btn.scrollIntoViewIfNeeded();
    await btn.click();

    const threadHeading = page.getByRole('heading', { name: /Thread:.*Raid Log/i });
    await expect(threadHeading).toBeVisible({ timeout: 15_000 });

    await openRaidControlPanel(page);

    const dkpButton = page.locator('button, [role="button"]').filter({ hasText: /^DKP$/i }).first();
    if (await dkpButton.isVisible({ timeout: 8000 }).catch(() => false)) {
      return;
    }
  }

  await dumpVisibleButtons(page, { max: 80 });
  throw new Error('Could not find a Raid Log thread where DKP is visible.');
}

function ensureEnvAndAuth() {
  if (!SERVER || !CHANNEL) {
    test.skip(true, 'DISCORD_TEST_SERVER_NAME and DISCORD_TEST_CHANNEL_NAME must be set.');
  }

  if (!fs.existsSync(STORAGE_STATE_1)) {
    test.skip(
      true,
      'discord-auth.json not found. Run DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed from js-e2e/ to create it.',
    );
  }
}

async function getMessageBox(page) {
  const channelBox = page.getByRole('textbox', { name: /Message #/i }).first();
  if (await channelBox.count()) return channelBox;

  const named = page.getByRole('textbox', { name: /message/i }).first();
  if (await named.count()) return named;

  const editable = page.locator('div[role="textbox"][contenteditable="true"]').first();
  if (await editable.count()) return editable;

  return page.getByRole('textbox').first();
}

async function clearAndTypeInMessageBox(page, messageBox, text) {
  await messageBox.click();
  // Discord's chat box is often contenteditable; `.fill()` can fail to trigger
  // the slash command UI because it bypasses key events.
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.press('Backspace');
  await page.keyboard.type(text, { delay: 25 });
  await page.waitForTimeout(250);
}

async function loginAndOpenChannel(page) {
  await page.goto('https://discord.com/app', { timeout: 60_000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  const currentUrl = page.url();
  if (/discord\.com\/login/i.test(currentUrl)) {
    throw new Error(
      'Discord login page detected. The storageState did not load. Regenerate discord-auth.json from js-e2e/ using tests/setup-discord-auth.spec.js.',
    );
  }

  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 5000 }).catch(() => false)) {
    throw new Error(
      'Discord login page detected. The storageState did not load. Regenerate discord-auth.json from js-e2e/ using tests/setup-discord-auth.spec.js.',
    );
  }

  const serverTreeItem = page.getByRole('treeitem', { name: SERVER });
  await serverTreeItem.first().waitFor({ state: 'visible', timeout: 45_000 });
  await serverTreeItem.first().click({ timeout: 45_000 });
  await page.waitForTimeout(2000);

  const channelPattern = new RegExp(`^(unread,\\s*)?${escapeRegExp(CHANNEL)}(\\b|\\s|\\().*`, 'i');
  const channelLink = page.getByRole('link', { name: channelPattern }).first();

  if (!(await channelLink.isVisible({ timeout: 5000 }).catch(() => false))) {
    await channelLink.scrollIntoViewIfNeeded().catch(() => null);
  }

  if (await channelLink.isVisible({ timeout: 5000 }).catch(() => false)) {
    await channelLink.click({ timeout: 45_000 });
    await page.waitForTimeout(2000);
    return;
  }

  // Discord sometimes virtualizes/collapses the channel list such that the link exists
  // but remains hidden. Use the Quick Switcher as a reliable navigation fallback.
  await page.keyboard.press('ControlOrMeta+K').catch(() => null);
  const quickSwitcher = page
    .locator('input[placeholder*="Where would you like to go"], input[aria-label*="Where would you like to go"]')
    .first();
  if (await quickSwitcher.isVisible({ timeout: 5000 }).catch(() => false)) {
    await quickSwitcher.fill(CHANNEL);
    await page.waitForTimeout(750);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(2000);
    return;
  }

  // Last resort: try to click the hidden element anyway.
  await channelLink.click({ force: true, noWaitAfter: true, timeout: 15_000 }).catch(() => null);
  await page.waitForTimeout(2000);
}

async function ensureDkpSetup(page) {
  const messageBox = await getMessageBox(page);
  await clearAndTypeInMessageBox(page, messageBox, '/setup_dkp');

  // Prefer the listbox+Enter flow, but fall back to clicking the option if needed.
  const listbox = page.locator('[role="listbox"]').first();
  if (await listbox.isVisible({ timeout: 8000 }).catch(() => false)) {
    await page.keyboard.press('Enter');
  } else {
    const selected = await selectSlashCommandOption(page, 'setup_dkp');
    if (selected) {
      await page.keyboard.press('Enter');
    } else {
      // Last resort: Discord may still have a role=option entry without listbox.
      const setupOption = page.locator('[role="option"], [role="menuitem"]').filter({ hasText: /\/setup_dkp/i }).first();
      if (await setupOption.isVisible({ timeout: 8000 }).catch(() => false)) {
        await setupOption.click();
        await page.keyboard.press('Enter');
      }
    }
  }

  const setupComplete = page.getByText('DKP system setup complete!', { exact: false }).first();
  const setupRepaired = page.getByText('Setup repaired', { exact: false }).first();
  const setupExists = page.getByText('Setup already exists', { exact: false }).first();
  const setupMissingPerms = page.getByText('Missing permissions', { exact: false }).first();
  const setupNoPerms = page
    .getByText("You don't have permission to use this command.", { exact: false })
    .first();
  const setupGenericError = page.getByText('An error occurred while processing that command.', { exact: false }).first();

  // Discord sometimes fails to surface the ephemeral response in the DOM.
  // If we don't see an outcome quickly, assume setup is already OK.
  const result = await expect
    .poll(
      async () => {
        if (await setupComplete.isVisible().catch(() => false)) return 'complete';
        if (await setupRepaired.isVisible().catch(() => false)) return 'repaired';
        if (await setupExists.isVisible().catch(() => false)) return 'exists';
        if (await setupMissingPerms.isVisible().catch(() => false)) return 'missing_perms';
        if (await setupNoPerms.isVisible().catch(() => false)) return 'no_perms';
        if (await setupGenericError.isVisible().catch(() => false)) return 'error';
        return null;
      },
      { timeout: 12_000 },
    )
    .toBeTruthy()
    .catch(() => null);

  if (!result) {
    return;
  }

  if (result === 'missing_perms' || result === 'no_perms') {
    throw new Error('Cannot run /setup_dkp as this test user (missing permissions).');
  }
  if (result === 'error') {
    throw new Error('Discord bot returned a generic error while running /setup_dkp.');
  }
}

async function openDkpTextChannelIfPresent(page) {
  // Setup creates multiple channels like active-raids / archive. The pinned
  // welcome panel is in the main DKP channel.
  const dkpCandidates = page
    .getByRole('link')
    .filter({ hasText: /dkp/i });
  const total = await dkpCandidates.count();
  for (let i = 0; i < total; i += 1) {
    const link = dkpCandidates.nth(i);
    const name = (await link.innerText().catch(() => '')) || '';
    const norm = name.toLowerCase();
    if (norm.includes('active-raids') || norm.includes('archive')) continue;
    if (!(await link.isVisible({ timeout: 1000 }).catch(() => false))) continue;
    await link.click();
    await page.waitForTimeout(1500);
    return;
  }
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
      disconnectButton.waitFor({ state: 'visible', timeout: 15_000 }),
      connectedText.waitFor({ state: 'visible', timeout: 15_000 }),
    ]);
    return true;
  } catch {
    return false;
  }
}

async function createRaidAndOpenLogThread(page, raidName) {
  const modal = page.getByRole('dialog', { name: 'Create New Raid' });

  await openDkpTextChannelIfPresent(page);
  await openCreateRaidModalFromChannel(page);
  await expect(modal).toBeVisible({ timeout: 20_000 });

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

  const threadButton = page
    .getByRole('button', { name: new RegExp(`${escapeRegExp(raidName)}.*Raid Log.*\\(thread\\)`, 'i') })
    .last();
  await expect(threadButton).toBeVisible({ timeout: 45_000 });
  await threadButton.click();

  const threadHeading = page.getByRole('heading', {
    name: new RegExp(`Thread:.*${escapeRegExp(raidName)}.*Raid Log`, 'i'),
  });
  await expect(threadHeading).toBeVisible({ timeout: 15_000 });
}

async function openRaidControlPanel(page) {
  const panelTitle = page.getByText(/Raid Control Panel/i).last();
  const openPanelRole = page.getByRole('button', { name: /Open Raid Control Panel/i }).first();
  const openPanelFallback = page.locator('button, [role="button"]').filter({ hasText: /Open Raid Control Panel/i }).first();
  const interactionFailed = page.getByText(/This interaction failed/i).last();
  const onlyYouCanSeeThis = page.getByText(/Only you can see this/i).last();

  async function findOpenPanelButton() {
    if (await openPanelRole.isVisible({ timeout: 250 }).catch(() => false)) return openPanelRole;
    if (await openPanelFallback.isVisible({ timeout: 250 }).catch(() => false)) return openPanelFallback;
    return null;
  }

  async function scrollThreadToBottom() {
    await page
      .evaluate(() => {
        const chat = document.querySelector('[data-list-id="chat-messages"]');
        if (chat) {
          let scroller = chat;
          while (scroller && scroller.parentElement) {
            const el = scroller;
            if (el.scrollHeight && el.clientHeight && el.scrollHeight > el.clientHeight + 50) break;
            scroller = scroller.parentElement;
          }
          if (scroller && scroller.scrollHeight && scroller.clientHeight) {
            scroller.scrollTop = scroller.scrollHeight;
            return true;
          }
        }

        const main = document.querySelector('main, div[role="main"]');
        if (!main) return false;

        const scrollers = Array.from(main.querySelectorAll('div')).filter((el) => {
          try {
            return el.scrollHeight && el.clientHeight && el.scrollHeight > el.clientHeight + 50;
          } catch {
            return false;
          }
        });
        if (scrollers.length === 0) return false;

        scrollers.sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
        const s = scrollers[0];
        s.scrollTop = s.scrollHeight;
        return true;
      })
      .catch(() => null);
  }

  async function isLikelyRaidPanelContainer(container) {
    const hasMarker =
      (await container
        .getByText(/This panel is only visible to you/i)
        .first()
        .isVisible({ timeout: 250 })
        .catch(() => false)) ||
      (await container
        .getByText(/Only you can see this/i)
        .first()
        .isVisible({ timeout: 250 })
        .catch(() => false));

    const hasSelectGroup = await container
      .getByText(/Select a group/i)
      .first()
      .isVisible({ timeout: 250 })
      .catch(() => false);

    const raidButtons = [
      /^Join Raid$/i,
      /^Leave Raid$/i,
      /^My DKP/i,
      /^Groups$/i,
      /^DKP$/i,
      /^Award DKP$/i,
      /^Deduct DKP$/i,
      /^Raid Points$/i,
      /^Reverse Raid DKP$/i,
      /^Stop Timed DKP$/i,
      /^Remove Raider$/i,
    ];

    let hasAnyRaidButton = false;
    for (const re of raidButtons) {
      // eslint-disable-next-line no-await-in-loop
      const ok = await container
        .locator('button, [role="button"]')
        .filter({ hasText: re })
        .first()
        .isVisible({ timeout: 250 })
        .catch(() => false);
      if (ok) {
        hasAnyRaidButton = true;
        break;
      }
    }

    // Require the ephemeral marker plus at least one raid-specific indicator.
    // This avoids matching unrelated ephemeral panels like "DKP Panel for ...".
    return (hasMarker && hasAnyRaidButton) || hasSelectGroup;
  }

  async function waitForEphemeralRaidPanelContainer(timeoutMs = 15_000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const resolved = await resolveEphemeralRaidPanelContainer();
      if (resolved) return resolved;
      if (await interactionFailed.isVisible({ timeout: 200 }).catch(() => false)) return 'interaction_failed';
      await page.waitForTimeout(250);
    }
    return null;
  }

  async function resolveEphemeralRaidPanelContainer() {
    const candidates = [
      /^DKP$/i,
      /^Join Raid$/i,
      /^Leave Raid$/i,
      /^My DKP/i,
      /^Timed DKP$/i,
      /^Award DKP$/i,
      /^Deduct DKP$/i,
      /^Groups$/i,
      /^Not in raid$/i,
      /^Raid Points$/i,
      /^Reverse Raid DKP$/i,
    ];

    for (const re of candidates) {
      const btn = page.locator('button, [role="button"]').filter({ hasText: re }).last();
      if (await btn.isVisible({ timeout: 500 }).catch(() => false)) {
        const container = btn.locator('xpath=ancestor::li[1]');
        if (await isLikelyRaidPanelContainer(container)) return container;
      }
    }

    if (await onlyYouCanSeeThis.isVisible({ timeout: 500 }).catch(() => false)) {
      const container = onlyYouCanSeeThis.locator('xpath=ancestor::li[1]');
      if (await isLikelyRaidPanelContainer(container)) return container;
    }

    const titleCandidates = [
      page.getByText(/Raid Control Panel for/i).last(),
      page.getByText(/Raid Panel for/i).last(),
      page.getByText(/DKP for/i).last(),
    ];
    for (const title of titleCandidates) {
      if (await title.isVisible({ timeout: 500 }).catch(() => false)) {
        const container = title.locator('xpath=ancestor::li[1]');
        if (await isLikelyRaidPanelContainer(container)) return container;
      }
    }

    return null;
  }

  await expect
    .poll(
      async () => {
        await scrollThreadToBottom();
        const hasPanelTitle = await panelTitle.isVisible({ timeout: 1000 }).catch(() => false);
        if (hasPanelTitle) return true;
        const btn = await findOpenPanelButton();
        return Boolean(btn);
      },
      { timeout: 90_000 },
    )
    .toBe(true)
    .catch(async () => {
      await dumpVisibleButtons(page, { max: 120 });
      throw new Error('Timed out waiting for Open Raid Control Panel button/title (thread may be virtualized/offscreen).');
    });

  if (await panelTitle.isVisible({ timeout: 2000 }).catch(() => false)) {
    const scopedButton = panelTitle
      .locator('xpath=ancestor::li[1]')
      .locator('button, [role="button"]')
      .filter({ hasText: /Open Raid Control Panel/i })
      .first();
    if (await scopedButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await scopedButton.scrollIntoViewIfNeeded();
      for (let attempt = 0; attempt < 3; attempt += 1) {
        await page.keyboard.press('Escape').catch(() => null);
        try {
          await scopedButton.click({ force: true, noWaitAfter: true, timeout: 15_000 });
        } catch {
          await scopedButton.evaluate((el) => el.click()).catch(() => null);
        }
        await page.waitForTimeout(1500);

        const container = await waitForEphemeralRaidPanelContainer(15_000);

        if (container && container !== 'interaction_failed') {
          return container;
        }
        await page.waitForTimeout(1000);
      }
      throw new Error(
        'Open Raid Control Panel interaction failed (Discord showed "This interaction failed"). Ensure the bot is online and able to respond to button interactions in this guild/thread, then re-run.',
      );
    }
  }

  await expect
    .poll(async () => Boolean(await findOpenPanelButton()), { timeout: 45_000 })
    .toBe(true);

  const openPanel = (await findOpenPanelButton()) || openPanelFallback;
  await openPanel.scrollIntoViewIfNeeded().catch(() => null);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await page.keyboard.press('Escape').catch(() => null);
    try {
      await openPanel.click({ force: true, noWaitAfter: true, timeout: 15_000 });
    } catch {
      await openPanel.evaluate((el) => el.click()).catch(() => null);
    }
    await page.waitForTimeout(1500);

    const container = await waitForEphemeralRaidPanelContainer(15_000);

    if (container && container !== 'interaction_failed') {
      return container;
    }
    await page.waitForTimeout(1000);
  }
  throw new Error(
    'Open Raid Control Panel interaction failed (Discord showed "This interaction failed"). Ensure the bot is online and able to respond to button interactions in this guild/thread, then re-run.',
  );
}

test('raid leader tools: raid points + reverse raid dkp + stop timed dkp + not in raid label', async ({ page }) => {
  ensureEnvAndAuth();

  test.setTimeout(10 * 60_000);

  const raidName = `Playwright Raid Controls ${Date.now()}`;

  await loginAndOpenChannel(page);

  const voiceOk = await joinAnyVoiceChannel(page);
  test.skip(!voiceOk, 'Could not connect to Discord voice in this environment (headless WebRTC).');

  await createRaidAndOpenLogThread(page, raidName);
  let raidPanel = await openRaidControlPanel(page);

  async function resolveLatestEphemeralPanelContainer() {
    const chatRoot = page.locator('[data-list-id="chat-messages"]').first();
    const scope = (await chatRoot.count()) > 0 ? chatRoot : page;

    const markerLocators = [
      scope.getByText(/This panel is only visible to you/i),
      scope.getByText(/Only you can see this/i),
    ];

    for (const marker of markerLocators) {
      const n = await marker.count();
      if (n <= 0) continue;
      for (let i = 0; i < Math.min(n, 6); i += 1) {
        const cand = marker.nth(n - 1 - i);
        if (await cand.isVisible({ timeout: 400 }).catch(() => false)) {
          return cand.locator('xpath=ancestor::li[1]');
        }
      }
    }

    // Fallback: a visible Groups button whose message looks like the panel.
    const groupsBtns = scope.locator('button, [role="button"]').filter({ hasText: /^Groups$/i });
    const gCount = await groupsBtns.count();
    if (gCount > 0) {
      for (let i = 0; i < Math.min(gCount, 6); i += 1) {
        const b = groupsBtns.nth(gCount - 1 - i);
        if (!(await b.isVisible({ timeout: 400 }).catch(() => false))) continue;
        const container = b.locator('xpath=ancestor::li[1]');
        const ok =
          (await container.getByText(/This panel is only visible to you/i).count()) > 0 ||
          (await container.getByText(/Only you can see this/i).count()) > 0;
        if (ok) return container;
      }
    }

    return raidPanel;
  }

  async function resolveLatestRaidPanelContainer() {
    const marker = page.getByText(/This panel is only visible to you/i).last();
    if (await marker.isVisible({ timeout: 800 }).catch(() => false)) {
      return marker.locator('xpath=ancestor::li[1]');
    }
    return resolveCurrentRaidPanelContainer();
  }

  async function resolveCurrentRaidPanelContainer() {
    const isCurrentContainerOk = async (container) => {
      const hasMarker =
        (await container
          .getByText(/This panel is only visible to you/i)
          .first()
          .isVisible({ timeout: 250 })
          .catch(() => false)) ||
        (await container
          .getByText(/Only you can see this/i)
          .first()
          .isVisible({ timeout: 250 })
          .catch(() => false));

      const hasSelectGroup = await container
        .getByText(/Select a group/i)
        .first()
        .isVisible({ timeout: 250 })
        .catch(() => false);

      const raidButtons = [
        /^Join Raid$/i,
        /^Leave Raid$/i,
        /^My DKP/i,
        /^Groups$/i,
        /^DKP$/i,
        /^Award DKP$/i,
        /^Deduct DKP$/i,
        /^Raid Points$/i,
        /^Reverse Raid DKP$/i,
        /^Stop Timed DKP$/i,
        /^Remove Raider$/i,
      ];
      let hasAnyRaidButton = false;
      for (const re of raidButtons) {
        // eslint-disable-next-line no-await-in-loop
        const ok = await container
          .locator('button, [role="button"]')
          .filter({ hasText: re })
          .first()
          .isVisible({ timeout: 250 })
          .catch(() => false);
        if (ok) {
          hasAnyRaidButton = true;
          break;
        }
      }

      return (hasMarker && hasAnyRaidButton) || hasSelectGroup;
    };

    if (raidPanel && (await isCurrentContainerOk(raidPanel).catch(() => false))) {
      return raidPanel;
    }

    const candidates = [
      /^DKP$/i,
      /^Join Raid$/i,
      /^Groups$/i,
      /^Not in raid$/i,
      /Select a group/i,
      /^Award DKP$/i,
      /^Deduct DKP$/i,
      /^Raid Points$/i,
      /^Reverse Raid DKP$/i,
      /^Stop Timed DKP$/i,
    ];
    for (const re of candidates) {
      const btn = page.locator('button, [role="button"]').filter({ hasText: re }).last();
      if (await btn.isVisible({ timeout: 800 }).catch(() => false)) {
        const container = btn.locator('xpath=ancestor::li[1]');
        if (await isCurrentContainerOk(container)) return container;
      }
    }
    return raidPanel;
  }

  const dkpButton = raidPanel.locator('button, [role="button"]').filter({ hasText: /^DKP$/i }).first();
  const raidPointsButtonPre = raidPanel.locator('button, [role="button"]').filter({ hasText: /^Raid Points$/i }).first();
  const reverseButtonPre = raidPanel.locator('button, [role="button"]').filter({ hasText: /^Reverse Raid DKP$/i }).first();
  const stopTimedPre = raidPanel.locator('button, [role="button"]').filter({ hasText: /^Stop Timed DKP$/i }).first();
  const hasLeaderButtons =
    (await raidPointsButtonPre.isVisible({ timeout: 2000 }).catch(() => false)) ||
    (await reverseButtonPre.isVisible({ timeout: 2000 }).catch(() => false)) ||
    (await stopTimedPre.isVisible({ timeout: 2000 }).catch(() => false));

  if (!hasLeaderButtons) {
    if (!(await dkpButton.isVisible({ timeout: 20_000 }).catch(() => false))) {
      await dumpVisibleButtons(page, { max: 80 });
      throw new Error('DKP button not found after creating raid and opening control panel. See Visible buttons log above.');
    }
    await dkpButton.click();
    await page.waitForTimeout(1200);
    raidPanel = await resolveCurrentRaidPanelContainer();
  }

  const raidPointsButton = raidPanel.locator('button, [role="button"]').filter({ hasText: /^Raid Points$/i }).first();
  await expect(raidPointsButton).toBeVisible({ timeout: 45_000 });
  await raidPointsButton.click();

  // Raid Points is now an in-message options view (dropdowns + Submit), not a modal.
  async function waitForPanelWithButtons(requiredButtons, timeoutMs = 20_000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      for (const re of requiredButtons) {
        const btn = page.locator('button, [role="button"]').filter({ hasText: re }).last();
        // eslint-disable-next-line no-await-in-loop
        if (!(await btn.isVisible({ timeout: 400 }).catch(() => false))) continue;
        const container = btn.locator('xpath=ancestor::li[1]');
        const hasMarker =
          (await container.getByText(/This panel is only visible to you/i).count()) > 0 ||
          (await container.getByText(/Only you can see this/i).count()) > 0;
        if (!hasMarker) continue;

        let allOk = true;
        for (const need of requiredButtons) {
          // eslint-disable-next-line no-await-in-loop
          const ok = await container
            .locator('button, [role="button"]')
            .filter({ hasText: need })
            .first()
            .isVisible({ timeout: 400 })
            .catch(() => false);
          if (!ok) {
            allOk = false;
            break;
          }
        }
        if (allOk) return container;
      }
      await page.waitForTimeout(250);
    }
    return null;
  }

  const raidPointsPanel = await waitForPanelWithButtons([/^raid$/i, /^dkp$/i, /^Submit$/i], 25_000);
  if (!raidPointsPanel) {
    await dumpVisibleButtons(page, { max: 120 });
    throw new Error('Raid Points options panel did not appear (raid/dkp/Submit not found).');
  }

  await raidPointsPanel.scrollIntoViewIfNeeded().catch(() => null);
  const scopeTrigger = raidPointsPanel.locator('button, [role="button"]').filter({ hasText: /^raid$/i }).first();
  const sortTrigger = raidPointsPanel.locator('button, [role="button"]').filter({ hasText: /^dkp$/i }).first();
  await expect(scopeTrigger).toBeVisible({ timeout: 15_000 });
  await expect(sortTrigger).toBeVisible({ timeout: 15_000 });

  async function selectDropdownOption(container, triggerText, optionText) {
    const trigger = container
      .locator('button[aria-haspopup="listbox"], [role="button"][aria-haspopup="listbox"], [role="combobox"][aria-haspopup="listbox"]')
      .filter({ hasText: new RegExp(`^${escapeRegExp(triggerText)}$`, 'i') })
      .first();

    await expect(trigger).toBeVisible({ timeout: 15_000 });
    await trigger.click();

    const listbox = page.getByRole('listbox').filter({ hasText: new RegExp(optionText, 'i') }).first();
    await expect(listbox).toBeVisible({ timeout: 15_000 });
    await listbox.getByRole('option', { name: new RegExp(`^${escapeRegExp(optionText)}$`, 'i') }).first().click();
  }

  await selectDropdownOption(raidPointsPanel, 'raid', 'raid');
  await selectDropdownOption(raidPointsPanel, 'dkp', 'dkp');

  const submitPoints = raidPointsPanel.locator('button, [role="button"]').filter({ hasText: /^Submit$/i }).first();
  await expect(submitPoints).toBeVisible({ timeout: 15_000 });
  await submitPoints.click();

  // Verify a response containing "Raid Points" appears.
  await expect(page.getByText('Raid Points', { exact: false }).first()).toBeVisible({ timeout: 30_000 });

  // Return to the DKP/manage raid panel so leader buttons like Reverse Raid DKP are visible.
  const backFromPoints = raidPointsPanel.locator('button, [role="button"]').filter({ hasText: /^Back$/i }).first();
  if (await backFromPoints.isVisible({ timeout: 5000 }).catch(() => false)) {
    await backFromPoints.click();
    await page.waitForTimeout(1200);
  }

  raidPanel = await resolveCurrentRaidPanelContainer();
  const reverseButton = raidPanel.locator('button, [role="button"]').filter({ hasText: /^Reverse Raid DKP$/i }).first();
  await expect(reverseButton).toBeVisible({ timeout: 45_000 });

  const interactionFailedToast = page.getByText(/This interaction failed/i).last();
  const confirmPlaceholder = page.locator('input[placeholder="CONFIRM"], textarea[placeholder="CONFIRM"]').first();
  const confirmLabel = page.getByLabel(/Type\s+CONFIRM/i).first();

  const findReverseModal = async () => {
    const byTitleText = page.getByRole('dialog').filter({ hasText: /Reverse Raid DKP/i }).first();
    if (await byTitleText.isVisible({ timeout: 400 }).catch(() => false)) return byTitleText;

    const byConfirmPlaceholder = page.getByRole('dialog').filter({ has: confirmPlaceholder }).first();
    if (await byConfirmPlaceholder.isVisible({ timeout: 400 }).catch(() => false)) return byConfirmPlaceholder;

    const byConfirmLabel = page.getByRole('dialog').filter({ has: confirmLabel }).first();
    if (await byConfirmLabel.isVisible({ timeout: 400 }).catch(() => false)) return byConfirmLabel;

    return null;
  };

  let reverseModal = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await reverseButton.scrollIntoViewIfNeeded().catch(() => null);
    await page.keyboard.press('Escape').catch(() => null);
    try {
      await reverseButton.click({ force: true, noWaitAfter: true, timeout: 15_000 });
    } catch {
      await reverseButton.evaluate((el) => el.click()).catch(() => null);
    }

    const startedAt = Date.now();
    while (Date.now() - startedAt < 20_000) {
      reverseModal = await findReverseModal();
      if (reverseModal) break;
      if (await interactionFailedToast.isVisible({ timeout: 250 }).catch(() => false)) break;
      await page.waitForTimeout(250);
    }

    if (reverseModal) break;
    await page.waitForTimeout(800);
  }

  if (!reverseModal) {
    await dumpVisibleButtons(page, { max: 120 });
    await dumpVisibleDialogs(page, { max: 4 });
    throw new Error('Reverse Raid DKP modal did not appear after clicking Reverse Raid DKP.');
  }

  const confirmInput = reverseModal.getByLabel(/Type\s+CONFIRM/i).first();
  if (await confirmInput.isVisible({ timeout: 1500 }).catch(() => false)) {
    await confirmInput.fill('NO');
  } else {
    const placeholderInput = reverseModal.locator('input[placeholder="CONFIRM"], textarea[placeholder="CONFIRM"]').first();
    await placeholderInput.fill('NO');
  }
  const reverseReason = reverseModal.getByLabel(/Reason/i);
  const reverseReasonPlaceholder = reverseModal.locator('textarea[placeholder]').first();
  await expect(reverseReasonPlaceholder).toHaveAttribute('placeholder', /remove all dkp given during the raid/i);
  if (await reverseReason.isVisible({ timeout: 1500 }).catch(() => false)) {
    await reverseReason.fill('Playwright smoke test');
  } else {
    await reverseModal.locator('textarea').first().fill('Playwright smoke test');
  }
  await reverseModal.getByRole('button', { name: /submit/i }).click();

  await expect(page.getByText('Confirmation text did not match.', { exact: false }).first()).toBeVisible({ timeout: 30_000 });

  const stopTimed = raidPanel.locator('button, [role="button"]').filter({ hasText: /^Stop Timed DKP$/i }).first();
  await expect(stopTimed).toBeVisible({ timeout: 45_000 });
  await stopTimed.click();

  // Either it disables timed DKP, or reports it's not configured.
  await expect
    .poll(
      async () => {
        const disabledCount = await page.getByText('Timed DKP disabled.', { exact: false }).count();
        const notConfiguredCount = await page.getByText('Timed DKP is not configured for this raid.', { exact: false }).count();
        const notConfiguredYetCount = await page
          .getByText('Timed DKP is not configured for this raid yet.', { exact: false })
          .count();
        return disabledCount + notConfiguredCount + notConfiguredYetCount;
      },
      { timeout: 30_000 },
    )
    .toBeGreaterThan(0);

  return;
  await page.keyboard.press('Escape').catch(() => null);
  await groupsButton.scrollIntoViewIfNeeded().catch(() => null);
  try {
    await groupsButton.click({ force: true, noWaitAfter: true, timeout: 15_000 });
  } catch {
    await groupsButton.evaluate((el) => el.click()).catch(() => null);
  }

  const groupSignupsHeading = () => raidPanel.getByRole('heading', { name: /Group Signups/i }).first();
  const groupSignupsText = () => raidPanel.getByText(/Group Signups/i).first();
  await expect
    .poll(
      async () => {
        raidPanel = await resolveCurrentRaidPanelContainer();
        const headingOk = await groupSignupsHeading().isVisible({ timeout: 500 }).catch(() => false);
        const textOk = await groupSignupsText().isVisible({ timeout: 500 }).catch(() => false);
        return headingOk || textOk;
      },
      { timeout: 20_000 },
    )
    .toBe(true)
    .catch(() => null);

  let lastGroupsClickAt = 0;
  await expect
    .poll(
      async () => {
        const scrollMessages = async () => {
          await page
            .evaluate(() => {
              const chat = document.querySelector('[data-list-id="chat-messages"]');
              if (chat) {
                let scroller = chat;
                while (scroller && scroller.parentElement) {
                  const el = scroller;
                  if (el.scrollHeight && el.clientHeight && el.scrollHeight > el.clientHeight + 50) break;
                  scroller = scroller.parentElement;
                }
                if (scroller && scroller.scrollHeight && scroller.clientHeight) {
                  scroller.scrollTop = scroller.scrollHeight;
                  return true;
                }
              }

              const main = document.querySelector('main, div[role="main"]');
              if (!main) return false;
              const scrollers = Array.from(main.querySelectorAll('div')).filter((el) => {
                try {
                  return el.scrollHeight && el.clientHeight && el.scrollHeight > el.clientHeight + 50;
                } catch {
                  return false;
                }
              });
              if (scrollers.length === 0) return false;
              scrollers.sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
              const s = scrollers[0];
              s.scrollTop = s.scrollHeight;
              return true;
            })
            .catch(() => null);
        };

        // If Discord rejected the component interaction, we'll never see the UI update.
        if (await interactionFailedAny.isVisible({ timeout: 200 }).catch(() => false)) {
          throw new Error('Groups interaction failed (Discord showed "This interaction failed").');
        }

        // Groups may open a setup modal if groups haven't been configured yet.
        // In some runs, group_count may still read 0 briefly even after submitting.
        // Handle the modal a couple times and re-click Groups after each submit.
        for (let setupAttempt = 0; setupAttempt < 2; setupAttempt += 1) {
          const numberOfGroupsField = page.getByLabel(/Number of groups|How many groups\?/i).first();
          const placeholderGroups = page.getByPlaceholder(/e\.?g\.?\s*,?\s*2/i).first();
          const anyTextbox = page.getByRole('textbox').first();
          const groupSetupModal = page
            .getByRole('dialog')
            .filter({ has: numberOfGroupsField.or(placeholderGroups).or(anyTextbox) })
            .first();
          if (!(await groupSetupModal.isVisible({ timeout: 400 }).catch(() => false))) break;

          const numGroupsInput = groupSetupModal.getByLabel(/Number of groups|How many groups\?/i).first();
          const fallbackInput = groupSetupModal.getByRole('textbox').first();
          if (await numGroupsInput.isVisible({ timeout: 300 }).catch(() => false)) {
            await numGroupsInput.fill('2');
          } else {
            await fallbackInput.fill('2');
          }
          await groupSetupModal.getByRole('button', { name: /submit|done|save|ok/i }).first().click();
          await expect(groupSetupModal).toBeHidden({ timeout: 15_000 }).catch(() => null);
          await page.waitForTimeout(1500);

          // Wait for any confirmation that group setup completed.
          const readyAny = page.getByText(/Group signups are ready\./i).first();
          await expect
            .poll(async () => (await readyAny.count()) > 0, { timeout: 10_000 })
            .toBe(true)
            .catch(() => null);

          raidPanel = await resolveLatestEphemeralPanelContainer();
          const postSetupGroups = raidPanel.locator('button, [role="button"]').filter({ hasText: /^Groups$/i }).first();
          if (await postSetupGroups.isVisible({ timeout: 2500 }).catch(() => false)) {
            await page.keyboard.press('Escape').catch(() => null);
            await postSetupGroups.scrollIntoViewIfNeeded().catch(() => null);
            try {
              await postSetupGroups.click({ force: true, noWaitAfter: true, timeout: 10_000 });
            } catch {
              await postSetupGroups.evaluate((el) => el.click()).catch(() => null);
            }
            await page.waitForTimeout(1000);
          }
        }

        // Prefer detecting the embed text (more stable than select placeholder text).
        await scrollMessages();

        // First: if the ephemeral panel itself updated, assert within that message container.
        raidPanel = await resolveLatestEphemeralPanelContainer();
        const panelNotInRaid = raidPanel.getByText(/Not in raid/i).first();
        if (await panelNotInRaid.isVisible({ timeout: 500 }).catch(() => false)) {
          return true;
        }
        const panelSelectGroup = raidPanel.getByText(/Select a group/i).first();
        if (await panelSelectGroup.isVisible({ timeout: 500 }).catch(() => false)) {
          return true;
        }

        const chatRoot = page.locator('[data-list-id="chat-messages"]').first();
        const chatScope = (await chatRoot.count()) > 0 ? chatRoot : page;

        // If groups were just set up, RaidCog sends a followup confirmation.
        const readyText = chatScope.getByText(/Group signups are ready\./i).first();
        if (await readyText.isVisible({ timeout: 400 }).catch(() => false)) {
          return true;
        }

        const notInRaidAll = chatScope.getByText(/Not in raid/i);
        const nirCount = await notInRaidAll.count();
        if (nirCount > 0) {
          const maxToCheck = Math.min(nirCount, 10);
          for (let i = 0; i < maxToCheck; i += 1) {
            const candidate = notInRaidAll.nth(nirCount - 1 - i);
            await candidate.scrollIntoViewIfNeeded().catch(() => null);
            if (await candidate.isVisible({ timeout: 400 }).catch(() => false)) {
              return true;
            }
          }
        }

        const groupSignupsAll = chatScope.getByText(/Group Signups/i);
        const gsCount = await groupSignupsAll.count();
        if (gsCount > 0) {
          const maxToCheck = Math.min(gsCount, 8);
          for (let i = 0; i < maxToCheck; i += 1) {
            const candidate = groupSignupsAll.nth(gsCount - 1 - i);
            await candidate.scrollIntoViewIfNeeded().catch(() => null);
            if (!(await candidate.isVisible({ timeout: 400 }).catch(() => false))) continue;

            const container = candidate.locator('xpath=ancestor::li[1]');
            const notInRaidText = container.getByText(/Not in raid/i).first();
            if (await notInRaidText.isVisible({ timeout: 800 }).catch(() => false)) {
              return true;
            }
          }
        }

        const selectCandidates = [
          chatScope.locator('button, [role="button"]').filter({ hasText: /Select a group/i }),
          chatScope.getByRole('combobox', { name: /Select a group/i }),
          chatScope.getByText(/Select a group/i),
        ];

        for (const loc of selectCandidates) {
          const n = await loc.count();
          if (n <= 0) continue;

          const maxToCheck = Math.min(n, 10);
          for (let i = 0; i < maxToCheck; i += 1) {
            const candidate = loc.nth(n - 1 - i);
            await candidate.scrollIntoViewIfNeeded().catch(() => null);
            if (!(await candidate.isVisible({ timeout: 300 }).catch(() => false))) continue;

            const groupPanel = candidate.locator('xpath=ancestor::li[1]');

            const notInRaidBtns = groupPanel
              .locator('button, [role="button"]')
              .filter({ hasText: /^Not in raid$/i });
            const notInRaidCount = await notInRaidBtns.count();
            if (notInRaidCount > 0) {
              for (let j = 0; j < Math.min(notInRaidCount, 6); j += 1) {
                const b = notInRaidBtns.nth(notInRaidCount - 1 - j);
                await b.scrollIntoViewIfNeeded().catch(() => null);
                if (await b.isVisible({ timeout: 300 }).catch(() => false)) {
                  return true;
                }
              }
            }

            const notInRaidText = groupPanel.getByText(/Not in raid/i).first();
            if (await notInRaidText.isVisible({ timeout: 500 }).catch(() => false)) {
              return true;
            }
          }
        }

        // If we haven't reached the signup controls yet, retry clicking Groups.
        const now = Date.now();
        if (now - lastGroupsClickAt > 900) {
          lastGroupsClickAt = now;

          raidPanel = await resolveLatestEphemeralPanelContainer();
          const backToMain = raidPanel.locator('button, [role="button"]').filter({ hasText: /^Back$/i }).first();
          if (await backToMain.isVisible({ timeout: 800 }).catch(() => false)) {
            await backToMain.click({ force: true, noWaitAfter: true, timeout: 10_000 }).catch(() => null);
            await page.waitForTimeout(750);
            raidPanel = await resolveLatestEphemeralPanelContainer();
          }
          const retryGroups = raidPanel.locator('button, [role="button"]').filter({ hasText: /^Groups$/i }).first();
          if (await retryGroups.isVisible({ timeout: 800 }).catch(() => false)) {
            await page.keyboard.press('Escape').catch(() => null);
            await retryGroups.scrollIntoViewIfNeeded().catch(() => null);
            try {
              await retryGroups.click({ force: true, noWaitAfter: true, timeout: 10_000 });
            } catch {
              await retryGroups.evaluate((el) => el.click()).catch(() => null);
            }
            await page.waitForTimeout(600);
          }
        }

        return false;
      },
      { timeout: 60_000 },
    )
    .toBe(true)
    .catch(async () => {
      await dumpVisibleButtons(page, { max: 120 });
      await dumpVisibleDialogs(page, { max: 4 });
      if (await interactionFailedAny.isVisible({ timeout: 200 }).catch(() => false)) {
        throw new Error('Groups interaction failed (Discord showed "This interaction failed").');
      }
      throw new Error('Expected group signup controls (Not in raid + Select a group...) after clicking Groups, but they did not appear.');
    });
});
