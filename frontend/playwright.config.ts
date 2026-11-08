import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.E2E_PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } }],
  // Reuses a running `npm run dev`/`npm start`; otherwise starts the production server.
  webServer: { command: `npx next start -p ${PORT}`, url: `http://127.0.0.1:${PORT}`, reuseExistingServer: true, timeout: 120_000 },
});
