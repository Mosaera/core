import { defineConfig } from "@playwright/test";

/**
 * One smoke path (Phase 7) — not a comprehensive suite. `scripts/e2e-smoke.sh` owns the
 * lifecycle (a throwaway Postgres container, the built SPA, the API with a seeded admin),
 * so this config does NOT use Playwright's own `webServer` — the server is already up by
 * the time `playwright test` runs, at the URL the harness passes via `E2E_BASE_URL`.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8734",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
