<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import MaterialPanel from "./components/MaterialPanel.vue";
import { usePlatform } from "./usePlatform";
const p = usePlatform();
const {
  exams,
  history,
  attempt,
  question,
  page,
  setupExam,
  mode,
  scope,
  busy,
  loading,
  error,
  saveState,
  dialog,
  filter,
  pending,
  conflict,
  index,
  selected,
  response,
  answered,
  remaining,
  active,
  canOperate,
} = p;
const { passages, passageId, practiceElapsed } = p;
const modal = ref<HTMLDialogElement | null>(null),
  answerCardOpen = ref(false),
  showAllHistory = ref(false);
const time = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;
const date = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString("zh-CN", { hour12: false });
const title = computed(
  () =>
    exams.value.find((e) => e.id === attempt.value?.exam_id)?.title ??
    "Reading Test",
);
const result = computed(() => attempt.value?.result);
const visibleEntries = computed(
  () =>
    result.value?.entries.filter(
      (e) =>
        filter.value === "all" ||
        (filter.value === "wrong" && e.selection && !e.correct) ||
        (filter.value === "blank" && !e.selection) ||
        (filter.value === "marked" &&
          attempt.value?.responses[String(e.id)]?.marked),
    ) ?? [],
);
const partStats = computed(() =>
  [5, 6, 7]
    .map((part) => {
      const entries =
        result.value?.entries.filter((e) => e.part === part) ?? [];
      return {
        part,
        total: entries.length,
        right: entries.filter((e) => e.correct).length,
      };
    })
    .filter((p) => p.total),
);
const lastAnswered = computed(
  () =>
    active.value &&
    attempt.value?.auto_next &&
    index.value === attempt.value.questions.length - 1 &&
    selected.value,
);
watch(dialog, async (value) => {
  await nextTick();
  if (value) modal.value?.showModal();
  else modal.value?.close();
});
function returnResults() {
  page.value = "result";
  window.history.replaceState({}, "", `#/attempt/${attempt.value!.id}/result`);
}
async function go(i: number) {
  await p.go(i);
  answerCardOpen.value = false;
}
function discard() {
  if (
    window.confirm("确定放弃尚未同步的本地选择？服务端已经保存的答案会保留。")
  )
    p.discardPending();
}
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <header class="site-header">
    <button class="brand" aria-label="阅读练习室首页" @click="p.leave">
      <span class="brand-symbol">阅</span
      ><span>阅读练习室<small>READ. PRACTICE. PROGRESS.</small></span>
    </button>
    <nav aria-label="主导航">
      <span class="device-note">记录保存在当前浏览器身份下</span
      ><button class="quiet" @click="p.leave">试卷大厅</button>
    </nav>
  </header>
  <main id="main" :class="{ 'workspace-main': page === 'work' }">
    <div v-if="error" class="notice error-notice" role="alert">
      <span>{{ error }}</span><button v-if="!attempt" @click="p.init">
        重新加载</button
      ><button v-else-if="!pending" @click="p.resume(attempt)">
        刷新当前记录
      </button>
    </div>
    <section v-if="pending" class="notice pending-notice" role="status">
      <strong>有一条作答尚未同步</strong>
      <p>
        本地选择不会计入服务端成绩，直到保存成功。{{
          conflict
            ? "另一窗口或截止时间改变了记录，请先核对。"
            : "请恢复网络后重试。"
        }}
      </p>
      <div class="button-row">
        <button v-if="!attempt" :disabled="busy" @click="p.openPending">
          打开关联记录
        </button>
        <button :disabled="busy || !active" @click="p.retry(conflict)">
          {{ conflict ? "用本地选择覆盖当前题" : "重试保存" }}</button><button
          :disabled="busy"
          @click="discard"
        >
          放弃未同步选择
        </button>
      </div>
    </section>
    <div v-if="loading" class="loading" role="status">
      正在准备你的阅读空间…
    </div>

    <template v-else-if="page === 'home'">
      <section class="hero">
        <div>
          <p class="eyebrow">A LITTLE BETTER, EVERY DAY</p>
          <h1>读懂每一句，<br />走稳每一步。</h1>
          <p class="hero-description">
            从一套试卷开始，找到自己的阅读节奏。<br />考试检验积累，练习理解每一个答案。
          </p>
        </div>
        <div class="hero-index">
          <span class="hero-number">10<span>套</span></span>
          <p>阅读全真模拟</p>
          <div class="hero-facts">
            <span>1,000 道题</span><span>3 类题型</span><span>原版材料</span>
          </div>
        </div>
      </section>
      <section class="section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">YOUR NEXT CHAPTER</p>
            <h2>选择一套，开始今天的进步</h2>
          </div>
          <span class="muted">每套 100 题 · 考试限时 75 分钟</span>
        </div>
        <div class="exam-grid">
          <article v-for="exam in exams" :key="exam.id" class="exam-card">
            <div class="exam-card-top">
              <span class="exam-number">{{
                String(exam.number).padStart(2, "0")
              }}</span><span class="badge">READING</span>
            </div>
            <h3>{{ exam.title }}</h3>
            <p class="muted">
              {{ exam.total }} 道单选题 · {{ exam.duration_minutes }} 分钟
            </p>
            <div class="part-labels">
              <span>Part 5 · 30</span><span>Part 6 · 16</span
              ><span>Part 7 · 54</span>
            </div>
            <div class="button-row">
              <button class="primary" @click="p.setup(exam, 'exam')">
                开始考试</button
              ><button @click="p.setup(exam, 'practice')">进入练习</button>
            </div>
          </article>
        </div>
      </section>
      <section class="section history-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">PICK UP WHERE YOU LEFT OFF</p>
            <h2>我的学习记录</h2>
          </div>
          <button
            v-if="history.length > 12"
            @click="showAllHistory = !showAllHistory"
          >
            {{ showAllHistory ? "收起" : `查看全部 ${history.length} 条` }}
          </button>
        </div>
        <div v-if="!history.length" class="empty-state">
          <h3>下一次进步，从第一次开始。</h3>
          <p>完成考试或练习后，你的进度和结果会出现在这里。</p>
        </div>
        <div v-else class="history-list">
          <article
            v-for="item in showAllHistory ? history : history.slice(0, 12)"
            :key="item.id"
            class="history-row"
          >
            <div>
              <h3>
                {{ exams.find((e) => e.id === item.exam_id)?.title }}
                <span class="badge"
                  >{{ item.mode === "exam" ? "考试" : "练习"
                  }}{{ item.scope ? ` · Part ${item.scope}` : "" }}</span
                >
              </h3>
              <p class="muted">{{ date(item.created_at) }}</p>
            </div>
            <div class="history-outcome">
              <strong v-if="item.status === 'finished'">{{
                item.mode === "exam"
                  ? `${item.result?.score}/100 分`
                  : `独立作答 ${item.result?.independent_correct}/${item.result?.independent_total}`
              }}</strong><span v-else
                >{{
                  Object.values(item.responses).filter((r) => r.selection)
                    .length
                }}/{{ item.questions.length }} 已答</span
              ><button :disabled="busy" @click="p.resume(item)">
                {{ item.status === "active" ? "继续作答" : "查看结果" }}
              </button>
            </div>
          </article>
        </div>
      </section>
    </template>

    <section v-else-if="page === 'setup'" class="setup-panel panel">
      <button class="text-button" @click="p.backHome">← 返回试卷大厅</button>
      <p class="eyebrow">
        {{ mode === "exam" ? "READY WHEN YOU ARE" : "LEARN AT YOUR OWN PACE" }}
      </p>
      <h1>
        {{
          mode === "exam" ? "留出专注的 75 分钟。" : "找到适合自己的练习节奏。"
        }}
      </h1>
      <h2>{{ setupExam?.title }} · Reading Test</h2>
      <template v-if="mode === 'exam'"
        ><div class="setup-facts">
          <span><strong>100</strong>道单选题</span
          ><span><strong>75</strong>分钟</span
          ><span><strong>100</strong>分满分</span>
        </div>
        <ul class="rules">
          <li>交卷后才能查看正确答案与解析。</li>
          <li>每题 1 分，错答或未答均为 0 分，不倒扣。</li>
          <li>开始后持续计时；刷新或离开页面不会暂停。</li>
          <li>交卷后作答锁定，可查看成绩并逐题回顾。</li>
        </ul>
        <p class="muted">这里的原始分数不等于官方 TOEIC 换算分。</p></template
      ><template v-else
        ><label class="field-label"
          >练习范围<select v-model="scope">
            <option value="all">整套试卷 · 100 题</option>
            <option value="5">Part 5 · 独立填空 · 30 题</option>
            <option value="6">Part 6 · 篇章填空 · 16 题</option>
            <option value="7">Part 7 · 阅读理解 · 54 题</option>
          </select></label
        ><label v-if="scope !== '5'" class="field-label"
          >题组（可选）<select v-model="passageId">
            <option value="all">全部题组</option>
            <option
              v-for="g in passages.filter(
                (g) => scope === 'all' || g.part === Number(scope),
              )"
              :key="g.id"
              :value="String(g.id)"
            >
              Part {{ g.part }} · Questions {{ g.first_number }}–{{
                g.last_number
              }}
            </option>
          </select></label
        >
        <ul class="rules">
          <li>无倒计时，按自己的节奏完成。</li>
          <li>随时查看当前题的答案与解析，不自动揭示其他题。</li>
          <li>独立首次作答与先看答案分开记录。</li>
          <li>Part 6/7 保留完整共用阅读材料。</li>
        </ul></template
      ><button class="primary start-button" :disabled="busy" @click="p.start">
        {{ busy ? "正在创建…" : mode === "exam" ? "确认开始考试" : "开始练习" }}
        →
      </button>
    </section>

    <template v-else-if="page === 'work' && attempt">
      <div class="exam-toolbar">
        <div class="button-row">
          <span class="badge">{{
            !active
              ? "只读回顾"
              : attempt.mode === "exam"
                ? "考试模式"
                : "练习模式"
          }}</span><strong>{{ title }}</strong
          ><span class="muted"
            >{{ answered }}/{{ attempt.questions.length }} 已答</span
          >
        </div>
        <div class="button-row">
          <span
            v-if="active && attempt.mode === 'exam'"
            class="timer"
            :class="{ urgent: remaining <= 60 }"
            aria-label="剩余时间"
            >{{ time(remaining) }}</span><template v-else-if="active"
            ><span class="muted">练习 {{ time(practiceElapsed) }}</span
            ><button :disabled="busy || !!pending" @click="p.pause">
              {{ attempt.paused ? "继续练习" : "暂停" }}
            </button></template
          ><button
            class="primary"
            :disabled="busy"
            @click="active ? (dialog = 'submit') : returnResults()"
          >
            {{
              !active
                ? "返回成绩/小结"
                : attempt.mode === "exam"
                  ? "交卷"
                  : "结束练习"
            }}
          </button>
        </div>
      </div>
      <p
        v-if="active && attempt.mode === 'exam' && remaining <= 600"
        class="notice"
        role="status"
      >
        {{
          remaining <= 60
            ? "不足 1 分钟，请检查作答。"
            : "剩余不足 10 分钟，请留意时间。"
        }}到时将由服务端自动交卷。
      </p>
      <p v-if="active && attempt.paused" class="notice" role="status">
        练习已暂停，用时已停止累计。点击“继续练习”后可作答。
      </p>
      <div class="workspace">
        <aside class="answer-card panel" :class="{ expanded: answerCardOpen }">
          <div class="answer-card-title">
            <h2>答题卡</h2>
            <button
              class="mobile-only"
              :aria-expanded="answerCardOpen"
              @click="answerCardOpen = !answerCardOpen"
            >
              {{ answerCardOpen ? "收起" : "展开" }}
            </button>
          </div>
          <div class="answer-card-body">
            <section v-for="part in [5, 6, 7]" :key="part">
              <template v-if="attempt.questions.some((q) => q.part === part)"
                ><h3>Part {{ part }}</h3>
                <div class="number-grid">
                  <button
                    v-for="q in attempt.questions.filter(
                      (q) => q.part === part,
                    )"
                    :key="q.id"
                    :class="{
                      answered: attempt.responses[String(q.id)]?.selection,
                      current: question?.id === q.id,
                      marked: attempt.responses[String(q.id)]?.marked,
                    }"
                    :aria-current="question?.id === q.id ? 'true' : undefined"
                    :aria-label="`${q.number}题，${attempt.responses[String(q.id)]?.selection ? '已答' : '未答'}${attempt.responses[String(q.id)]?.marked ? '，已标记' : ''}`"
                    :disabled="!canOperate"
                    @click="
                      go(attempt.questions.findIndex((x) => x.id === q.id))
                    "
                  >
                    {{ q.number }}
                  </button>
                </div></template
              >
            </section>
            <p class="muted legend">
              底色：已答<br />圆点：标记<br />边框：当前题
            </p>
          </div>
        </aside>
        <div class="question-workspace">
          <div class="work-heading">
            <h2>
              Part {{ question?.part }}
              <span class="muted">{{
                question?.part === 5
                  ? "独立填空"
                  : question?.part === 6
                    ? "篇章填空"
                    : "阅读理解"
              }}</span>
            </h2>
            <span class="save-status" role="status">{{ saveState }}</span>
          </div>
          <div
            v-if="question"
            class="reading-layout"
            :class="{ solo: !question.passage }"
          >
            <MaterialPanel
              v-if="question.passage"
              :key="question.passage.id"
              :passage="question.passage"
            />
            <section class="question-panel panel" :aria-busy="busy">
              <div class="question-top">
                <span class="muted"
                  >第 {{ index + 1 }}/{{ attempt.questions.length }} 题 · 原题号
                  {{ question.number }}</span
                ><button
                  v-if="active"
                  :disabled="!canOperate"
                  :aria-pressed="!!response?.marked"
                  @click="p.mark"
                >
                  {{ response?.marked ? "已标记 · 取消" : "标记稍后检查" }}
                </button>
              </div>
              <h3 class="question-stem">{{ question.stem }}</h3>
              <label v-if="active" class="auto-next"
                ><input
                  type="checkbox"
                  :checked="attempt.auto_next"
                  :disabled="!canOperate"
                  @change="
                    p.toggleAuto(($event.target as HTMLInputElement).checked)
                  "
                />选答后自动下一题</label
              >
              <div
                class="options"
                role="group"
                :aria-label="`第${question.number}题选项`"
              >
                <button
                  v-for="option in question.options"
                  :key="option.label"
                  class="option"
                  :class="{
                    selected: selected === option.label,
                    correct: question.answer === option.label,
                    incorrect:
                      question.answer &&
                      selected === option.label &&
                      question.answer !== option.label,
                  }"
                  :aria-pressed="selected === option.label"
                  :disabled="!active || !canOperate"
                  @click="p.choose(option.label)"
                >
                  <span class="option-letter">{{ option.label }}</span><span>{{
                    option.content
                  }}</span
                  ><span
                    v-if="question.answer === option.label"
                    class="option-state"
                    >✓ 正确答案</span
                  >
                </button>
              </div>
              <div v-if="active" class="question-actions">
                <button
                  v-if="attempt.mode === 'practice' && !question.answer"
                  class="primary"
                  :disabled="!canOperate"
                  @click="p.reveal"
                >
                  {{
                    selected ? "核对本题 · 答案与解析" : "查看答案与解析"
                  }}</button><button
                  v-if="selected"
                  class="text-button"
                  :disabled="!canOperate"
                  @click="p.choose(null)"
                >
                  清除选择
                </button>
              </div>
              <section
                v-if="question.answer"
                class="answer-panel"
                aria-live="polite"
              >
                <div class="section-heading">
                  <h3>正确答案 {{ question.answer }}</h3>
                  <span>{{
                    !selected
                      ? "尚未作答"
                      : selected === question.answer
                        ? "你的选择正确"
                        : `你的选择 ${selected}`
                  }}</span>
                </div>
                <p v-if="active" class="muted">
                  已查看答案，后续修改不覆盖首次作答记录。
                </p>
                <h3>解析</h3>
                <p class="explanation">
                  {{ question.explanation || "暂无解析" }}
                </p>
              </section>
              <p v-if="lastAnswered" class="notice" role="status">
                已记录最后一题，请{{
                  attempt.mode === "exam" ? "交卷" : "结束练习"
                }}。不会自动提交整卷。
              </p>
              <footer class="question-footer">
                <button
                  :disabled="!canOperate || index === 0"
                  @click="go(index - 1)"
                >
                  ← 上一题</button
                ><span class="muted"
                  >PDF {{ question.page_start
                  }}{{
                    question.page_end !== question.page_start
                      ? `–${question.page_end}`
                      : ""
                  }}
                  页</span
                ><button
                  :disabled="
                    !canOperate || index === attempt.questions.length - 1
                  "
                  @click="go(index + 1)"
                >
                  下一题 →
                </button>
              </footer>
            </section>
          </div>
        </div>
      </div>
    </template>

    <section
      v-else-if="page === 'result' && attempt && result"
      class="results section"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">A STEP FORWARD</p>
          <h1>
            {{
              attempt.mode === "exam"
                ? "这一次，看见自己的积累。"
                : "把答案，变成真正的理解。"
            }}
          </h1>
          <p class="muted">
            {{ title }} ·
            {{ attempt.mode === "exam" ? "考试已交卷" : "练习小结" }} ·
            {{ date(attempt.finished_at!) }}
          </p>
        </div>
        <button class="primary" :disabled="busy" @click="p.review()">
          逐题回顾 →
        </button>
      </div>
      <div class="result-grid">
        <article class="score-card">
          <p>{{ attempt.mode === "exam" ? "原始得分" : "独立首次作答正确" }}</p>
          <strong
            >{{
              attempt.mode === "exam"
                ? result.score
                : result.independent_correct
            }}<span
              >/{{
                attempt.mode === "exam"
                  ? result.total
                  : result.independent_total
              }}</span
            ></strong
          >
          <p>
            {{
              attempt.mode === "exam"
                ? "每题 1 分，无倒扣"
                : "查看答案前的首次作答"
            }}
          </p>
        </article>
        <article class="metric">
          <span>{{
            attempt.mode === "exam" ? "正确率" : "先看答案"
          }}</span><strong>{{
            attempt.mode === "exam"
              ? `${Math.round((result.correct / result.total) * 100)}%`
              : `${result.peek_first} 题`
          }}</strong>
        </article>
        <article class="metric">
          <span>未答</span><strong>{{ result.blank }}<small>题</small></strong>
        </article>
        <article class="metric">
          <span>用时</span><strong>{{ time(result.duration_seconds) }}</strong>
        </article>
      </div>
      <p class="muted">
        {{
          attempt.mode === "exam"
            ? "这是本套题目的原始分数，不是官方 TOEIC 换算分。"
            : "练习中看答案后改对，不会增加独立首次作答正确数。"
        }}
      </p>
      <div class="part-results">
        <article v-for="s in partStats" :key="s.part" class="panel">
          <h3>Part {{ s.part }}</h3>
          <strong>{{ s.right }}/{{ s.total }}</strong
          ><span class="muted">{{
            attempt.mode === "exam" ? "答对题数" : "当前作答正确（含已看答案）"
          }}</span
          ><progress
            :value="s.right"
            :max="s.total"
            :aria-label="`Part ${s.part} 当前正确题数`"
          ></progress>
        </article>
      </div>
      <div class="section-heading">
        <h2>题目回顾</h2>
        <div class="filter-row">
          <button
            v-for="f in [
              { id: 'all', name: '全部' },
              { id: 'wrong', name: '错题' },
              { id: 'blank', name: '未答' },
              { id: 'marked', name: '已标记' },
            ]"
            :key="f.id"
            :aria-pressed="filter === f.id"
            @click="filter = f.id"
          >
            {{ f.name }}
          </button>
        </div>
      </div>
      <div class="result-list">
        <div class="result-list-head">
          <span>题号</span><span>我的选择</span><span>正确答案</span
          ><span>结果</span><span></span>
        </div>
        <article v-for="e in visibleEntries" :key="e.id" class="result-row">
          <span>{{ e.number }}</span><span>{{ e.selection || "未答" }}</span
          ><strong>{{ e.answer }}</strong
          ><span :class="e.correct ? 'positive' : 'negative'">{{
            !e.selection ? "未答" : e.correct ? "正确" : "错误"
          }}</span
          ><button :disabled="busy" @click="p.review(e.id)">解析</button>
        </article>
        <p v-if="!visibleEntries.length" class="empty-state">
          没有符合条件的题目。
        </p>
      </div>
      <div class="button-row">
        <button @click="p.backHome">返回试卷大厅</button
        ><button
          :disabled="busy || !result.wrong || !!pending"
          @click="p.retryPractice('wrong')"
        >
          重练错题</button
        ><button
          :disabled="
            busy ||
            !Object.values(attempt.responses).some((r) => r.marked) ||
            !!pending
          "
          @click="p.retryPractice('marked')"
        >
          练习标记题</button
        ><button
          :disabled="busy"
          @click="
            p.setup(
              exams.find((e) => e.id === attempt!.exam_id)!,
              attempt!.mode,
            )
          "
        >
          新建一次{{ attempt.mode === "exam" ? "考试" : "练习" }}
        </button>
      </div>
    </section>
    <footer v-if="page !== 'work'" class="site-footer">
      <span>阅读练习室 · 每一次理解都算数</span
      ><span>仅保留当前浏览器访客记录；清除 Cookie 后将无法找回。</span>
    </footer>
  </main>
  <dialog
    ref="modal"
    class="confirm-dialog"
    @cancel.prevent="dialog = null"
    @close="dialog = null"
  >
    <div v-if="attempt" class="dialog-content">
      <p class="eyebrow">
        {{ dialog === "leave" ? "YOUR PROGRESS IS SAVED" : "READY TO FINISH?" }}
      </p>
      <h2>
        {{
          dialog === "leave"
            ? "返回试卷大厅？"
            : attempt.mode === "exam"
              ? "确认交卷？"
              : "结束本次练习？"
        }}
      </h2>
      <p>
        已答 {{ answered }} 题，未答
        {{ attempt.questions.length - answered }} 题，已标记
        {{ Object.values(attempt.responses).filter((r) => r.marked).length }}
        题。
      </p>
      <p class="muted">
        {{
          dialog === "leave"
            ? attempt.mode === "exam"
              ? "考试计时将继续，到时自动交卷。稍后可从历史记录继续。"
              : "已保存的练习进度可从历史记录继续。"
            : "提交后不能再修改作答，可查看结果、答案及解析。"
        }}
      </p>
      <p v-if="pending" class="notice">请先处理尚未同步的本地作答。</p>
      <div class="button-row">
        <button autofocus :disabled="busy" @click="dialog = null">
          返回检查</button
        ><button
          class="primary"
          :disabled="busy || !!pending"
          @click="dialog === 'leave' ? p.backHome() : p.finish()"
        >
          {{
            busy ? "正在处理…" : dialog === "leave" ? "返回大厅" : "确认提交"
          }}
        </button>
      </div>
    </div>
  </dialog>
</template>
