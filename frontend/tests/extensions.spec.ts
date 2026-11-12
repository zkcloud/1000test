import { test, expect } from "@playwright/test";

test("自动跳题时双击不会越过多题", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "进入练习", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "开始练习 →", exact: true }).click();
  await page.getByLabel("选答后自动下一题").check();
  await expect(page.locator(".option").first()).toBeEnabled();
  await page.locator(".option").first().dblclick({ delay: 150 });
  await expect(page.locator(".question-top")).toContainText("原题号 102");
  await expect(page.locator(".exam-toolbar")).toContainText("1/100 已答");
});

test("按题组练习、暂停继续、标记和错题重练", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "进入练习", exact: true })
    .first()
    .click();
  await page.getByLabel("练习范围").selectOption("6");
  await page
    .getByLabel("题组（可选）")
    .selectOption({ label: "Part 6 · Questions 131–134" });
  await page.getByRole("button", { name: "开始练习 →", exact: true }).click();
  await expect(page.locator(".exam-toolbar")).toContainText("0/4 已答");
  await page.getByRole("button", { name: "暂停", exact: true }).click();
  await expect(page.locator(".option").first()).toBeDisabled();
  await expect(
    page.getByText("练习已暂停，用时已停止累计。", { exact: false }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "继续练习", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "继续练习", exact: true }).click();
  await page.getByRole("button", { name: "标记稍后检查", exact: true }).click();
  await page.locator(".option").first().click();
  await page.getByRole("button", { name: "结束练习", exact: true }).click();
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await expect(page.locator(".score-card strong")).toHaveText("0/1");
  await page.getByRole("button", { name: "重练错题", exact: true }).click();
  await expect(page.locator(".exam-toolbar")).toContainText("0/1 已答");
  await expect(
    page.getByRole("heading", { name: "Questions 131–134" }),
  ).toBeVisible();
  await expect(page.locator(".question-top")).toContainText("原题号 131");
});

test("深色主题与320px布局仍可阅读操作", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/");
  await expect(page.locator(".exam-card")).toHaveCount(10);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page
    .getByRole("button", { name: "进入练习", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "开始练习 →", exact: true }).click();
  await expect(page.locator(".options")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: `../reports/release/${testInfo.project.name}-dark-320.png`,
    fullPage: true,
  });
});

test("孤立的本地待同步记录可明确放弃，不会永久阻塞新练习", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".exam-card")).toHaveCount(10);
  await page.evaluate(() =>
    localStorage.setItem(
      "reader-pending",
      JSON.stringify({
        aid: "missing-record",
        qid: 1,
        selection: "A",
        revision: 0,
      }),
    ),
  );
  await page.reload();
  await expect(page.locator(".pending-notice")).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "放弃未同步选择", exact: true })
    .click();
  await expect(page.locator(".pending-notice")).toHaveCount(0);
  await page
    .getByRole("button", { name: "进入练习", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "开始练习 →", exact: true }).click();
  await expect(page.locator(".options")).toBeVisible();
});
