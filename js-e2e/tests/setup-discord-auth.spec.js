import { test } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

// This spec is meant to be run manually to create/refresh a logged-in
// Discord session for the test accounts. It is skipped by default so it
// does not run as part of the normal test suite.
//
// Usage (from js-e2e/):
//   DISCORD_SETUP_AUTH=1 npx playwright test tests/setup-discord-auth.spec.js --headed
//
// Then log into Discord in the browser window (including solving any
// hCaptcha challenges). Once you are fully logged in to the test
// account, close the Playwright Inspector. The test will save the
// session into `discord-auth.json`, which other tests reuse.

const shouldRun = process.env.DISCORD_SETUP_AUTH === '1';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const jsE2eRoot = path.resolve(__dirname, '..');
const rawAuthPath = (process.env.DISCORD_AUTH_STATE_PATH || 'discord-auth.json').trim();
const authPath = path.isAbsolute(rawAuthPath) ? rawAuthPath : path.join(jsE2eRoot, rawAuthPath);

test('manual Discord login to create auth state', async ({ browser }) => {
  test.skip(!shouldRun, 'Set DISCORD_SETUP_AUTH=1 to regenerate discord-auth.json with a manual Discord login.');
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.goto('https://discord.com/login');

  // Open the Playwright Inspector and pause so you can log in manually
  // (including solving the "Wait! Are you human?" hCaptcha challenge).
  await page.pause();

  await page.goto('https://discord.com/app');
  try {
    await page.waitForFunction(
      () => Boolean(window.localStorage.getItem('token') || window.localStorage.getItem('tokens')),
      null,
      { timeout: 60000 },
    );
  } catch {
  }

  // After you finish logging in and close the Inspector, we save the
  // storage state so subsequent tests can reuse the logged-in session.
  try {
    await page.evaluate(() => {
      const getJson = (key) => {
        const raw = window.localStorage.getItem(key);
        if (!raw) return null;
        try {
          return JSON.parse(raw);
        } catch {
          return null;
        }
      };

      let userId = null;
      const rawUserId = window.localStorage.getItem('user_id_cache');
      if (rawUserId) {
        try {
          userId = JSON.parse(rawUserId);
        } catch {
          userId = rawUserId.replace(/^"|"$/g, '') || null;
        }
      }

      const multiParsed = getJson('MultiAccountStore');
      if (!userId && multiParsed && multiParsed._state && Array.isArray(multiParsed._state.users)) {
        const ids = multiParsed._state.users.map((u) => (u ? u.id : null)).filter(Boolean);
        if (ids.length === 1) userId = ids[0];
      }

      const tokensParsed = getJson('tokens');
      if (!userId && tokensParsed && typeof tokensParsed === 'object') {
        const ids = Object.keys(tokensParsed).filter((k) => k && k !== '__analytics__');
        if (ids.length === 1) userId = ids[0];
      }

      if (!userId) {
        return;
      }

      window.localStorage.setItem('user_id_cache', JSON.stringify(userId));

      const existingToken = window.localStorage.getItem('token');
      if ((!existingToken || existingToken === 'null') && tokensParsed && typeof tokensParsed === 'object') {
        const tok = tokensParsed[userId];
        if (tok) {
          window.localStorage.setItem('token', JSON.stringify(tok));
        }
      }

      if (tokensParsed && typeof tokensParsed === 'object') {
        const filtered = {};
        if (tokensParsed.__analytics__) filtered.__analytics__ = tokensParsed.__analytics__;
        if (tokensParsed[userId]) filtered[userId] = tokensParsed[userId];
        window.localStorage.setItem('tokens', JSON.stringify(filtered));
      }

      if (multiParsed && typeof multiParsed === 'object' && multiParsed._state && Array.isArray(multiParsed._state.users)) {
        multiParsed._state.users = multiParsed._state.users.filter((u) => u && String(u.id) === String(userId));
        window.localStorage.setItem('MultiAccountStore', JSON.stringify(multiParsed));
      }
    });
  } catch {
  }
  await context.storageState({ path: authPath });

  await context.close();
});
