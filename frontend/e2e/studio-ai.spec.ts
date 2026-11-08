import { expect, test } from "@playwright/test";

// AG Studio AI assistant wiring. Never sends a message: a send would spend Claude API credit.
test("AI assistant is offered in edit mode and makes no LLM call on load", async ({ page }) => {
  const llmCalls: string[] = [];
  page.on("request", (r) => r.url().includes("/api/backend/studio/llm") && llmCalls.push(r.url()));

  await page.goto("/");
  await page.getByRole("button", { name: "Edit layout" }).first().click();
  await expect(page.getByRole("button", { name: "AI Assistant" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Investigate the open incident" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Send message" }).first()).toBeVisible();

  await page.waitForTimeout(2_000);
  expect(llmCalls).toEqual([]);
});

test("studio config never carries the Anthropic key", async ({ request }) => {
  const res = await request.get("/api/backend/studio/config");
  expect(res.status()).toBe(200);
  const body = await res.text();
  expect(body).not.toMatch(/sk-ant-/);
  expect(JSON.parse(body).data).toHaveProperty("ai_enabled");
});
