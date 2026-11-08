import { expect, test } from "@playwright/test";

// Real money path against the PayPal SANDBOX: AI drafts -> policy -> human approves -> execute -> verified by PayPal.
// Opt-in only (moves sandbox money, spends one LLM call): run `npm run test:e2e:sandbox`, which first re-bootstraps
// the demo world so case RC-2041 is open on a fresh real sandbox capture.
test.skip(process.env.E2E_SANDBOX !== "1", "sandbox money path is opt-in (E2E_SANDBOX=1)");
test.setTimeout(240_000);

test("propose -> approve -> execute -> verified at PayPal", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("incident-link").first().click();

  // 1. AI drafts a typed proposal for the legitimate case; the policy engine evaluates it.
  await page.getByRole("button", { name: "Draft proposal with AI (RC-2041)" }).click();
  await page.getByRole("button", { name: "Draft proposal", exact: true }).click();

  // 2. Human approves the exact amount/target/case (approval is bound to the details hash).
  const approve = page.getByRole("button", { name: "Approve", exact: true }).first();
  await expect(approve).toBeVisible({ timeout: 60_000 });
  await approve.click();
  await page.getByRole("button", { name: "Approve 12.00 USD" }).click();

  // 3. Execute: real PayPal sandbox refund.
  await page.getByRole("button", { name: "Execute refund" }).first().click();
  await page.getByRole("button", { name: "Refund 12.00 USD" }).click();

  // 4. Verified at PayPal: signed webhook if configured, else GET read-back.
  const badge = page.getByText(/Verified at PayPal/).first();
  for (let attempt = 0; attempt < 12 && !(await badge.isVisible().catch(() => false)); attempt++) {
    const verify = page.getByRole("button", { name: "Verify with PayPal" }).first();
    if (attempt >= 4 && (await verify.isVisible().catch(() => false))) await verify.click();
    await page.waitForTimeout(5_000);
    await page.reload();
  }
  await expect(badge).toBeVisible();
  await expect(page.getByLabel("Execution outcome").getByText("VERIFIED", { exact: true })).toBeVisible();
});
