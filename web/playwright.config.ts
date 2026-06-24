// Playwright config (F25) — browser E2E for the Vue SPA.
//
// Tests live in /tests/e2e_ui (project root). The webServer block starts the
// backend (which serves the built web/dist SPA via FastAPI) on :8000. The CI
// job builds web/dist first, then runs `npx playwright test`.
//
// SSE streaming is exercised via page.waitForResponse / text assertions rather
// than byte-boundary checks (which are flaky); see tests/e2e_ui/chat.spec.ts.
import { defineConfig, devices } from "@playwright/test";

const BACKEND = process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "../tests/e2e_ui",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: BACKEND,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    // The CI job is expected to have built web/dist and to start the backend
    // separately (with the e2e fakes). We only point Playwright at it here.
    command: process.env.E2E_NO_WEBSERVER
      ? "echo 'using externally-started backend'"
      : `cd .. && PYTEST_RUN=1 uv run uvicorn api.main:app --host 127.0.0.1 --port 8000`,
    url: BACKEND,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
