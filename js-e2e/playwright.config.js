// @ts-check
import { defineConfig } from '@playwright/test';
import fs from 'fs';

/**
 * Playwright configuration for JS + ZeroStep tests.
 *
 * If a saved Discord auth storage state exists (discord-auth.json), reuse it
 * so tests start from an already-logged-in session instead of repeatedly
 * hitting the Discord login + hCaptcha flow.
 */

const storageStatePath = fs.existsSync('discord-auth.json') ? 'discord-auth.json' : undefined;

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    headless: true,
    storageState: storageStatePath,
  },
});
