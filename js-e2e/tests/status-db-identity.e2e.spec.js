import { test, expect } from '@playwright/test';
import fs from 'fs';

const guildId = (process.env.DISCORD_TEST_GUILD_ID || '1383966524150124604').trim();
const channelId = (process.env.DISCORD_TEST_CHANNEL_ID || '1459606597528715307').trim();
const fallbackChannelId = (process.env.DISCORD_TEST_STATUS_FALLBACK_CHANNEL_ID || '1383966524603105323').trim();
const guildId2 = (process.env.DISCORD_TEST_GUILD_ID_2 || '').trim();
const channelId2 = (process.env.DISCORD_TEST_CHANNEL_ID_2 || '').trim();

const botHint = (process.env.DISCORD_TEST_STATUS_BOT_HINT || '').trim();
const botHint2 = (process.env.DISCORD_TEST_STATUS_BOT_HINT_2 || '').trim();

function ensureAuthState() {
  if (!fs.existsSync('discord-auth.json')) {
    test.skip(
      true,
      'discord-auth.json not found. Run DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed from js-e2e/ to create it.',
    );
  }
}

function normalize(text) {
  return (text || '').replace(/\s+/g, ' ').trim();
}

function extractField(text, label) {
  const re = new RegExp(`${label}\\s*:?\\s*(?:\`([^\`]+)\`|([^\n]+))`, 'i');
  const match = re.exec(text);
  const raw = match ? (match[1] || match[2] || '') : '';
  return normalize(raw);
}

async function openChannel(page, gid, cid) {
  await page.goto(`https://discord.com/channels/${gid}/${cid}`, { waitUntil: 'domcontentloaded' });
  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 1500 }).catch(() => false)) {
    throw new Error('Discord login page detected. The storageState did not load; regenerate discord-auth.json.');
  }
  await page.waitForTimeout(5000);
}

async function openWritableChannel(page, gid, primaryCid) {
  const candidates = [primaryCid, fallbackChannelId].filter(Boolean);
  for (const cid of candidates) {
    await openChannel(page, gid, cid);

    const noPerm = page.getByText('You do not have permission to send messages in this channel.', { exact: false }).first();
    if (await noPerm.isVisible({ timeout: 1500 }).catch(() => false)) {
      continue;
    }

    const messageBox = page.getByRole('textbox', { name: /Message #/ });
    if (await messageBox.isVisible({ timeout: 15000 }).catch(() => false)) {
      return { cid, messageBox };
    }
  }

  throw new Error(
    'Could not find a writable channel with a message textbox. Ensure your Discord test account has permission to send messages and use application commands in the target channel, or set DISCORD_TEST_STATUS_FALLBACK_CHANNEL_ID to a writable channel ID.',
  );
}

async function runStatus(page, gid, cid, hint) {
  const { messageBox } = await openWritableChannel(page, gid, cid);

  const beforeCount = await page.getByText('Bot Status', { exact: true }).count();

  await messageBox.click();
  await messageBox.fill('/status');

  const options = page.getByRole('option', { name: /\/status\b/i });
  await options.first().waitFor({ state: 'visible', timeout: 15000 });

  try {
    const texts = await options.evaluateAll((els) =>
      els
        .map((el) => (el.textContent || '').replace(/\s+/g, ' ').trim())
        .filter((t) => t),
    );
    console.log('[status] autocomplete options:', texts.slice(0, 10));
  } catch {
  }

  let chosen = options.first();
  if (hint) {
    const hinted = options.filter({ hasText: new RegExp(hint.replace(/[-/\\.^$*+?()|[\]{}]/g, '\\$&'), 'i') }).first();
    if (await hinted.isVisible({ timeout: 1500 }).catch(() => false)) {
      chosen = hinted;
    }
  }

  await chosen.click();
  await messageBox.press('Enter');

  const missingPerm = page.getByText("You don't have permission to use this command.", { exact: false }).first();
  const genericError = page.getByText('An error occurred while processing that command.', { exact: false }).first();
  const interactionFailed = page.getByText('This interaction failed', { exact: false }).first();

  const botStatusCount = () => page.getByText('Bot Status', { exact: true }).count();
  const missingPermVisible = () => missingPerm.isVisible().catch(() => false);
  const genericErrorVisible = () => genericError.isVisible().catch(() => false);
  const interactionFailedVisible = () => interactionFailed.isVisible().catch(() => false);

  await expect
    .poll(
      async () => {
        if (await missingPermVisible()) return 'missing-permissions';
        if (await genericErrorVisible()) return 'generic-error';
        if (await interactionFailedVisible()) return 'interaction-failed';
        const count = await botStatusCount();
        if (count > beforeCount) return 'ok';
        return 'waiting';
      },
      { timeout: 45000 },
    )
    .not.toBe('waiting');

  if (await missingPermVisible()) {
    throw new Error(
      'Discord returned: "You don\'t have permission to use this command."\n\n'
      + 'Fix: run /status as a Discord account that is a server admin OR has the "DKP Admin" role (or the configured bot admin role) in the test guild.\n'
      + 'If you have multiple bot apps installed, set DISCORD_TEST_STATUS_BOT_HINT to pick the intended /status command from autocomplete.',
    );
  }

  if (await genericErrorVisible()) {
    throw new Error('Discord returned a generic command error for /status. Check bot logs for the underlying exception.');
  }

  if (await interactionFailedVisible()) {
    throw new Error('Discord showed "This interaction failed" for /status. This usually means the bot did not respond in time or crashed.');
  }

  await expect
    .poll(async () => page.getByText('Bot Status', { exact: true }).count(), { timeout: 45000 })
    .toBeGreaterThan(beforeCount);

  const container = page
    .locator('li')
    .filter({ hasText: 'Bot Status' })
    .filter({ hasText: 'Only you can see this' })
    .last();

  await container.waitFor({ state: 'visible', timeout: 45000 });

  const text = normalize(await container.innerText());

  const dbFile = extractField(text, 'DB File');
  const dbResolved = extractField(text, 'DB File \\(resolved\\)');
  const railwayEnv = extractField(text, 'Railway Env');
  const railwayService = extractField(text, 'Railway Service');

  return { text, dbFile, dbResolved, railwayEnv, railwayService };
}

let firstResult = null;

test('status includes db identity (and differs across envs when configured)', async ({ page }) => {
  test.setTimeout(180_000);
  ensureAuthState();

  const r1 = await runStatus(page, guildId, channelId, botHint);
  console.log('[status #1] DB File:', r1.dbFile);
  console.log('[status #1] DB File (resolved):', r1.dbResolved);
  console.log('[status #1] Railway Env:', r1.railwayEnv);
  console.log('[status #1] Railway Service:', r1.railwayService);

  expect(r1.text).toContain('Bot Status');
  if (!/DB File/i.test(r1.text)) {
    throw new Error(
      'The /status response did not include the DB identity fields (expected "DB File" and optionally Railway Env/Service).\n\n'
      + 'This usually means the deployed bot is running an older build that predates the status diagnostics changes, OR Playwright selected the wrong /status command from autocomplete.\n\n'
      + 'Fix:\n'
      + '- Redeploy the bot with the latest code from this repo (commit that adds DB identity to /status).\n'
      + '- If multiple bot apps provide /status, set DISCORD_TEST_STATUS_BOT_HINT to target the correct one.\n\n'
      + `Observed status text: ${r1.text}`,
    );
  }

  firstResult = r1;

  if (!guildId2 || !channelId2) {
    return;
  }

  const r2 = await runStatus(page, guildId2, channelId2, botHint2);
  console.log('[status #2] DB File:', r2.dbFile);
  console.log('[status #2] DB File (resolved):', r2.dbResolved);
  console.log('[status #2] Railway Env:', r2.railwayEnv);
  console.log('[status #2] Railway Service:', r2.railwayService);

  expect(r2.text).toContain('Bot Status');
  expect(r2.text).toMatch(/DB File/i);

  if (firstResult?.dbResolved && r2.dbResolved) {
    expect(r2.dbResolved).not.toBe(firstResult.dbResolved);
  }
});
