import { test, expect, type Page } from "@playwright/test";

async function begin(page: Page, mode: "exam" | "practice", part?: number) {
  await page.goto("/");
  await page
    .getByRole("button", {
      name: mode === "exam" ? "开始考试" : "进入练习",
      exact: true,
    })
    .first()
    .click();
  if (part) await page.getByLabel("练习范围").selectOption(String(part));
  await page
    .getByRole("button", {
      name: mode === "exam" ? "确认开始考试 →" : "开始练习 →",
      exact: true,
    })
    .click();
  await expect(page.locator(".options")).toBeVisible();
}

test("考试答案隔离、交卷成绩、历史与只读回顾", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await begin(page, "exam");
  await expect(page.getByText("正确答案", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "查看答案与解析" }),
  ).toHaveCount(0);
  const payload = await page.evaluate(async () => {
    const id = location.hash.split("/")[2];
    return (await fetch(`/api/attempts/${id}/questions/1`)).json();
  });
  expect(payload).not.toHaveProperty("answer");
  expect(payload).not.toHaveProperty("explanation");
  await page.locator(".option").first().click();
  await expect(page.getByText("已保存到服务端", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "交卷", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("未答 99 题");
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await expect(page.locator(".score-card strong")).toHaveText("1/100");
  await page.screenshot({
    path: `../reports/release/${testInfo.project.name}-result.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "逐题回顾 →" }).click();
  await expect(page.getByRole("heading", { name: "正确答案 A" })).toBeVisible();
  await expect(page.locator(".option").first()).toBeDisabled();
  await page.getByRole("button", { name: "试卷大厅", exact: true }).click();
  await expect(page.locator(".history-list")).toContainText("1/100 分");
  expect(errors).toEqual([]);
});

test("自动下一题默认关闭、保存成功后跳题并恢复设置", async ({ page }) => {
  await begin(page, "practice", 5);
  const toggle = page.getByLabel("选答后自动下一题");
  await expect(toggle).not.toBeChecked();
  await page.locator(".option").first().click();
  await expect(page.locator(".question-top")).toContainText("原题号 101");
  await toggle.check();
  await expect(page.locator(".option").first()).toBeEnabled();
  await expect(page.locator(".question-top")).toContainText("原题号 101");
  await page.locator(".option").nth(1).click();
  await expect(page.locator(".question-top")).toContainText("原题号 102");
  await page.reload();
  await expect(page.getByLabel("选答后自动下一题")).toBeChecked();
  await expect(page.locator(".question-top")).toContainText("原题号 102");
  if (await page.getByRole("button", { name: "展开", exact: true }).isVisible())
    await page.getByRole("button", { name: "展开", exact: true }).click();
  await page.getByRole("button", { name: "130题，未答", exact: true }).click();
  await page.locator(".option").first().click();
  await expect(
    page.getByText("已记录最后一题", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".question-top")).toContainText("原题号 130");
});

test("练习未答即可看解析且首次独立作答统计不被改写", async ({ page }) => {
  await begin(page, "practice", 5);
  await page
    .getByRole("button", { name: "查看答案与解析", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "正确答案 A" })).toBeVisible();
  await expect(page.locator(".answer-panel")).toContainText("尚未作答");
  await page.locator(".option").first().click();
  await page.getByRole("button", { name: "下一题 →" }).click();
  await expect(page.getByRole("heading", { name: "正确答案 A" })).toHaveCount(
    0,
  );
  await page.locator(".option").nth(1).click();
  await page.getByRole("button", { name: "核对本题 · 答案与解析" }).click();
  await expect(page.locator(".answer-panel")).toContainText("正确答案 A");
  await page.locator(".option").first().click();
  await page.getByRole("button", { name: "结束练习", exact: true }).click();
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await expect(page.locator(".score-card strong")).toHaveText("0/1");
  await expect(page.locator(".metric").first()).toContainText("1 题");
});

test("保存失败不跳题，刷新后可重试本地作答", async ({ page }) => {
  await begin(page, "practice", 5);
  await page.getByLabel("选答后自动下一题").check();
  await expect(page.locator(".option").first()).toBeEnabled();
  await page.route("**/api/attempts/*/questions/*/answer", (route) =>
    route.abort("failed"),
  );
  await page.locator(".option").first().click();
  await expect(page.locator(".pending-notice")).toBeVisible();
  await expect(page.locator(".question-top")).toContainText("原题号 101");
  await page.reload();
  await expect(page.locator(".pending-notice")).toBeVisible();
  await page.unroute("**/api/attempts/*/questions/*/answer");
  await page.getByRole("button", { name: "重试保存", exact: true }).click();
  await expect(page.locator(".pending-notice")).toHaveCount(0);
  await expect(page.locator(".option").first()).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("共用材料完整图片与同组切题，响应式无页面横向溢出", async ({
  page,
}, testInfo) => {
  await begin(page, "practice", 6);
  await expect(
    page.getByRole("heading", { name: "Questions 131–134" }),
  ).toBeVisible();
  await expect(page.locator(".material-panel img").first()).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator(".material-panel img")
        .first()
        .evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBeGreaterThan(0);
  await page
    .locator(".material-panel")
    .evaluate((el) => el.setAttribute("data-retained", "yes"));
  await page.getByRole("button", { name: "下一题 →" }).click();
  await expect(page.locator(".question-top")).toContainText("原题号 132");
  await expect(page.locator(".material-panel")).toHaveAttribute(
    "data-retained",
    "yes",
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: `../reports/release/${testInfo.project.name}-reading.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "文字", exact: true }).click();
  await expect(page.locator(".reading-text")).toContainText(
    "Bank Mortgage Rates Will Fall",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("大厅与键盘可操作", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.locator(".exam-card")).toHaveCount(10);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "跳到主要内容" })).toBeFocused();
  await page.keyboard.press("Tab");
  await page.screenshot({
    path: `../reports/release/${testInfo.project.name}-home.png`,
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});
