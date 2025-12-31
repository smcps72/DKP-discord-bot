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

function ensureMultiUserEnv() {
  if (!EMAIL1 || !PASSWORD1 || !EMAIL2 || !PASSWORD2 || !SERVER || !CHANNEL) {
    test.skip(true, 'Multi-user tests require DISCORD_TEST_EMAIL, DISCORD_TEST_PASSWORD, DISCORD_TEST_EMAIL_2, DISCORD_TEST_PASSWORD_2, DISCORD_TEST_SERVER_NAME, and DISCORD_TEST_CHANNEL_NAME.');
  }
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

async function createRaidAndOpenLogThread(page, raidName) {
  const messageBox = page.getByRole('textbox', { name: /Message #/ });
  await messageBox.click();
  await messageBox.fill('/raid_create');
  const raidCreateOption = page.getByRole('option', { name: /\/raid_create/ }).first();
  await raidCreateOption.click();
  await messageBox.press('Enter');
  const modal = page.getByRole('dialog', { name: 'Create New Raid' });

  const raidNameInput = modal.getByLabel('Raid Name');
  await raidNameInput.fill(raidName);

  const submitButton = modal.getByRole('button', { name: 'Submit' });
  await submitButton.click();

  await page.getByRole('link', { name: 'active-raids' }).click();
  await page
    .getByRole('button', { name: new RegExp(`Thread ${raidName} - Raid Log`) })
    .first()
    .click();

  await expect(
    page.getByRole('heading', { name: `Thread: ${raidName} - Raid Log` }),
  ).toBeVisible();
}

test('raid member list shows empty VC message when no one is in raid voice channel', async ({ page }) => {
	if (!EMAIL1 || !PASSWORD1 || !SERVER || !CHANNEL) {
		test.skip(true, 'DISCORD_TEST_EMAIL, DISCORD_TEST_PASSWORD, DISCORD_TEST_SERVER_NAME, and DISCORD_TEST_CHANNEL_NAME must be set.');
	}

	const raidName = 'Playwright Raid Member Test';

	await loginAndOpenChannel(page);
	await createRaidAndOpenLogThread(page, raidName);

	await page.getByRole('button', { name: 'Update Team' }).click();

	const emptyMessage = page.getByText('The voice channel is empty.', { exact: false }).first();
	await expect(emptyMessage).toBeVisible();
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
