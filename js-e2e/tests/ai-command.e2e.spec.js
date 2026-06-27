import { test, expect } from '@playwright/test';
import dotenv from 'dotenv';
import fs from 'fs';
import path from 'path';

// Credentials/server config live in the project-root .env.local.
dotenv.config({ path: path.resolve(process.cwd(), '../.env.local'), override: false });

// Navigate directly by guild+channel id (the server name is ambiguous — there
// are several "DKP-local" servers). #general in the bot's working guild:
const GUILD_ID = '1388467074346516621';
const CHANNEL_ID = '1433615577892520037';

function ensureAuthState() {
  if (!fs.existsSync('discord-auth.json')) {
    test.skip(true, 'discord-auth.json not found. Run the setup-discord-auth spec first.');
  }
}

async function openChannel(page) {
  await page.goto(`https://discord.com/channels/${GUILD_ID}/${CHANNEL_ID}`, {
    timeout: 60_000,
    waitUntil: 'domcontentloaded',
  });

  const loginHeading = page.getByRole('heading', { name: 'Welcome back!' });
  if (await loginHeading.isVisible({ timeout: 2000 }).catch(() => false)) {
    throw new Error('Discord login page detected; storageState did not load. Regenerate discord-auth.json.');
  }

  // Wait for the message composer to be ready.
  await page
    .getByRole('textbox', { name: /Message #/ })
    .first()
    .waitFor({ state: 'visible', timeout: 45_000 });
  await page.waitForTimeout(2000);
}

// Invoke the /ai slash command with a single string "request" option.
async function sendAi(page, requestText) {
  const box = page.getByRole('textbox', { name: /Message #/ }).first();
  await box.click();
  await box.pressSequentially('/ai', { delay: 90 });
  await page.waitForTimeout(2000); // let the slash-command autocomplete render
  await page.keyboard.press('Enter'); // select the highlighted /ai command
  await page.waitForTimeout(1000); // request option now focused
  await page.keyboard.type(requestText, { delay: 25 });
  await page.waitForTimeout(800);
  await page.keyboard.press('Enter'); // submit
}

test('/ai off-topic request returns a friendly no-match (decline path)', async ({ page }) => {
  test.setTimeout(120_000);
  ensureAuthState();

  await openChannel(page);
  await sendAi(page, 'tell me a joke about elves');

  // The bot defers then edits in an ephemeral reply. Our decline fix should
  // surface the friendly "couldn't match" message rather than a schema error.
  const reply = page.getByText(/couldn.?t match that to a known command/i).first();
  await reply.waitFor({ state: 'visible', timeout: 30_000 });

  await page.screenshot({ path: 'ai-nomatch.png', fullPage: false });
  await expect(reply).toBeVisible();
});
