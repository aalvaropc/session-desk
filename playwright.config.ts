import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:8766", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "node scripts/demo-server.mjs",
      url: "http://127.0.0.1:8766",
      reuseExistingServer: false,
      timeout: 60000,
    },
    {
      command: "node scripts/demo-server.mjs --fixture",
      url: "http://127.0.0.1:8768",
      reuseExistingServer: false,
      timeout: 60000,
    },
  ],
});
