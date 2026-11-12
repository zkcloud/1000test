import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  reporter: [
    ["list"],
    ["json", { outputFile: "../reports/release/browser-tests.json" }],
    ["html", { open: "never" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:8010",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    channel: process.env.PLAYWRIGHT_CHANNEL || "msedge",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"], defaultBrowserType: "chromium" },
    },
  ],
  webServer: {
    command: "uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8010",
    cwd: "..",
    env: { APP_DATABASE: `reports/e2e-runtime-${process.pid}.sqlite3` },
    url: "http://127.0.0.1:8010/api/health",
    reuseExistingServer: false,
    timeout: 60000,
  },
});
