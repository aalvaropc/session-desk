import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("language-select").selectOption("en");
});

test("demo supports search, provider filters and a visible conversation", async ({
  page,
}) => {
  await expect(page.getByTestId("session-row")).toHaveCount(12);
  await page.getByTestId("provider-filter").selectOption("codex");
  await expect(page.getByTestId("session-row")).toHaveCount(6);
  await page.getByTestId("search").fill("onboarding");
  await expect(page.getByTestId("session-row")).toHaveCount(1);
  await page.getByTestId("row-open").first().click();
  await expect(page.getByTestId("detail-panel")).toContainText("onboarding");
  await expect(page.getByTestId("copy-command")).toBeVisible();
});

test("native buttons keep Space behavior and hidden selections are cleared", async ({
  page,
}) => {
  const theme = page.getByTestId("theme-toggle");
  const initialTheme = await page.locator("html").getAttribute("data-theme");
  await theme.focus();
  await page.keyboard.press("Space");
  await expect(page.locator("html")).not.toHaveAttribute(
    "data-theme",
    initialTheme ?? "",
  );
  await page.getByTestId("row-select").first().check();
  await page.getByTestId("search").fill("there are no matching conversations");
  await expect(page.getByTestId("session-row")).toHaveCount(0);
  await page.getByTestId("search").blur();
  await page.keyboard.press("3");
  await expect(page.getByTestId("trash-selected")).toHaveCount(0);
  await page.getByTestId("search").fill("");
  await expect(page.getByTestId("row-select").first()).not.toBeChecked();
});

test("corrupt browser state recovers and review controls retain focus", async ({
  page,
}) => {
  await page.evaluate(() => {
    localStorage.setItem("session-desk:review:v1", "{invalid JSON");
    localStorage.setItem("cc-sessions-state", "{invalid JSON");
  });
  await page.reload();
  await expect(page.getByTestId("session-row")).toHaveCount(12);
  await page.getByTestId("row-open").first().click();
  const keep = page.getByTestId("review-keep");
  await keep.focus();
  await page.keyboard.press("Enter");
  await expect(keep).toBeFocused();
});

test("demo trash and restore never require a filesystem mutation", async ({
  page,
}) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST") requests.push(request.url());
  });
  await page.getByTestId("row-select").first().check();
  await page.getByTestId("trash-selected").click();
  await page.getByTestId("confirm-trash").click();
  await expect(page.getByTestId("session-row")).toHaveCount(11);
  await page.getByTestId("nav-trash").click();
  await page.getByTestId("restore-item").first().click();
  await page.getByTestId("nav-sessions").click();
  await expect(page.getByTestId("session-row")).toHaveCount(12);
  expect(requests).toEqual([]);
});

test("memories support search, linked detail and recovery", async ({
  page,
}) => {
  await page.getByTestId("nav-memories").click();
  await expect(page.getByTestId("memory-row")).toHaveCount(4);
  await page.getByTestId("search").fill("Keyboard conventions");
  await page.getByTestId("row-open").first().click();
  await expect(page.getByTestId("detail-panel")).toContainText("Keep focus");
  await page
    .getByTestId("detail-panel")
    .getByRole("button", { name: "writing-guidelines", exact: true })
    .click();
  await expect(page.getByTestId("detail-panel")).toContainText(
    "concrete action labels",
  );
});

test("Spanish, mobile list and detail remain usable without page overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByTestId("language-select").selectOption("es");
  await expect(page.getByTestId("nav-sessions")).toContainText("Sesiones");
  const first = page.getByTestId("session-row").first();
  const box = await first.boundingBox();
  expect(box?.y).toBeLessThan(430);
  await page.getByTestId("row-open").first().click();
  await expect(page.getByTestId("detail-panel")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
