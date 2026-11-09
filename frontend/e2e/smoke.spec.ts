import { expect, test } from "@playwright/test";

// Requires the PayOps backend running with at least one incident whose selected
// investigation has a finding (the BASELINE run is enough). Never triggers AI runs.
test("console loads, opens incident, drills through a claim", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("PayOps Sentinel").first()).toBeVisible();
  const incident = page.getByTestId("incident-link").first();
  await expect(incident).toBeVisible();
  await expect(page.locator(".ag-theme-mode").first()).toBeVisible();

  await incident.click();
  await expect(page.getByTestId("ms-driver")).toBeVisible();
  await expect(page.getByTestId("ms-corrective")).toBeVisible();
  await expect(page.getByTestId("ms-resolved")).toBeVisible();
  await expect(page.getByTestId("incident-command")).toBeVisible();
  await expect(page.getByTestId("hypothesis-row").first()).toBeVisible();
  await expect(page.getByText("Untrusted customer text").first()).toBeVisible();

  const claim = page.getByTestId("claim-row").first();
  await expect(claim).toBeVisible({ timeout: 45_000 });
  await claim.click();
  const drawer = page.getByTestId("evidence-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer.getByTestId("tool-result-json")).toBeVisible();
  await expect(drawer.getByText(/Ledger records/)).toBeVisible();

  // No horizontal page scroll at 1280px.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("proxy refuses paths outside the allowlist", async ({ request }) => {
  expect((await request.get("/api/backend/admin/secrets")).status()).toBe(404);
  expect((await request.get("/api/backend/incidents/../../etc")).status()).toBe(404);
  expect((await request.delete("/api/backend/incidents")).status()).toBe(405);
  expect((await request.post("/api/backend/config", { data: {} })).status()).toBe(404);
});
