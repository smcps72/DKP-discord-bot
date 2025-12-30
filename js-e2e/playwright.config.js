// @ts-check
import { defineConfig } from '@playwright/test';

/**
 * Playwright configuration for JS + ZeroStep tests.
 */
export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    headless: true,
  },
});
