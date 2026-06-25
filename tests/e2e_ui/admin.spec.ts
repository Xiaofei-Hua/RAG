/**
 * Admin UI E2E — health grid, circuit breakers, degradation mode, metrics.
 *
 * Backend has RAG_E2E_FAKES=1. These are read-mostly assertions plus the
 * degradation-mode switch (a row of buttons, not a <select>).
 */
import { test, expect } from "@playwright/test";
import { screenshot } from "./helpers";

const SHOT_DIR = "admin";

test.describe("Admin UI", () => {
  test("all four sections render", async ({ page }) => {
    await page.goto("/admin");
    await expect(page.getByTestId("admin-section-health")).toBeVisible();
    await expect(page.getByTestId("admin-section-circuits")).toBeVisible();
    await expect(page.getByTestId("admin-section-degradation")).toBeVisible();
    await expect(page.getByTestId("admin-section-metrics")).toBeVisible();
    await screenshot(page, SHOT_DIR, "overview");
  });

  test("degradation mode buttons switch active state", async ({ page }) => {
    await page.goto("/admin");
    // Default mode is 'full' (active).
    await expect(page.getByTestId("degradation-mode-full")).toHaveClass(/active/);

    await page.getByTestId("degradation-mode-cached").click();
    await expect(page.getByTestId("degradation-mode-cached")).toHaveClass(/active/);
    await expect(page.getByTestId("degradation-mode-full")).not.toHaveClass(/active/);
    await screenshot(page, SHOT_DIR, "mode-cached");

    // Restore full mode.
    await page.getByTestId("degradation-mode-full").click();
    await expect(page.getByTestId("degradation-mode-full")).toHaveClass(/active/);
  });
});
