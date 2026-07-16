/**
 * Sessions UI E2E — session listing, switching, new-session, and delete.
 *
 * Backend has RAG_E2E_FAKES=1 with an in-memory fake session store, so a session
 * only appears after a chat turn registers it. The store is process-scoped and
 * shared by Playwright workers, so each test must select the session it seeded
 * instead of relying on list order.
 */
import { test, expect } from "@playwright/test";
import { screenshot, autoConfirmDialog } from "./helpers";

const SHOT_DIR = "sessions";
const SEEDED_QUESTION = "git 合并冲突如何解决？";

async function seedSession(page: import("@playwright/test").Page): Promise<string> {
  await page.goto("/");
  const input = page.getByTestId("chat-input");
  const requestPromise = page.waitForRequest((request) => {
    return new URL(request.url()).pathname === "/api/chat/stream" && request.method() === "POST";
  });
  await input.fill(SEEDED_QUESTION);
  await input.press("Enter");
  const request = await requestPromise;
  const payload = request.postDataJSON() as { session_id: string };
  expect(payload.session_id).toMatch(/^session_/);
  // Wait for the answer so the session is registered.
  await expect(page.locator("[data-testid='message'].assistant").last())
    .toContainText(/合并|冲突/, { timeout: 30_000 });
  return payload.session_id;
}

function seededSessionCard(page: import("@playwright/test").Page, sessionId: string) {
  const fallbackTitle = `${sessionId.substring(0, 12)}...`;
  return page.getByTestId("session-card").filter({
    has: page.getByText(fallbackTitle, { exact: true }),
  });
}

test.describe("Sessions UI", () => {
  test("a chat turn creates a session visible in the list", async ({ page }) => {
    const sessionId = await seedSession(page);
    await page.goto("/sessions");
    await expect(seededSessionCard(page, sessionId)).toBeVisible({ timeout: 30_000 });
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
    const sessionId = await seedSession(page);
    await page.goto("/sessions");
    const target = seededSessionCard(page, sessionId);
    await expect(target).toBeVisible({ timeout: 30_000 });
    await target.click();
    await expect(page).toHaveURL("/");
    // History should render the prior turn (user + assistant messages).
    const messages = page.locator("[data-testid='message']");
    await expect(messages).toHaveCount(2, { timeout: 30_000 });
    await expect(messages.nth(0)).toHaveClass(/user/);
    await expect(messages.nth(0)).toContainText(SEEDED_QUESTION);
    await expect(messages.nth(1)).toHaveClass(/assistant/);
    await screenshot(page, SHOT_DIR, "opened-session");
  });

  test("delete removes the session from the list", async ({ page }) => {
    const sessionId = await seedSession(page);
    await page.goto("/sessions");
    // Wait for the seeded session to register in the (process-scoped) store
    // before counting. Under combined-suite load the chat-turn -> session
    // registration can race the navigation, leaving the list momentarily empty.
    const target = seededSessionCard(page, sessionId);
    await expect(target).toBeVisible({ timeout: 30_000 });

    const stop = autoConfirmDialog(page, true);
    await target.getByTestId("session-delete").click();
    stop();

    await expect(target).toHaveCount(0, { timeout: 30_000 });
    await screenshot(page, SHOT_DIR, "after-delete");
  });
});
