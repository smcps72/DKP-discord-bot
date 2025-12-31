import { test } from '@playwright/test';

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

test.skip(!shouldRun, 'Set DISCORD_SETUP_AUTH=1 to regenerate discord-auth.json with a manual Discord login.');

test('manual Discord login to create auth state', async ({ page, context }) => {
  await page.goto('https://discord.com/login');

  // Open the Playwright Inspector and pause so you can log in manually
  // (including solving the "Wait! Are you human?" hCaptcha challenge).
  await page.pause();

  // After you finish logging in and close the Inspector, we save the
  // storage state so subsequent tests can reuse the logged-in session.
  await context.storageState({ path: 'discord-auth.json' });
});
