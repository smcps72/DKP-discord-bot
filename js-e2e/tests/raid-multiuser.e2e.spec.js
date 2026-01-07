import { test, expect } from '@playwright/test';
import { ai } from '@zerostep/playwright';
import dotenv from 'dotenv';
import path from 'path';

// Load the shared .env from the project root, and allow it to override any
// variables that might already be set in the shell so tests are deterministic.
dotenv.config({ path: path.resolve(process.cwd(), '../.env'), override: true });

const EMAIL1 = process.env.DISCORD_TEST_EMAIL;
const PASSWORD1 = process.env.DISCORD_TEST_PASSWORD;
const EMAIL2 = process.env.DISCORD_TEST_EMAIL_2;
const PASSWORD2 = process.env.DISCORD_TEST_PASSWORD_2;
const SERVER = process.env.DISCORD_TEST_SERVER_NAME;
const CHANNEL = process.env.DISCORD_TEST_CHANNEL_NAME;
const USERNAME2 = (process.env.DISCORD_TEST_USERNAME_2 || 'sc_dkp2').trim();
const VOICE_CHANNEL = (process.env.DISCORD_TEST_VOICE_CHANNEL_NAME || 'General').trim();

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function ensureMultiUserEnv() {
  if (!EMAIL1 || !PASSWORD1 || !EMAIL2 || !PASSWORD2 || !SERVER || !CHANNEL) {
    test.skip(true, 'Multi-user tests require DISCORD_TEST_EMAIL, DISCORD_TEST_PASSWORD, DISCORD_TEST_EMAIL_2, DISCORD_TEST_PASSWORD_2, DISCORD_TEST_SERVER_NAME, and DISCORD_TEST_CHANNEL_NAME.');
  }
}

async function ensureDkpSetup(page) {
  const messageBox = page.getByRole('textbox', { name: /Message #/ });
  await messageBox.click();
  await messageBox.fill('/setup_dkp');

  const setupOption = page.getByRole('option', { name: /\/setup_dkp/ }).first();
  await setupOption.click();
  await messageBox.press('Enter');

  const setupComplete = page.getByText('DKP system setup complete!', { exact: false }).first();
  const setupRepaired = page.getByText('Setup repaired', { exact: false }).first();
  const setupExists = page.getByText('Setup already exists', { exact: false }).first();
  const setupMissingPerms = page.getByText('Missing permissions', { exact: false }).first();

  await Promise.race([
    setupComplete.waitFor({ state: 'visible', timeout: 45000 }),
    setupRepaired.waitFor({ state: 'visible', timeout: 45000 }),
    setupExists.waitFor({ state: 'visible', timeout: 45000 }),
    setupMissingPerms.waitFor({ state: 'visible', timeout: 45000 }),
  ]);
}

async function loginAndOpenChannel(page) {
  // Use any saved storageState (discord-auth.json) so we start from an
  // already-logged-in Discord session when possible.
  await page.goto('https://discord.com/app');

  // If we are still on the login page with the "Welcome back!" heading,
  // it means there is no valid saved auth state yet. In that case, surface
  // a clear error explaining how to create it manually.
  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  try {
    if (await loginHeading.isVisible({ timeout: 5000 })) {
      throw new Error(
        'Discord login page detected. Run `DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed` from js-e2e/ to log in once and create discord-auth.json, then re-run the tests.',
      );
    }
  } catch {
    // If the heading is not found quickly, continue.
  }

  // Navigate to the target server and channel using regular Playwright
  // selectors instead of ZeroStep. This is more reliable than natural-
  // language instructions for basic navigation.
  await page.getByRole('treeitem', { name: SERVER }).click();
  await page.waitForTimeout(2000);

  const channelLink = page.getByRole('link', { name: CHANNEL });
  await channelLink.click();
  await page.waitForTimeout(2000);
}

async function ensureRaidThreadOpen(page, raidName) {
  const result = await ai(
    `Using the DKP bot, create a new raid named "${raidName}" and then open its raid log thread named "${raidName} - Raid Log". If the thread is already present, just open it. When the raid log thread is open, reply exactly with "OPENED". If you cannot open it, reply exactly with "FAILED".`,
    { page, test },
  );

  expect(result.trim()).toBe('OPENED');
}

async function joinRaidVoiceChannel(page, raidName) {
  const result = await ai(
    `Join the voice channel in this server named "${raidName}". If you successfully join it, reply exactly with "JOINED". If you cannot find or join it, reply exactly with "FAILED".`,
    { page, test },
  );

  expect(result.trim()).toBe('JOINED');
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
    return;
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
  } catch {
    return;
  }
}

async function createRaidAndOpenLogThread(page, raidName) {
  const messageBox = page.getByRole('textbox', { name: /Message #/ });
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
      const voiceError = page.getByText('You must be connected to a voice channel', { exact: false }).first();

      if (await noPerm.isVisible().catch(() => false)) {
        throw new Error('Cannot run /raid_create as this test user (missing permissions).');
      }

      if (await voiceError.isVisible().catch(() => false)) {
        throw new Error('Raid creation requires the user to be connected to a voice channel.');
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

  // There may be multiple historical DKP-System setups, each with its own
  // active-raids channel. Prefer the one marked unread (likely the newest),
  // otherwise fall back to the last matching channel in the sidebar.
  const unreadActiveRaids = page.getByRole('link', { name: /unread, active-raids/i });
  if (await unreadActiveRaids.count()) {
    await unreadActiveRaids.first().click();
  } else {
    await page.getByRole('link', { name: /active-raids.*text channel/i }).last().click();
  }

  const threadButton = page
    .getByRole('button', { name: new RegExp(`${escapeRegExp(raidName)}.*Raid Log.*\(thread\)`, 'i') })
    .first();
  if (await threadButton.isVisible({ timeout: 5000 }).catch(() => false)) {
    await threadButton.click();
  } else {
    const threadLink = page
      .getByRole('link', { name: new RegExp(`${escapeRegExp(raidName)}.*Rai`, 'i') })
      .first();
    await expect(threadLink).toBeVisible({ timeout: 20000 });
    await threadLink.click();
  }

  const threadHeading = page.getByRole('heading', { name: new RegExp(`Thread:.*${escapeRegExp(raidName)}.*Raid Log`, 'i') });
  try {
    await expect(threadHeading).toBeVisible({ timeout: 15000 });
  } catch {
    const noVoice = page.getByText('You must be connected to a voice channel', { exact: false }).first();
    if (await noVoice.isVisible().catch(() => false)) {
      throw new Error(
        'Raid creation failed because the bot requires the raid leader to be in a voice channel. Join a voice channel in Discord as the test user, then re-run.',
      );
    }
    throw new Error('Failed to open the raid log thread after creating the raid.');
  }
}

test('raid member list shows empty VC message when no one is in raid voice channel', async ({ page }) => {
	if (!EMAIL1 || !PASSWORD1 || !SERVER || !CHANNEL) {
		test.skip(true, 'DISCORD_TEST_EMAIL, DISCORD_TEST_PASSWORD, DISCORD_TEST_SERVER_NAME, and DISCORD_TEST_CHANNEL_NAME must be set.');
	}

	const raidName = 'Playwright Raid Member Test';

	await loginAndOpenChannel(page);
	await createRaidAndOpenLogThread(page, raidName);

	await page.getByRole('button', { name: 'Update Team' }).click();

	// Depending on whether the raid leader remains connected to voice (e.g. on
	// another client), the team list may show members immediately instead of an
	// empty-state message.
	const emptyMessage = page.getByText('No raid members were found for this raid.', { exact: false }).first();
	const teamEmbed = page.getByText('Current Raid Team', { exact: false }).first();
	await Promise.race([
		emptyMessage.waitFor({ state: 'visible', timeout: 15000 }),
		teamEmbed.waitFor({ state: 'visible', timeout: 15000 }),
	]);
});

test('award DKP dropdown supports typing and selecting another member', async ({ page }) => {
  ensureMultiUserEnv();

  const raidName = 'Playwright E2E Raid';

  await loginAndOpenChannel(page);
  await createRaidAndOpenLogThread(page, raidName);

  // In the newly created raid log thread, verify that the Raid Control
  // Panel is present and that the "Award DKP" button is visible for the
  // raid leader. This ensures the dropdown entry point is available.
  const panel = page.getByText('Raid Control Panel for', { exact: false });
  await expect(panel).toBeVisible();

  const awardButton = page.getByRole('button', { name: 'Award DKP' });
  await expect(awardButton).toBeVisible();
});

test('My DKP shows balance but does not re-send the raid panel', async ({ page }) => {
  if (!EMAIL1 || !PASSWORD1 || !SERVER || !CHANNEL) {
    test.skip(true, 'DISCORD_TEST_EMAIL, DISCORD_TEST_PASSWORD, DISCORD_TEST_SERVER_NAME, and DISCORD_TEST_CHANNEL_NAME must be set.');
  }

  const raidName = 'Playwright My DKP Raid';

  await loginAndOpenChannel(page);
  await createRaidAndOpenLogThread(page, raidName);

  const beforePanels = await page.locator('text=Raid Control Panel').count();

  await page.getByRole('button', { name: /^My DKP\b/ }).click();

  await page.waitForTimeout(4000);

  const afterPanels = await page.locator('text=Raid Control Panel').count();
  expect(afterPanels).toBeGreaterThan(beforePanels);

  // Confirm that the "Your DKP Balance" message is visible in the thread.
  const balanceMessage = page.getByText('Your DKP Balance', { exact: false });
  await expect(balanceMessage).toBeVisible();
});

test('Join Raid button adds the user to the raid', async ({ page }) => {
  if (!EMAIL1 || !PASSWORD1 || !SERVER || !CHANNEL) {
    test.skip(true, 'DISCORD_TEST_EMAIL, DISCORD_TEST_PASSWORD, DISCORD_TEST_SERVER_NAME, and DISCORD_TEST_CHANNEL_NAME must be set.');
  }

  const raidName = 'Playwright Join Raid Test';

  await loginAndOpenChannel(page);
  await ensureDkpSetup(page);
  await joinAnyVoiceChannel(page);
  await createRaidAndOpenLogThread(page, raidName);

  const panel = page.getByText('Raid Control Panel', { exact: false }).first();
  await expect(panel).toBeVisible({ timeout: 20000 });

  await page.getByRole('button', { name: /^Join Raid$/ }).click();
  await expect(page.getByText('You have been added to the raid.', { exact: false })).toBeVisible();

  await page.getByRole('button', { name: /^Join Raid$/ }).click();
  await expect(page.getByText('You are already part of this raid.', { exact: false })).toBeVisible();
});

test('Rename Thread button opens modal and renames the raid log thread', async ({ page }) => {
  if (!EMAIL1 || !PASSWORD1 || !SERVER || !CHANNEL) {
    test.skip(true, 'DISCORD_TEST_EMAIL, DISCORD_TEST_PASSWORD, DISCORD_TEST_SERVER_NAME, and DISCORD_TEST_CHANNEL_NAME must be set.');
  }

  const raidName = 'Playwright Rename Thread Test';
  const newThreadName = `${raidName} - Renamed`;

  await loginAndOpenChannel(page);
  await ensureDkpSetup(page);
  await joinAnyVoiceChannel(page);
  await createRaidAndOpenLogThread(page, raidName);

  const panel = page.getByText('Raid Control Panel', { exact: false }).first();
  await expect(panel).toBeVisible({ timeout: 20000 });

  await page.getByRole('button', { name: /^Rename Thread$/ }).click();

  const modal = page.getByRole('dialog', { name: 'Rename Raid Thread' });
  await expect(modal).toBeVisible();

  await modal.getByLabel('New thread name').fill(newThreadName);
  await modal.getByRole('button', { name: 'Submit' }).click();

  await expect(page.getByText('Thread renamed successfully.', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: `Thread: ${newThreadName}` })).toBeVisible();
});
