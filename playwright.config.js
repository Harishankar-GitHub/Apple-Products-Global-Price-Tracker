// @ts-check
// Browser tests (tests/browser). The page is served from docs/ by a small local server,
// with its API address pointed at a local copy of the API in which apple.com is faked
// (tests/servers/fake_api.py), run by gunicorn with the production settings.
const { defineConfig, devices } = require('@playwright/test');

const SITE = 'http://127.0.0.1:8088';
const API = 'http://127.0.0.1:5055';
const PYTHON = process.env.PYTHON || 'python3';

module.exports = defineConfig({
  testDir: 'tests/browser',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  timeout: 60_000,
  use: {
    baseURL: SITE,
    locale: 'en-IE',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } } }],
  webServer: [
    {
      command: 'node tests/browser/support/serve-site.js',
      url: `${SITE}/`,
      env: { PORT: '8088', API_BASE: API },
      reuseExistingServer: !process.env.CI,
    },
    {
      command: `${PYTHON} -m gunicorn -c api/gunicorn.conf.py --bind 127.0.0.1:5055 --pythonpath tests/servers fake_api:app`,
      url: `${API}/api/health`,
      env: { TEST_ROUTES: '1', FAKE_APPLE_JITTER: '1', ADMIN_TOKEN: 'browser-test-token', FETCH_SLOT_NOTICE: '0.5',
        FAKE_APPLE_SLOW: 'prod904=4,prod907=2.5' },          // slow searches for the 'several visitors' test
      reuseExistingServer: !process.env.CI,
    },
  ],
});
