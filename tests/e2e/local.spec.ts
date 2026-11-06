import { expect, test } from "@playwright/test";

test("local API powers session and memory trash and restore against isolated files", async ({
  page,
  context,
}) => {
  await page.goto("http://127.0.0.1:8768");
  await page.getByTestId("language-select").selectOption("en");
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByTestId("copy-command").click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    "claude --resume",
  );
  await page.getByTestId("row-select").first().check();
  await page.getByTestId("trash-selected").click();
  await page.getByTestId("confirm-trash").click();
  await expect(page.getByTestId("session-row")).toHaveCount(11);
  await page.getByTestId("nav-trash").click();
  await page.getByTestId("restore-item").click();
  await page.getByTestId("nav-sessions").click();
  await expect(page.getByTestId("session-row")).toHaveCount(12);
  await page.getByTestId("nav-memories").click();
  await page.getByTestId("row-select").first().check();
  await page.getByTestId("trash-selected").click();
  await page.getByTestId("confirm-trash").click();
  await expect(page.getByTestId("memory-row")).toHaveCount(3);
  await page.getByTestId("nav-trash").click();
  await page.getByTestId("restore-item").click();
  await page.getByTestId("nav-memories").click();
  await expect(page.getByTestId("memory-row")).toHaveCount(4);
});
