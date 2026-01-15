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
  const blocks = page.locator('li').filter({ has: page.getByText('Welcome to the DKP Bot!', { exact: false }) });
  const count = await blocks.count();
  expect(count).toBeGreaterThan(0);

  for (let i = count - 1; i >= 0; i -= 1) {
    const block = blocks.nth(i);
    await block.scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(200);

    const btn = block.getByRole('button', { name: /Change Log/i }).first();
    if (await btn.isVisible({ timeout: 1500 }).catch(() => false)) {
      await btn.click({ timeout: 15000 });
      return;
    }
  }

  throw new Error('Could not find a visible "Change Log" button on any Welcome panel.');
}

async function openVersionDropdown(page) {
  await page.getByRole('button', { name: /^Close$/i }).first().waitFor({ state: 'visible', timeout: 45000 });

  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForTimeout(100);

  const trigger = page
    .locator('[aria-haspopup="listbox"]')
    .filter({ hasText: /Select a version|alpha\.|Unreleased/i })
    .first();

  await trigger.waitFor({ state: 'visible', timeout: 15000 });
  await trigger.click({ timeout: 15000, force: true });

  const versionOptionRe = /Unreleased|0\.1\.0-alpha\.1|0\.1\.0-alpha\.0/i;
  const listbox = page
    .getByRole('listbox')
    .filter({ has: page.getByRole('option', { name: versionOptionRe }) })
    .first();

  await listbox.waitFor({ state: 'visible', timeout: 15000 });

  const options = await listbox.getByRole('option').evaluateAll((els) =>
    els
      .map((el) => ({
        text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
        selected: el.getAttribute('aria-selected') === 'true',
      }))
      .filter((o) => o.text),
  );

  return { listbox, options };
}

async function pickOption(page, label) {
  const escaped = label.replace(/[-/\\.^$*+?()|[\]{}]/g, '\\$&');
  const option = page.getByRole('option', { name: new RegExp(`^${escaped}$`, 'i') }).first();
  await option.waitFor({ state: 'visible', timeout: 15000 });
  await option.click({ timeout: 15000 });
}

test('Staging changelog smoke test', async ({ page }) => {
  ensureAuthState();

  await page.goto(`https://discord.com/channels/${guildId}/${channelId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);

  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 1500 }).catch(() => false)) {
    throw new Error('Discord login page detected. The storageState did not load; regenerate discord-auth.json.');
  }

  await openChangelogFromNewestWelcome(page);

  const { options } = await openVersionDropdown(page);
  const optionTexts = options.map((o) => o.text);

  expect(optionTexts).toContain('Unreleased');
  expect(optionTexts).toContain('0.1.0-alpha.1');
  expect(optionTexts).toContain('0.1.0-alpha.0');

  await pickOption(page, '0.1.0-alpha.0');
  await expect(page.getByText('Initial alpha release', { exact: false }).first()).toBeVisible({ timeout: 45000 });

  await pickOption(page, '0.1.0-alpha.1');
  await expect(page.getByText('Versioning', { exact: false }).first()).toBeVisible({ timeout: 45000 });

  await pickOption(page, 'Unreleased');
  await expect(
    page.getByText('How the bot decides which voice channels belong', { exact: false }).first(),
  ).toBeVisible({ timeout: 45000 });

  const { options: optionsAfter } = await openVersionDropdown(page);
  const selected = optionsAfter.find((o) => o.selected);
  expect(selected?.text).toBe('Unreleased');
});
