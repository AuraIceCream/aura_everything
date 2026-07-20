import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("asks a grounded question and opens evidence", async ({ page }) => {
  await page.goto("/ask");
  await page.getByLabel("Ask a biology question").fill("How does the electron transport chain create ATP?");
  await page.getByRole("button", { name: "Ask AURA" }).click();
  await expect(page.getByText("Core idea")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /Open citation/ }).first().click();
  await expect(page.getByRole("heading", { name: "Sources used" })).toBeVisible();
});

test("compares retrieval and exposes a structured trace", async ({ page }) => {
  await page.goto("/retrieval");
  await page.getByRole("button", { name: /Run comparison/ }).click();
  await expect(page.getByText("3 evidence candidates")).toBeVisible();
  await page.goto("/traces/run-demo-4821");
  await expect(page.getByRole("heading", { name: "Stage-by-stage trace" })).toBeVisible();
  await expect(page.getByText("What this trace deliberately excludes")).toBeVisible();
});

test("desktop sidebar closes, reopens, and remembers its state", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Desktop navigation behavior");
  await page.goto("/settings");
  await page.getByRole("button", { name: "Close sidebar" }).click();
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Open sidebar" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Open sidebar" })).toBeVisible();
  await page.getByRole("button", { name: "Open sidebar" }).click();
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
});

test("desktop sidebar previews when the collapsed menu is hovered", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Desktop hover behavior");
  await page.goto("/ask");
  await page.getByRole("button", { name: "Close sidebar" }).click();
  const menu = page.getByRole("button", { name: "Open sidebar" });
  await menu.dispatchEvent("mouseenter");
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await page.getByRole("heading", { name: "Understand biology." }).hover();
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).not.toBeVisible();
});

test("opens the mock activity feed and controls a simulated process", async ({ page }) => {
  await page.goto("/ask");
  await page.getByLabel("Open demo runs and processes").click();
  await expect(page.getByRole("heading", { name: "Runs & processes" })).toBeVisible();
  await expect(page.locator(".activity-popover").getByRole("link", { name: /How does the electron transport chain/ })).toBeVisible();
  await page.getByRole("button", { name: "Pause Chunk generation" }).click();
  await expect(page.getByRole("button", { name: "Resume Chunk generation" })).toBeVisible();
});

test("core route is free of serious accessibility violations", async ({ page }) => {
  await page.goto("/ask");
  const results = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
  expect(results.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);
});
