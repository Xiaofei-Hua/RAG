/**
 * Chat UI E2E — covers the chat flows AGENTS.md §0 rule #2 requires.
 *
 * Runs against the built web/dist SPA served by the FastAPI backend. The
 * backend uvicorn process has RAG_E2E_FAKES=1 set (see web/playwright.config.ts
 * + tests/e2e_ui/_fakes.py), so it serves deterministic canned answers WITHOUT
 * Ollama/Milvus. Every interaction is captured with a screenshot into
 * tests/e2e_ui/screenshots/.
 *
 * Covered: welcome render, identity shortcut (no LLM), deep (thinking) RAG,
 * fast-mode RAG, SSE streaming, the sources panel, and feedback
 * (thumbs up / down / correction) which drives the eval flywheel.
 */
import { test, expect } from "@playwright/test";
import { screenshot } from "./helpers";

const SHOT_DIR = "chat";

test.describe("Chat UI", () => {
  test("welcome screen renders with quick questions", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("welcome")).toBeVisible();
    await expect(page.getByTestId("quick-q-1")).toBeVisible();
    await screenshot(page, SHOT_DIR, "welcome");
  });

  test("identity question answers without LLM (你是谁)", async ({ page }) => {
    await page.goto("/");
    const input = page.getByTestId("chat-input");
    await input.fill("你是谁");
    await input.press("Enter");

    // Identity shortcut returns a capability string (no LLM needed).
    await expect(page.locator("[data-testid='message'].assistant").last())
      .toContainText(/智能|RAG|问答|助手/, { timeout: 30_000 });
    await screenshot(page, SHOT_DIR, "identity-answer");
  });

  test("deep (thinking) mode answers a RAG question with a diagnosis", async ({ page }) => {
    await page.goto("/");
    // Ensure thinking mode (default).
    await expect(page.getByTestId("mode-thinking")).toHaveClass(/active/);
    const input = page.getByTestId("chat-input");
    await input.fill("发动机振动异常如何排查？");
    await input.press("Enter");

    // Fake harness returns a canned PHM diagnosis answer.
    await expect(page.locator("[data-testid='message'].assistant").last())
      .toContainText(/诊断|振动|不平衡|频谱/, { timeout: 30_000 });
    await screenshot(page, SHOT_DIR, "deep-answer");
  });

  test("fast mode answers a RAG question", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("mode-fast").click();
    await expect(page.getByTestId("mode-fast")).toHaveClass(/active/);
    const input = page.getByTestId("chat-input");
    await input.fill("液压系统压力低的排故流程是什么？");
    await input.press("Enter");

    await expect(page.locator("[data-testid='message'].assistant").last())
      .toContainText(/诊断|液压|压力/, { timeout: 30_000 });
    await screenshot(page, SHOT_DIR, "fast-answer");
  });

  test("SSE streaming emits a final answer", async ({ page }) => {
    await page.goto("/");
    // Streaming is on by default; the toggle reflects that.
    await expect(page.getByTestId("stream-toggle")).toBeVisible();
    const streamResp = page.waitForResponse(
      (r) => r.url().includes("/api/chat/stream"),
      { timeout: 30_000 }
    );
    const input = page.getByTestId("chat-input");
    await input.fill("发动机振动异常如何排查？");
    await input.press("Enter");
    const resp = await streamResp;
    expect(resp.ok()).toBeTruthy();

    // The assistant message should gain content via token events.
    await expect(page.locator("[data-testid='message'].assistant").last())
      .toContainText(/诊断|振动|不平衡|频谱/, { timeout: 30_000 });
    await screenshot(page, SHOT_DIR, "stream-answer");
  });

  test("sources panel opens when an answer has sources", async ({ page }) => {
    await page.goto("/");
    const input = page.getByTestId("chat-input");
    await input.fill("发动机振动异常如何排查？");
    await input.press("Enter");
    // Wait for the answer to land first.
    await expect(page.locator("[data-testid='message'].assistant").last())
      .toContainText(/诊断|振动/, { timeout: 30_000 });

    const toggle = page.getByTestId("sources-toggle");
    if (await toggle.count()) {
      await toggle.first().click();
      await expect(page.getByTestId("sources-panel")).toBeVisible();
      await screenshot(page, SHOT_DIR, "sources-panel");
    }
  });
});

// Helper: seed a Q&A turn so an assistant message with a feedback row exists.
async function seedAnswer(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/");
  const input = page.getByTestId("chat-input");
  await input.fill("发动机振动异常如何排查？");
  await input.press("Enter");
  await expect(page.locator("[data-testid='message'].assistant").last())
    .toContainText(/诊断|振动/, { timeout: 30_000 });
  // The feedback row renders once streaming completes.
  await expect(page.getByTestId("feedback-row").first()).toBeVisible({ timeout: 10_000 });
}

test.describe("Chat feedback", () => {
  test("thumbs up submits and marks the message as feedbacked", async ({ page }) => {
    await seedAnswer(page);
    await page.getByTestId("feedback-up").first().click();
    await expect(page.getByTestId("feedback-done").first()).toBeVisible({ timeout: 10_000 });
    await screenshot(page, SHOT_DIR, "feedback-up");
  });

  test("thumbs down submits and marks the message as feedbacked", async ({ page }) => {
    await seedAnswer(page);
    await page.getByTestId("feedback-down").first().click();
    await expect(page.getByTestId("feedback-done").first()).toBeVisible({ timeout: 10_000 });
    await screenshot(page, SHOT_DIR, "feedback-down");
  });

  test("correction opens the input, submits, and marks feedbacked", async ({ page }) => {
    await seedAnswer(page);
    await page.getByTestId("feedback-correct-open").first().click();
    await expect(page.getByTestId("correction-box").first()).toBeVisible();
    await page.getByTestId("correction-input").first().fill("应先检查转子平衡，再测频谱。");
    await screenshot(page, SHOT_DIR, "correction-input");
    await page.getByTestId("correction-submit").first().click();
    await expect(page.getByTestId("feedback-done").first()).toBeVisible({ timeout: 10_000 });
    await screenshot(page, SHOT_DIR, "correction-submitted");
  });
});
