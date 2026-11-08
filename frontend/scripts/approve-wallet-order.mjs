// Approve ONE PayPal sandbox order as the sandbox personal (buyer) account.
// Usage: node scripts/approve-wallet-order.mjs <approval-url> <return-url-prefix>
// Reads SANDBOX_BUYER_EMAIL / SANDBOX_BUYER_PASSWORD from the environment (never logged).
// Exit codes: 0 approved, 2 missing credentials, 3 CAPTCHA/verification challenge (stop, human needed), 4 other failure.
import { chromium } from "@playwright/test";

const [approvalUrl, returnPrefix] = process.argv.slice(2);
const email = process.env.SANDBOX_BUYER_EMAIL;
const password = process.env.SANDBOX_BUYER_PASSWORD;
if (!approvalUrl || !returnPrefix) { console.error("usage: approve-wallet-order.mjs <approval-url> <return-url-prefix>"); process.exit(4); }
if (!email || !password) { console.error("SANDBOX_BUYER_EMAIL / SANDBOX_BUYER_PASSWORD not set"); process.exit(2); }
if (!new URL(approvalUrl).hostname.endsWith("sandbox.paypal.com")) { console.error("refusing non-sandbox approval URL"); process.exit(4); }

const CHALLENGE = /captcha|security challenge|verify (it'?s|that it'?s) you|confirm it'?s you|one-time code|security check/i;

// Only a challenge the user would actually SEE counts: PayPal loads CAPTCHA-provider iframes invisibly for
// background risk scoring, which is not a challenge. A visible challenge frame or visible challenge text stops us.
async function challenged(page) {
  const text = await page.locator("body").innerText().catch(() => "");
  const frames = page.locator('iframe[src*="captcha" i], iframe[src*="arkose" i], iframe[title*="captcha" i], iframe[title*="challenge" i]');
  const count = await frames.count().catch(() => 0);
  for (let i = 0; i < count; i++) {
    const box = await frames.nth(i).boundingBox().catch(() => null);
    if (box && box.width > 40 && box.height > 40 && (await frames.nth(i).isVisible().catch(() => false))) return true;
  }
  return CHALLENGE.test(text);
}

async function stopIfChallenged(page, stage) {
  if (await challenged(page)) {
    console.error(`STOP: PayPal showed a CAPTCHA / verification challenge at stage "${stage}". Not attempting to bypass it.`);
    await page.screenshot({ path: "test-results/paypal-challenge.png" }).catch(() => {});
    process.exit(3);
  }
}

const browser = await chromium.launch({ headless: process.env.HEADLESS !== "0" ? true : false });
const page = await browser.newPage();
try {
  await page.goto(approvalUrl, { waitUntil: "domcontentloaded" });
  await stopIfChallenged(page, "open");
  const emailBox = page.locator("#email");
  if (await emailBox.isVisible({ timeout: 15000 }).catch(() => false)) {
    await emailBox.fill(email);
    const next = page.locator("#btnNext");
    if (await next.isVisible().catch(() => false)) await next.click();
    await stopIfChallenged(page, "after email");
    await page.locator("#password").fill(password, { timeout: 15000 });
    await page.locator("#btnLogin").click();
  }
  await page.waitForLoadState("domcontentloaded");
  await stopIfChallenged(page, "after login");
  const pay = page.locator('#payment-submit-btn, button[data-testid="submit-button-initial"], button:has-text("Complete Purchase"), button:has-text("Pay Now"), button:has-text("Continue")').first();
  await pay.click({ timeout: 30000 });
  await page.waitForURL((u) => u.toString().startsWith(returnPrefix), { timeout: 45000 });
  console.log("APPROVED");
  process.exit(0);
} catch (err) {
  await stopIfChallenged(page, "failure");
  console.error(`approval failed: ${err?.message ?? err}`);
  await page.screenshot({ path: "test-results/paypal-approval-failure.png" }).catch(() => {});
  process.exit(4);
} finally {
  await browser.close();
}
