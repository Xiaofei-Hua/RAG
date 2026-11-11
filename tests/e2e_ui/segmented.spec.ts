import { test, expect } from "@playwright/test";
import { screenshot } from "./helpers";

for (const stop of [false, true]) {
  test(`checked prefix survives ${stop ? "stop" : "partial completion"}`, async ({ page }) => {
    await page.addInitScript(() => {
      const original = window.fetch.bind(window);
      const target = window as typeof window & { finishSegment?: () => void };
      window.fetch = async (input, init) => {
        if (!String(input).includes("/api/chat/stream")) return original(input, init);
        const encoder = new TextEncoder();
        const body = new ReadableStream({
          start(controller) {
            const send = (event: object) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
            send({ type: "token", content: "A与B记录值相同；温度不同，不能外推。[记录.txt]" });
            target.finishSegment = () => {
              send({ type: "token", content: "\n\n回答尚未完成，请重试。" });
              send({ type: "done", full_response: "A与B记录值相同；温度不同，不能外推。[记录.txt]\n\n回答尚未完成，请重试。", metadata: { generation_complete: false, reason: "length", status: "incomplete" } });
              controller.close();
            };
            init?.signal?.addEventListener("abort", () => controller.error(new DOMException("Stopped", "AbortError")));
          },
        });
        return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
      };
    });
    await page.goto("/");
    await page.getByTestId("chat-input").fill("比较记录值及适用条件");
    await page.getByTestId("chat-input").press("Enter");
    const answer = page.locator("[data-testid='message'].assistant").last();
    await expect(answer).toContainText("温度不同，不能外推");
    await screenshot(page, "segmented", stop ? "before-stop" : "first-segment");
    if (stop) await page.getByTestId("chat-stop").click();
    else await page.evaluate(() => (window as typeof window & { finishSegment: () => void }).finishSegment());
    await expect(page.getByTestId("generation-incomplete")).toBeVisible();
    await expect(answer).toContainText("A与B记录值相同");
    await expect(page.getByTestId("chat-input")).toBeEnabled();
    await screenshot(page, "segmented", stop ? "stopped" : "incomplete");
  });
}


test("history retains the incomplete notice", async ({ page, request }) => {
  await request.post("/api/chat", { data: { message: "你是谁", session_id: "partial-ui-history" } });
  await page.route("**/api/chat/history/partial-ui-history**", (route) => route.fulfill({
    json: { session_id: "partial-ui-history", total_messages: 1, messages: [{
      role: "assistant", content: "已检查的首段[资料.txt]", metadata: { generation_complete: false, status: "incomplete" },
    }] },
  }));
  await page.goto("/sessions");
  await page.locator('[data-testid="session-card"][data-session-id="partial-ui-history"]').click();
  await expect(page.getByTestId("generation-incomplete")).toBeVisible();
  await expect(page.locator("[data-testid='message'].assistant")).toContainText("已检查的首段");
  await screenshot(page, "segmented", "incomplete-history");
});
