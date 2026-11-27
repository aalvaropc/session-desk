import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

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
  await expect(page.getByTestId("session-row")).toHaveCount(14);
  await page.getByTestId("nav-trash").click();
  await page.getByTestId("restore-item").click();
  await page.getByTestId("nav-sessions").click();
  await expect(page.getByTestId("session-row")).toHaveCount(15);
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

test("finds full conversations beyond the preview for Claude and Codex", async ({
  page,
}) => {
  await page.goto("http://127.0.0.1:8768");
  for (const provider of ["claude", "codex"]) {
    await page
      .locator(`[data-testid="row-open"][data-open^="${provider}:"]`)
      .first()
      .click();
    await expect(
      page
        .locator(".message-text")
        .getByText(`${provider} synthetic middle message 0`, { exact: true }),
    ).toBeVisible();
  }
});

test("searches a saved transcript, copies context and creates a persistent linked note", async ({
  page,
  context,
}) => {
  await page.goto("http://127.0.0.1:8768");
  await page.getByTestId("language-select").selectOption("en");
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByTestId("search").fill("codex synthetic middle message 0");
  await expect(page.getByTestId("session-row")).toHaveCount(1);
  await page.getByTestId("row-open").click();
  await expect(page.locator(".message-hit mark")).toHaveText(
    "codex synthetic middle message 0",
  );
  await page.getByText("Resume context", { exact: true }).click();
  await page.getByRole("button", { name: "Copy context", exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    "Last request",
  );
  await page
    .locator(".message-hit")
    .getByRole("button", { name: "Save as note" })
    .click();
  await page.locator('input[name="title"]').fill("Synthetic decision");
  await page.locator('textarea[name="body"]').fill("Keep the source visible.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Note saved");
  await page.reload();
  await page.getByTestId("nav-memories").click();
  await expect(
    page.getByText("Synthetic decision", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Edit note", exact: true }).click();
  await page.locator('input[name="title"]').fill("Updated synthetic decision");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Updated synthetic decision", { exact: true }),
  ).toBeVisible();
  const downloadReady = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export Markdown", exact: true })
    .click();
  expect((await downloadReady).suggestedFilename()).toMatch(
    /^session-desk-note-.+\.md$/,
  );
  await page.getByRole("button", { name: "Open message", exact: true }).click();
  await expect(page.locator(".message-hit")).toContainText(
    "codex synthetic middle message 0",
  );
});

test("opens Antigravity CLI, App and IDE and drills into activity", async ({
  page,
}) => {
  await page.goto("http://127.0.0.1:8768");
  await page.getByTestId("language-select").selectOption("en");
  await page.getByTestId("provider-filter").selectOption("antigravity");
  await page.getByTestId("search").fill("synthetic shared run");
  await expect(page.getByTestId("session-row")).toHaveCount(3);
  for (const [title, action] of [
    ["Trace a CLI command", "Copy command"],
    ["Review a desktop conversation", "Copy title or ID"],
    ["Check editor changes", "Copy title or ID"],
  ]) {
    const row = page.getByTestId("session-row").filter({ hasText: title });
    await expect(row.getByTestId("row-select")).toBeDisabled();
    await row.getByTestId("row-open").click();
    await expect(page.getByTestId("copy-command")).toHaveText(action);
    await expect(page.locator(".message-hit mark")).toHaveText(
      "synthetic shared run",
    );
  }
  await page.getByTestId("nav-activity").click();
  await page.locator("#activity-days").selectOption("30");
  await page.locator("#provider").selectOption("antigravity");
  await page.getByRole("button", { name: "Trace a CLI command" }).click();
  await expect(page.getByTestId("detail-panel")).toContainText(
    "agy --conversation",
  );
});
