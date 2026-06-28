/**
 * Sessions UI E2E — session listing, switching, new-session, and delete.
 *
 * Backend has RAG_E2E_FAKES=1 with an in-memory fake session store, so a session
 * only appears after a chat turn registers it. Each test seeds its own session
 * to stay deterministic; the store is process-scoped (not shared across runs)
 * so no cross-test cleanup is needed within a fresh server.
 */
import { test, expect } from "@playwright/test";
import { screenshot, autoConfirmDialog } from "./helpers";

const SHOT_DIR = "sessions";

async function seedSession(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/");
  const input = page.getByTestId("chat-input");
  await input.fill("git 合并冲突如何解决？");
  await input.press("Enter");
  // Wait for the answer so the session is registered.
  await expect(page.locator("[data-testid='message'].assistant").last())
    .toContainText(/合并|冲突/, { timeout: 30_000 });
}

test.describe("Sessions UI", () => {
  test("a chat turn creates a session visible in the list", async ({ page }) => {
    await seedSession(page);
    await page.goto("/sessions");
    await expect(page.getByTestId("session-card").first()).toBeVisible({ timeout: 30_000 });
    await screenshot(page, SHOT_DIR, "list");
  });

  test("new session navigates back to chat welcome", async ({ page }) => {
    await seedSession(page);
    await page.goto("/sessions");
    await page.getByTestId("session-new").click();
    await expect(page).toHaveURL("/");
    await expect(page.getByTestId("welcome")).toBeVisible();
    await screenshot(page, SHOT_DIR, "new-session");
  });

  test("opening a session loads its history into chat", async ({ page }) => {
    await seedSession(page);
    await page.goto("/sessions");
    await expect(page.getByTestId("session-card").first()).toBeVisible();
    await page.getByTestId("session-card").first().click();
    await expect(page).toHaveURL("/");
    // History should render the prior turn (user + assistant messages).
    await expect(page.locator("[data-testid='message']")).toHaveCount(2, { timeout: 30_000 });
    await screenshot(page, SHOT_DIR, "opened-session");
  });

  test("delete removes the session from the list", async ({ page }) => {
    await seedSession(page);
    await page.goto("/sessions");
    // Wait for the seeded session to register in the (process-scoped) store
    // before counting. Under combined-suite load the chat-turn -> session
    // registration can race the navigation, leaving the list momentarily empty.
    await expect(page.getByTestId("session-card").first()).toBeVisible({ timeout: 30_000 });
    const before = await page.getByTestId("session-card").count();
    expect(before).toBeGreaterThan(0);

    const stop = autoConfirmDialog(page, true);
    await page.getByTestId("session-delete").first().click();
    stop();

    await expect(page.getByTestId("session-card")).toHaveCount(before - 1, {
      timeout: 30_000,
    });
    await screenshot(page, SHOT_DIR, "after-delete");
  });
});
