import { test, expect } from '@playwright/test';
import fs from 'fs';

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

async function openChangelogFromNewestWelcome(page) {
  async function clickChangeLogFromDkpPanel() {
    const panelTitle = page.getByText(/DKP Panel for/i).last();
    await panelTitle.waitFor({ state: 'visible', timeout: 45000 });
    const panel = panelTitle.locator('xpath=ancestor::li[1]');
    const btn = panel.getByRole('button', { name: /Change Log/i }).first();
    await btn.waitFor({ state: 'visible', timeout: 15000 });
    await btn.click({ timeout: 15000 });
  }

  const openPanelButton = page.getByRole('button', { name: /Open DKP Panel/i }).last();
  if (await openPanelButton.isVisible({ timeout: 15000 }).catch(() => false)) {
    await openPanelButton.click({ timeout: 15000 });
    await clickChangeLogFromDkpPanel();
    return;
  }

  const changeLogButton = page.getByRole('button', { name: /Change Log/i }).last();
  if (await changeLogButton.isVisible({ timeout: 15000 }).catch(() => false)) {
    await changeLogButton.click({ timeout: 15000 });
    return;
  }

  const pinnedButton = page.getByRole('button', { name: /Pinned Messages/i }).first();
  if (await pinnedButton.isVisible({ timeout: 15000 }).catch(() => false)) {
    await pinnedButton.click({ timeout: 15000 });

    const pinnedOpenPanelButton = page.getByRole('button', { name: /Open DKP Panel/i }).last();
    if (await pinnedOpenPanelButton.isVisible({ timeout: 15000 }).catch(() => false)) {
      await pinnedOpenPanelButton.click({ timeout: 15000 });
      await clickChangeLogFromDkpPanel();
      return;
    }

    const pinnedChangeLogButton = page.getByRole('button', { name: /Change Log/i }).last();
    await pinnedChangeLogButton.waitFor({ state: 'visible', timeout: 45000 });
    await pinnedChangeLogButton.click({ timeout: 15000 });
    return;
  }

  throw new Error('Could not find a visible "Change Log" button.');
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

    const versionOptionRe = /Unreleased|0\.1\.0-alpha\.2|0\.1\.0-alpha\.1|0\.1\.0-alpha\.0/i;
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
  await page.goto(`https://discord.com/channels/${guildId}/${channelId}`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: /dkp-system/i }).first().waitFor({ state: 'visible', timeout: 45000 });
  await page.waitForTimeout(5000);

  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 1500 }).catch(() => false)) {
    throw new Error('Discord login page detected. The storageState did not load; regenerate discord-auth.json.');
  }

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
  expect(optionTexts).toContain('0.1.0-alpha.2');
  expect(optionTexts).toContain('0.1.0-alpha.1');
  expect(optionTexts).toContain('0.1.0-alpha.0');
  const hasUnreleased = optionTexts.includes('Unreleased');
  if (!hasUnreleased) {
    await expect(page.getByText('Showing public changelog entries', { exact: false }).first()).toBeVisible({ timeout: 45000 });
  }
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
  await expect(page.getByText('No unreleased notes yet.', { exact: false }).first()).toBeVisible({ timeout: 45000 });

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

  if (hasUnreleased) {
    await pickOption(page, 'Unreleased');
    await expect(page.getByText('No unreleased notes yet.', { exact: false }).first()).toBeVisible({ timeout: 45000 });

    const { options: optionsAfter } = await openVersionDropdown(page);
    const selected = optionsAfter.find((o) => o.selected);
    expect(selected?.text).toBe('Unreleased');
  } else {
    const { options: optionsAfter } = await openVersionDropdown(page);
    const selected = optionsAfter.find((o) => o.selected);
    expect(selected?.text).toBe('0.1.0-alpha.2');
  }
});
