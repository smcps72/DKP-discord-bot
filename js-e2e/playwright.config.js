// @ts-check
import dotenv from 'dotenv';
import fs from 'fs';
import { createRequire } from 'module';
import path from 'path';

const require = createRequire(import.meta.url);
const { defineConfig } = require('@playwright/test');

/**
 * Playwright configuration for JS + ZeroStep tests.
 *
 * If a saved Discord auth storage state exists (discord-auth.json), reuse it
 * so tests start from an already-logged-in session instead of repeatedly
 * hitting the Discord login + hCaptcha flow.
 */

const storageStatePath = fs.existsSync('discord-auth.json') ? 'discord-auth.json' : undefined;

dotenv.config({ path: path.resolve(process.cwd(), '../.env') });
dotenv.config({ path: path.resolve(process.cwd(), '../secrets/.env.local') });

const qaseMode = process.env.QASE_MODE === 'testops' ? 'testops' : 'off';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  reporter:
    qaseMode === 'testops'
      ? [
          [
            'list',
          ],
          [
            'playwright-qase-reporter',
            {
              mode: qaseMode,
              testops: {
                api: {
                  token: process.env.QASE_TESTOPS_API_TOKEN,
                },
                project: process.env.QASE_TESTOPS_PROJECT,
                run: {
                  complete: true,
                },
              },
            },
          ],
        ]
      : [
          [
            'list',
          ],
        ],
  use: {
    headless: true,
    channel: 'chrome',
    storageState: storageStatePath,
  },
});
