import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './live-tests', workers: 1, retries: 1, timeout: 120000,
  expect: { timeout: 20000 },
  outputDir: './test-results-live',
  reporter: [['list'], ['json', { outputFile: '../reports/deployment/live-browser.json' }]],
  use: { proxy: process.env.LIVE_PROXY ? { server: process.env.LIVE_PROXY } : undefined, baseURL: 'https://ty.1byte.online', channel: 'msedge', launchOptions: { args: ['--disable-quic', ...(process.env.LIVE_DIRECT_ORIGIN === '1' ? ['--host-resolver-rules=MAP ty.1byte.online 43.155.140.75'] : [])] }, navigationTimeout: 60000, ignoreHTTPSErrors: false, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: [{ name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } }, { name: 'mobile', use: { ...devices['Pixel 7'] } }],
})
