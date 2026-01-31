import { test, expect } from '@playwright/test';
import fs from 'fs';

const guildId = (process.env.DISCORD_TEST_GUILD_ID || '1383966524150124604').trim();
const channelId = (process.env.DISCORD_TEST_CHANNEL_ID || '').trim();
const channelName = (process.env.DISCORD_TEST_CHANNEL_NAME || 'dkp-system').trim();

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function ensureAuthState() {
  if (!fs.existsSync('discord-auth.json')) {
    test.skip(
      true,
      'discord-auth.json not found. Run DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed from js-e2e/ to create it.',
    );
  }
}

 async function openChangelogFromNewestWelcome(page) {
  async function clickChangeLogFromDkpPanel() {
    const panelTitle = page.getByText(/DKP Panel for/i).last();
    await panelTitle.waitFor({ state: 'visible', timeout: 45000 });
    const panel = panelTitle.locator('xpath=ancestor::li[1]');
    const btn = panel.getByRole('button', { name: /Change Log/i }).first();
    await btn.waitFor({ state: 'visible', timeout: 15000 });
    await btn.click({ timeout: 15000 });
  }

  const openPanelButton = page.locator('button, [role="button"]').filter({ hasText: /^Open DKP Panel$/i }).last();
  if (await openPanelButton.count()) {
    await openPanelButton.scrollIntoViewIfNeeded().catch(() => {});
  }
  if (await openPanelButton.isVisible({ timeout: 15000 }).catch(() => false)) {
    await openPanelButton.click({ timeout: 15000 });
    await clickChangeLogFromDkpPanel();
    return;
  }

  const pinnedButton = page.getByRole('button', { name: /Pinned Messages/i }).first();
  if (await pinnedButton.isVisible({ timeout: 15000 }).catch(() => false)) {
    await pinnedButton.click({ timeout: 15000 });

    const pinnedDialog = page.getByRole('dialog', { name: /Pinned Messages/i });
    await pinnedDialog.waitFor({ state: 'visible', timeout: 45000 }).catch(() => null);

    const welcomeText = page.getByText('Welcome to the DKP Bot!', { exact: false }).first();
    if (await welcomeText.isVisible({ timeout: 15000 }).catch(() => false)) {
      await welcomeText.click({ timeout: 15000 });
      await page.waitForTimeout(1000);
    }

    const pinnedOpenPanelButton = pinnedDialog
      .locator('button, [role="button"]')
      .filter({ hasText: /Open DKP Panel/i })
      .first();
    if (await pinnedOpenPanelButton.isVisible({ timeout: 15000 }).catch(() => false)) {
      await pinnedOpenPanelButton.click({ timeout: 15000 });
      await page.keyboard.press('Escape').catch(() => null);
      await page.waitForTimeout(1000);
      await clickChangeLogFromDkpPanel();
      return;
    }

    await page.keyboard.press('Escape').catch(() => null);
    await page.waitForTimeout(1000);

    if (await openPanelButton.isVisible({ timeout: 15000 }).catch(() => false)) {
      await openPanelButton.click({ timeout: 15000 });
      await clickChangeLogFromDkpPanel();
      return;
    }
  }

  throw new Error('Could not find a visible "Open DKP Panel" button.');
 }

async function openVersionDropdown(page) {
  const closeBtn = page.getByRole('button', { name: /^Close$/i }).last();
  await closeBtn.waitFor({ state: 'visible', timeout: 45000 });

  const viewer = closeBtn.locator('xpath=ancestor::li[1]');

  const trigger = viewer.getByRole('button', { name: /Select a version|0\.1\.0-alpha\.|Unreleased/i }).first();
  await trigger.scrollIntoViewIfNeeded().catch(() => {});
  await trigger.waitFor({ state: 'visible', timeout: 15000 });

  for (let attempt = 0; attempt < 4; attempt += 1) {
    await trigger.click({ timeout: 15000, force: true });
    await page.waitForTimeout(150);

    const versionOptionRe = /Unreleased|0\.1\.0-alpha\.3|0\.1\.0-alpha\.2|0\.1\.0-alpha\.1|0\.1\.0-alpha\.0/i;
    const match = page
      .locator('[role="option"], [role="menuitemradio"], [role="menuitem"]')
      .filter({ hasText: versionOptionRe });

    if (await match.first().isVisible({ timeout: 2000 }).catch(() => false)) {
      const options = await match.evaluateAll((els) =>
        els
          .map((el) => ({
            text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
            selected: el.getAttribute('aria-selected') === 'true' || el.getAttribute('aria-checked') === 'true',
          }))
          .filter((o) => o.text),
      );

      return { match, options };
    }
  }

  throw new Error('Could not open version dropdown (no version options appeared after clicking trigger).');
}

async function pickOption(page, label) {
  // Discord closes the dropdown after a selection, so always reopen it.
  await openVersionDropdown(page);

  const escaped = label.replace(/[-/\\.^$*+?()|[\]{}]/g, '\\$&');
  const option = page
    .locator('[role="option"], [role="menuitemradio"], [role="menuitem"]')
    .filter({ hasText: new RegExp(`^${escaped}$`, 'i') })
    .first();
  await option.waitFor({ state: 'visible', timeout: 15000 });
  await option.click({ timeout: 15000 });

  // Give Discord a moment to apply the selection and edit the ephemeral message.
  await page.waitForTimeout(300);
}

async function openChangelog(page) {
  if (channelId) {
    await page.goto(`https://discord.com/channels/${guildId}/${channelId}`, { waitUntil: 'domcontentloaded' });
  } else {
    await page.goto(`https://discord.com/channels/${guildId}`, { waitUntil: 'domcontentloaded' });
  }

  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 1500 }).catch(() => false)) {
    throw new Error('Discord login page detected. The storageState did not load; regenerate discord-auth.json.');
  }

  const expectedChannelHeaderPattern = new RegExp(String.raw`:\s*${escapeRegExp(channelName)}$`, 'i');
  const channelHeader = page.getByRole('heading', { name: expectedChannelHeaderPattern }).first();
  const inExpectedChannel = await channelHeader.isVisible({ timeout: 12_000 }).catch(() => false);

  if (!inExpectedChannel) {
    const channelPattern = new RegExp(
      String.raw`^(unread,\s*)?${escapeRegExp(channelName)}(\b|\s|\().*`,
      'i',
    );
    const channelsList = page.getByRole('list', { name: 'Channels' });
    const channelLink = channelsList.getByRole('link', { name: channelPattern }).first();

    await channelsList.waitFor({ state: 'visible', timeout: 45_000 });
    await channelLink.waitFor({ state: 'attached', timeout: 45_000 });

    const href = await channelLink.getAttribute('href');
    if (href) {
      await page.goto(`https://discord.com${href}`, { waitUntil: 'domcontentloaded' });
    } else {
      await channelLink.scrollIntoViewIfNeeded().catch(() => {});
      await channelLink.click({ timeout: 45_000, force: true });
    }
  }

  await channelHeader.waitFor({ state: 'visible', timeout: 45_000 });

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

  await page.waitForTimeout(5000);

  await openChangelogFromNewestWelcome(page);
  await page.getByRole('button', { name: /^Close$/i }).last().waitFor({ state: 'visible', timeout: 45000 });
}

test('Changelog options include released versions', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await openChangelog(page);

  const { options } = await openVersionDropdown(page);
  const optionTexts = options.map((o) => o.text);

  // Unreleased is officers-only; depending on the auth state used in CI,
  // it may or may not be present.
  expect(optionTexts).toContain('0.1.0-alpha.3');
  expect(optionTexts).toContain('0.1.0-alpha.2');
  expect(optionTexts).toContain('0.1.0-alpha.1');
  expect(optionTexts).toContain('0.1.0-alpha.0');
  const hasUnreleased = optionTexts.includes('Unreleased');
  if (!hasUnreleased) {
    await expect(page.getByText('Showing public changelog entries', { exact: false }).first()).toBeVisible({ timeout: 45000 });
  }
});

test('Changelog shows notes for 0.1.0-alpha.3', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await openChangelog(page);
  await pickOption(page, '0.1.0-alpha.3');
  await expect(page.getByText('team grouping', { exact: false }).first()).toBeVisible({ timeout: 45000 });
});

test('Changelog shows notes for 0.1.0-alpha.0', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await openChangelog(page);
  await pickOption(page, '0.1.0-alpha.0');
  await expect(page.getByText('Initial alpha release', { exact: false }).first()).toBeVisible({ timeout: 45000 });
});

test('Changelog shows notes for 0.1.0-alpha.1', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await openChangelog(page);
  await pickOption(page, '0.1.0-alpha.1');
  await expect(page.getByText('Versioning', { exact: false }).first()).toBeVisible({ timeout: 45000 });
});

test('Changelog shows notes for 0.1.0-alpha.2', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await openChangelog(page);
  await pickOption(page, '0.1.0-alpha.2');
  await expect(page.getByText('Open DKP Panel', { exact: false }).first()).toBeVisible({ timeout: 45000 });
});

test('Changelog viewer shows current bot version', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await openChangelog(page);
  await expect(page.getByText('Current bot version:', { exact: false }).first()).toBeVisible({ timeout: 45000 });
});

test('Changelog viewer is ephemeral', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await openChangelog(page);
  await expect(page.getByText('Only you can see this', { exact: false }).first()).toBeVisible({ timeout: 45000 });
});

test('Changelog shows Unreleased when available', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await openChangelog(page);

  const { options } = await openVersionDropdown(page);
  const optionTexts = options.map((o) => o.text);
  const hasUnreleased = optionTexts.includes('Unreleased');
  test.skip(!hasUnreleased, 'Unreleased is officers-only; current auth state does not have access.');

  await pickOption(page, 'Unreleased');
  await expect(page.getByText('Validate the new pop-up raid panel flow', { exact: false }).first()).toBeVisible({ timeout: 45000 });

  const { options: optionsAfter } = await openVersionDropdown(page);
  const selected = optionsAfter.find((o) => o.selected);
  expect(selected?.text).toBe('Unreleased');
});

test('Staging changelog smoke test', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await openChangelog(page);

  const { options } = await openVersionDropdown(page);
  const optionTexts = options.map((o) => o.text);
  const hasUnreleased = optionTexts.includes('Unreleased');

  await pickOption(page, '0.1.0-alpha.0');
  await expect(page.getByText('Initial alpha release', { exact: false }).first()).toBeVisible({ timeout: 45000 });

  await pickOption(page, '0.1.0-alpha.1');
  await expect(page.getByText('Versioning', { exact: false }).first()).toBeVisible({ timeout: 45000 });

  await pickOption(page, '0.1.0-alpha.2');
  await expect(page.getByText('Open DKP Panel', { exact: false }).first()).toBeVisible({ timeout: 45000 });

  await pickOption(page, '0.1.0-alpha.3');
  await expect(page.getByText('team grouping', { exact: false }).first()).toBeVisible({ timeout: 45000 });

  if (hasUnreleased) {
    await pickOption(page, 'Unreleased');
    await expect(page.getByText('Validate the new pop-up raid panel flow', { exact: false }).first()).toBeVisible({ timeout: 45000 });

    const { options: optionsAfter } = await openVersionDropdown(page);
    const selected = optionsAfter.find((o) => o.selected);
    expect(selected?.text).toBe('Unreleased');
  } else {
    const { options: optionsAfter } = await openVersionDropdown(page);
    const selected = optionsAfter.find((o) => o.selected);
    expect(selected?.text).toBe('0.1.0-alpha.3');
  }
});
