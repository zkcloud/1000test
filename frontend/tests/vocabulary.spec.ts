import { expect, test, type Page } from "@playwright/test";

const roundLength = 10;
const searchLabel = "搜索英文或中文释义";
const detailLabel = "词条详情";
const feedbackLabel = "答题反馈";

function button(page: Page, name: string) {
  return page.getByRole("button", { name, exact: true });
}

function words(page: Page) {
  return page.getByRole("region", { name: "词表", exact: true });
}

function detail(page: Page) {
  return page.getByRole("region", { name: detailLabel, exact: true });
}

function wordRow(page: Page, term: string) {
  return words(page)
    .getByRole("button")
    .filter({ has: page.getByText(term, { exact: true }) });
}

async function openVocabulary(page: Page) {
  await page.goto("/");
  await expect(page.locator(".exam-card")).toHaveCount(10);
  await button(page, "我要背单词").click();
  await expect(page).toHaveURL(/#\/vocabulary$/);
  await expect(
    page.getByRole("heading", { name: "我要背单词", exact: true }),
  ).toBeVisible();
}

async function enterSearch(page: Page, query: string) {
  const loaded = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === "/api/vocabulary/words" &&
      url.searchParams.get("q") === query
    );
  });
  await page.getByLabel(searchLabel).fill(query);
  expect((await loaded).ok()).toBeTruthy();
  await expect(words(page)).not.toHaveAttribute("aria-busy", "true");
}

async function assertFitsViewport(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(await page.evaluate(() => window.innerWidth));
}

// A learner can check the cue in a second tab with the visible word list.
async function consultWordList(
  reference: Page,
  cue: string,
  choice?: { options: string[]; pos: string },
) {
  await enterSearch(reference, cue);
  const terms = words(reference).getByRole("button").locator("[lang=en]");
  await expect(terms.first()).toBeVisible();
  if (!choice) return (await terms.first().innerText()).trim();
  const candidates = [];
  for (const term of choice.options) {
    const row = wordRow(reference, term);
    if (!(await row.isVisible())) continue;
    const summaries = await row.locator(".vocabulary-word-meaning").innerText();
    const shownSense = `${choice.pos} ${cue}`.normalize("NFKC");
    if (
      summaries
        .split(" · ")
        .some((item) => item.normalize("NFKC").trim() === shownSense)
    ) {
      candidates.push(term);
    }
  }
  expect(candidates, `词表中符合「${cue}」的可选项`).toHaveLength(1);
  return candidates[0]!;
}

async function getFeedback(
  page: Page,
  correct: boolean,
  userAnswer: string,
  word: string,
) {
  const feedback = page.getByRole("region", {
    name: feedbackLabel,
    exact: true,
  });
  await expect(feedback).toBeVisible();
  await expect(feedback).toContainText(correct ? "回答正确" : "回答错误");
  await expect(feedback.getByText("你的答案", { exact: true })).toBeVisible();
  await expect(feedback.getByText("正确答案", { exact: true })).toBeVisible();
  await expect(
    feedback.getByText(userAnswer, { exact: true }).first(),
  ).toBeVisible();
  await expect(feedback.getByText(word, { exact: true }).first()).toBeVisible();
  for (const label of ["释义", "用法", "例句"])
    await expect(
      feedback.getByRole("heading", { name: label, exact: true }),
    ).toBeVisible();
  await expect(feedback.locator("blockquote p[lang=en]")).not.toBeEmpty();
  await expect(feedback.locator("blockquote p:not([lang])")).not.toBeEmpty();
  return feedback;
}

test("从试卷大厅查英文和中文、按套次查看释义用法例句及页码", async ({
  page,
}, testInfo) => {
  if (testInfo.project.name === "mobile")
    await page.setViewportSize({ width: 390, height: 844 });
  await openVocabulary(page);
  const back = page.getByRole("button", { name: /返回词表/ });
  await words(page).locator(".vocabulary-word").first().click();
  for (const label of ["释义", "用法", "例句"])
    await expect(
      detail(page).getByRole("heading", { name: label, exact: true }).first(),
    ).toBeVisible();
  if (testInfo.project.name === "mobile") await back.click();

  await enterSearch(page, "additional");
  await wordRow(page, "additional").click();
  await expect(
    detail(page).getByRole("heading", { name: /^additional\b/ }),
  ).toBeVisible();
  await expect(detail(page)).toContainText(/附加的|另外的/);
  for (const label of ["释义", "用法", "例句"])
    await expect(
      detail(page).getByRole("heading", { name: label, exact: true }).first(),
    ).toBeVisible();
  await expect(detail(page)).toContainText(/原书例句|原书题句|补充例句/);
  await expect(detail(page)).toContainText(/PDF\s*第\s*450\s*页/);
  await assertFitsViewport(page);
  await testInfo.attach("词条详情", {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });

  if (testInfo.project.name === "mobile") {
    await expect(words(page)).not.toBeVisible();
    await back.click();
  }
  await expect(words(page)).toBeVisible();
  await enterSearch(page, "附加的");
  await expect(wordRow(page, "additional")).toBeVisible();
  const filtered = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === "/api/vocabulary/words" &&
      url.searchParams.get("test") === "10"
    );
  });
  await page.getByLabel("选择套次").selectOption({ label: "Test 10" });
  expect((await filtered).ok()).toBeTruthy();
  await enterSearch(page, "reservation");
  await wordRow(page, "reservation").click();
  await expect(detail(page)).toContainText("预订");
  await expect(detail(page)).toContainText("Test 10");
  await assertFitsViewport(page);
});

test("完成十道选择题、查看对错和释义例句、重新开始一轮", async ({
  page,
  context,
}, testInfo) => {
  test.setTimeout(90_000);
  if (testInfo.project.name === "mobile")
    await page.setViewportSize({ width: 390, height: 844 });
  await openVocabulary(page);
  const reference = await context.newPage();
  await reference.setViewportSize({ width: 1100, height: 900 });
  await openVocabulary(reference);
  await page.bringToFront();
  await button(page, "选择练习").click();
  const seen = new Set<string>();
  const submit = button(page, "提交答案");
  for (let index = 1; index <= roundLength; index += 1) {
    await expect(
      page.getByText(`第 ${index} / ${roundLength} 题`, { exact: true }),
    ).toBeVisible();
    await expect(submit).toBeDisabled();
    await expect(page.getByRole("region", { name: feedbackLabel })).toHaveCount(
      0,
    );
    const radios = page.getByRole("radio");
    await expect(radios).toHaveCount(4);
    const choices = (
      await page
        .locator("label:has(input[type=radio]) [lang=en]")
        .allInnerTexts()
    ).map((word) => word.trim());
    expect(new Set(choices).size).toBe(4);
    const word = await consultWordList(
      reference,
      (await page.locator(".vocabulary-cue").innerText()).trim(),
      {
        options: choices,
        pos: (
          await page.locator(".vocabulary-prompt .vocabulary-pos").innerText()
        ).trim(),
      },
    );
    expect(seen.has(word)).toBeFalsy();
    seen.add(word);
    const answer =
      index === 1 ? choices.find((choice) => choice !== word)! : word;
    await page.getByRole("radio", { name: answer, exact: true }).check();
    await submit.click();
    await getFeedback(page, index !== 1, answer, word);
    if (index === 1) {
      await assertFitsViewport(page);
      await testInfo.attach("选择题答错反馈", {
        body: await page.screenshot({ fullPage: true }),
        contentType: "image/png",
      });
    }
    await button(
      page,
      index === roundLength ? "查看本轮结果" : "下一题",
    ).click();
  }
  await expect(
    page.getByRole("heading", { name: "本轮练习完成" }),
  ).toBeVisible();
  await expect(page.getByText(/答对\s*9\s*\/\s*10\s*题/)).toBeVisible();
  await button(page, "再练一轮").click();
  await expect(page.getByText("第 1 / 10 题", { exact: true })).toBeVisible();
  await expect(page.getByText("已答对 0 题", { exact: true })).toBeVisible();
  await expect(submit).toBeDisabled();
  await reference.close();
});

test("键盘完成十道拼写题、忽略大小写和空格、返回大厅无背词历史", async ({
  page,
  context,
}, testInfo) => {
  test.setTimeout(90_000);
  if (testInfo.project.name === "mobile")
    await page.setViewportSize({ width: 390, height: 844 });
  await openVocabulary(page);
  const reference = await context.newPage();
  await reference.setViewportSize({ width: 1100, height: 900 });
  await openVocabulary(reference);
  await page.bringToFront();
  await button(page, "拼写练习").click();
  const spelling = page.getByRole("textbox", { name: "你的拼写", exact: true });
  const seen = new Set<string>();
  for (let index = 1; index <= roundLength; index += 1) {
    await expect(
      page.getByText(`第 ${index} / ${roundLength} 题`, { exact: true }),
    ).toBeVisible();
    await expect(spelling).toHaveValue("");
    await expect(page.getByRole("region", { name: feedbackLabel })).toHaveCount(
      0,
    );
    await spelling.fill("   ");
    await expect(button(page, "提交答案")).toBeDisabled();
    const word = await consultWordList(
      reference,
      (await page.locator(".vocabulary-cue").innerText()).trim(),
    );
    expect(seen.has(word)).toBeFalsy();
    seen.add(word);
    const answer =
      index === 1
        ? `${word}x`
        : index === 2
          ? `  ${word.toUpperCase()}  `
          : word;
    await spelling.fill(answer);
    await spelling.press("Enter");
    await getFeedback(page, index !== 1, answer.trim(), word);
    if (index === 2) {
      await assertFitsViewport(page);
      await testInfo.attach("拼写题答对反馈", {
        body: await page.screenshot({ fullPage: true }),
        contentType: "image/png",
      });
    }
    await button(
      page,
      index === roundLength ? "查看本轮结果" : "下一题",
    ).click();
  }
  await expect(
    page.getByRole("heading", { name: "本轮练习完成" }),
  ).toBeVisible();
  await expect(page.getByText(/答对\s*9\s*\/\s*10\s*题/)).toBeVisible();
  await button(page, "试卷大厅").click();
  await expect(page.locator(".exam-card")).toHaveCount(10);
  await expect(
    page.getByText("下一次进步，从第一次开始。", { exact: true }),
  ).toBeVisible();
  await button(page, "我要背单词").click();
  await button(page, "拼写练习").click();
  await expect(page.getByText("第 1 / 10 题", { exact: true })).toBeVisible();
  await expect(page.getByText("已答对 0 题", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/#\/vocabulary$/);
  await expect(page.getByLabel(searchLabel)).toBeVisible();
  await reference.close();
});

test("作答中的试卷切换背单词保留离开提示，返回大厅可继续", async ({ page }) => {
  await page.goto("/");
  await button(page, "开始考试").first().click();
  await button(page, "确认开始考试 →").click();
  await page.locator(".option").first().click();
  await expect(page.getByText("已保存到服务端", { exact: true })).toBeVisible();
  const attemptUrl = page.url();
  await button(page, "我要背单词").click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "前往背单词？" }),
  ).toBeVisible();
  await expect(dialog).toContainText("已答 1 题");
  await dialog.getByRole("button", { name: "返回检查", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page).toHaveURL(attemptUrl);
  await button(page, "我要背单词").click();
  await dialog.getByRole("button", { name: "前往背单词", exact: true }).click();
  await expect(page).toHaveURL(/#\/vocabulary$/);
  await button(page, "试卷大厅").click();
  await page
    .locator(".history-list")
    .getByRole("button", { name: /继续/ })
    .click();
  await expect(page).toHaveURL(attemptUrl);
  await expect(page.locator(".option").first()).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("浏览器前进回到背单词后，较慢的试卷响应不会盖掉当前页面", async ({
  page,
}) => {
  await page.goto("/");
  await button(page, "进入练习").first().click();
  await button(page, "开始练习 →").click();
  await expect(page.locator(".options")).toBeVisible();
  const attemptUrl = page.url();
  const id = new URL(attemptUrl).hash.split("/").at(-1);
  const attemptPath = `/api/attempts/${id}`;
  const attemptRoute = `**${attemptPath}`;

  await button(page, "我要背单词").click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "前往背单词" })
    .click();
  await expect(page).toHaveURL(/#\/vocabulary$/);
  let releaseResponse!: () => void;
  let receivedStatus!: (status: number) => void;
  const release = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  const received = new Promise<number>((resolve) => {
    receivedStatus = resolve;
  });
  await page.route(attemptRoute, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const liveResponse = await route.fetch();
    receivedStatus(liveResponse.status());
    await release;
    await route.fulfill({ response: liveResponse });
  });
  try {
    await page.goBack();
    await expect(page).toHaveURL(attemptUrl);
    expect(await received).toBe(200);
    await page.goForward();
    await expect(page).toHaveURL(/#\/vocabulary$/);
    await expect(page.getByLabel(searchLabel)).toBeVisible();

    const response = page.waitForResponse(
      (response) => new URL(response.url()).pathname === attemptPath,
    );
    releaseResponse();
    await (await response).finished();
    await page.evaluate(
      () =>
        new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        }),
    );
    await expect(page).toHaveURL(/#\/vocabulary$/);
    await expect(page.getByLabel(searchLabel)).toBeVisible();
    await expect(page.locator(".options")).not.toBeVisible();
  } finally {
    releaseResponse();
    await page.unroute(attemptRoute);
  }
});
