import { expect, test } from "@playwright/test";

/**
 * Phase 7 — ONE high-value smoke path, not comprehensive coverage. Playwright renders a real
 * browser DOM, which is what catches a blank route, a broken navigation, a layout-level
 * failure, or state lost between screens — none of which jsdom (the vitest suite) can see.
 *
 * The server under test is started by `scripts/e2e-smoke.sh`: a throwaway Postgres container
 * (multi-user accounts require a real database — the in-memory fallback reports
 * `auth_required: false` and skips login entirely, which would make step 2 below a no-op),
 * the built SPA, and the API with `MOSAERA_INITIAL_ADMIN_USER` / `_PASSWORD` seeding one
 * headless admin. Credentials arrive via env so the harness and the spec never drift apart.
 */
const ADMIN_USER = process.env.E2E_ADMIN_USER ?? "e2e-admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/");
  const usernameField = page.getByLabel("Username");
  await usernameField.fill(ADMIN_USER);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Login" }).click();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
}

test.beforeAll(() => {
  expect(ADMIN_PASSWORD, "E2E_ADMIN_PASSWORD must be set by the harness").not.toBe("");
});

test("core smoke path: login -> project -> settings -> logout", async ({ page }) => {
  // 1. Load / -> the login screen renders (not blank). Authentication is required because the
  // harness seeded an admin against a real database, so AuthGate must show the credential form.
  await page.goto("/");
  await expect(page.getByLabel("Username")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();

  // 2. Log in with the seeded admin -> the projects page renders.
  await login(page);

  // 3. Create a new project with NO repository URL (local-first) -> lands on the project's
  // start/onboarding view without error. A fresh project starts "draft"/"drafting" (still
  // cloning/initializing), so ProjectDetailPage redirects every section but Start there —
  // asserting on that redirect, rather than a fixed heading, is what survives the exact
  // moment (cloning vs. ready-for-intake) the test happens to land on.
  await page.getByRole("link", { name: "New project" }).click();
  await expect(page.getByRole("heading", { name: "New project" })).toBeVisible();
  const projectName = `E2E Smoke ${Date.now()}`;
  await page.getByLabel("Project name").fill(projectName);
  // Source repository is intentionally left empty — local-first (ADR-0123).
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/start$/, { timeout: 15_000 });
  // No error surfaced on the way in.
  await expect(page.getByRole("alert")).toHaveCount(0);

  // 4. Navigate to Settings -> Models -> the page renders content. Ollama's own health is
  // deliberately NOT asserted (the CI box may have no Ollama running) — only that the section
  // has structure and no raw error text leaked onto the screen.
  await page.goto("/settings/models");
  const settingsNav = page.getByRole("navigation", { name: "Settings sections" });
  await expect(settingsNav.getByRole("link", { name: "Models" })).toBeVisible();
  await expect(page.getByText(/traceback|internal server error/i)).toHaveCount(0);

  // 6. Log out via Settings -> Sign out -> the login screen renders again.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Username")).toBeVisible();
});

test("unknown route is not a silent blank page", async ({ page }) => {
  await login(page);

  // 5. Visit a nonsense route -> the page must NOT be a silent blank. Agent E is landing a
  // catch-all route in parallel; today's App.tsx has no "*" route, so React Router renders
  // nothing inside <main> (the sidebar/header chrome around it still renders, which is why
  // this asserts text INSIDE the <main> landmark rather than anywhere in <body> — a body-wide
  // assertion would pass today for the wrong reason and never catch the blank).
  await page.goto("/definitely-not-a-page");
  // The sidebar's own inset wrapper is ALSO a <main> landmark (shadcn's SidebarInset renders
  // one around the whole app shell), so `getByRole("main")` alone is ambiguous — two matches,
  // one of which (the shell) always has text. The inner one, App.tsx's own <main> holding
  // <Routes>, is the one that goes empty on an unmatched route; it carries no accessible
  // name, so pick it out by App.tsx's own class rather than by role alone.
  const routesMain = page.locator("main.overflow-x-clip");
  await expect(routesMain).toBeVisible();
  const mainText = (await routesMain.innerText()).trim();

  // The catch-all "*" Route (NotFoundPage) landed with the Phase 5 merge, so a blank <main>
  // here is a regression, not an expected gap — this assertion is enforced.
  expect(mainText.length).toBeGreaterThan(0);
});
