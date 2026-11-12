import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { api, ApiError, identify } from "./api";
import type {
  Attempt,
  Choice,
  Exam,
  Mode,
  PendingAnswer,
  Question,
} from "./types";

export function usePlatform() {
  const exams = ref<Exam[]>([]),
    history = ref<Attempt[]>([]),
    attempt = ref<Attempt | null>(null),
    question = ref<Question | null>(null);
  const page = ref<"home" | "setup" | "work" | "result">("home"),
    setupExam = ref<Exam | null>(null),
    mode = ref<Mode>("exam"),
    scope = ref("all");
  const busy = ref(false),
    loading = ref(true),
    error = ref(""),
    saveState = ref(""),
    dialog = ref<"submit" | "leave" | null>(null),
    filter = ref("all");
  const pending = ref<PendingAnswer | null>(null),
    conflict = ref(false),
    now = ref(Date.now() / 1000),
    offset = ref(0);
  const passages = ref<
      { id: number; part: number; first_number: number; last_number: number }[]
    >([]),
    passageId = ref("all");
  const practiceElapsed = computed(() =>
    attempt.value
      ? attempt.value.duration_seconds +
        (active.value && !attempt.value.paused
          ? Math.max(0, now.value + offset.value - attempt.value.server_time)
          : 0)
      : 0,
  );
  watch(scope, () => {
    passageId.value = "all";
  });
  const index = computed(() => attempt.value?.current_index ?? 0);
  const selected = computed(
    () =>
      attempt.value?.responses[String(question.value?.id)]?.selection ?? null,
  );
  const response = computed(
    () => attempt.value?.responses[String(question.value?.id)],
  );
  const answered = computed(
    () =>
      Object.values(attempt.value?.responses ?? {}).filter((r) => r.selection)
        .length,
  );
  const remaining = computed(() =>
    attempt.value?.deadline
      ? Math.max(
          0,
          Math.ceil(attempt.value.deadline - now.value - offset.value),
        )
      : 0,
  );
  const active = computed(() => attempt.value?.status === "active");
  const canOperate = computed(
    () =>
      !busy.value &&
      !pending.value &&
      !attempt.value?.paused &&
      (!question.value ||
        question.value.id === attempt.value?.questions[index.value]?.id),
  );
  let interval: ReturnType<typeof setInterval> | undefined,
    expiring = false;
  let lastAutoAdvance = -Infinity;

  function apply(a: Attempt) {
    attempt.value = a;
    offset.value = a.server_time - Date.now() / 1000;
  }
  function location(hash: string) {
    window.history.pushState({}, "", hash);
  }
  function storePending(p: PendingAnswer | null) {
    if (p) localStorage.setItem("reader-pending", JSON.stringify(p));
    else localStorage.removeItem("reader-pending");
    pending.value = p;
  }
  async function run(fn: () => Promise<void>) {
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    try {
      await fn();
    } catch (e) {
      error.value = e instanceof Error ? e.message : "操作失败，请重试";
    } finally {
      busy.value = false;
    }
  }
  async function loadQuestion() {
    const a = attempt.value;
    if (!a) return;
    const q = a.questions[a.current_index];
    if (!q) return;
    question.value = await api<Question>(`/attempts/${a.id}/questions/${q.id}`);
  }
  async function loadAttempt(id: string, result = false) {
    const saved = readPending();
    if (saved && saved.aid !== id) {
      pending.value = saved;
      throw new Error(
        "另一次作答仍有未同步选择，请先打开关联记录处理，避免覆盖本地数据。",
      );
    }
    apply(await api<Attempt>(`/attempts/${encodeURIComponent(id)}`));
    const raw = localStorage.getItem("reader-pending");
    if (raw) {
      try {
        const p = JSON.parse(raw) as PendingAnswer;
        pending.value = p.aid === id ? p : null;
      } catch {
        localStorage.removeItem("reader-pending");
      }
    } else pending.value = null;
    page.value =
      attempt.value!.status === "finished" && result ? "result" : "work";
    if (
      attempt.value!.status === "finished" &&
      !result &&
      !window.location.hash.includes("review")
    )
      page.value = "result";
    await loadQuestion();
  }
  async function home() {
    history.value = await api<Attempt[]>("/attempts");
    page.value = "home";
    attempt.value = null;
    question.value = null;
    pending.value = readPending();
    dialog.value = null;
    location("#/");
  }
  async function init() {
    loading.value = true;
    error.value = "";
    pending.value = readPending();
    try {
      await identify();
      exams.value = await api<Exam[]>("/exams");
      history.value = await api<Attempt[]>("/attempts");
      const match = window.location.hash.match(
        /^#\/attempt\/([\w-]+)(?:\/(review|result))?$/,
      );
      if (match) await loadAttempt(match[1]!, match[2] !== "review");
    } catch (e) {
      error.value = e instanceof Error ? e.message : "加载失败";
    } finally {
      loading.value = false;
    }
  }
  function readPending(): PendingAnswer | null {
    try {
      const raw = localStorage.getItem("reader-pending");
      if (!raw) return null;
      const p = JSON.parse(raw) as PendingAnswer;
      if (
        typeof p.aid !== "string" ||
        !Number.isInteger(p.qid) ||
        !Number.isInteger(p.revision) ||
        ![null, "A", "B", "C", "D"].includes(p.selection)
      )
        return null;
      return p;
    } catch {
      return null;
    }
  }
  async function openPending() {
    const saved = pending.value;
    if (saved)
      await run(async () => {
        await loadAttempt(saved.aid);
        location(`#/attempt/${saved.aid}`);
      });
  }
  async function setup(e: Exam, m: Mode) {
    setupExam.value = e;
    mode.value = m;
    scope.value = "all";
    passageId.value = "all";
    page.value = "setup";
    error.value = "";
    passages.value = [];
    try {
      passages.value = await api(`/exams/${e.id}/passages`);
    } catch (e) {
      error.value = e instanceof Error ? e.message : "材料列表加载失败";
    }
  }
  async function start() {
    await run(async () => {
      if (!setupExam.value) return;
      if (readPending())
        throw new Error("仍有未同步作答，请先从历史记录继续并处理后再开始。");
      apply(
        await api<Attempt>("/attempts", "POST", {
          exam_id: setupExam.value.id,
          mode: mode.value,
          scope: scope.value === "all" ? null : Number(scope.value),
          passage_id:
            passageId.value === "all" ? null : Number(passageId.value),
        }),
      );
      page.value = "work";
      pending.value = null;
      filter.value = "all";
      saveState.value = "已保存";
      location(`#/attempt/${attempt.value!.id}`);
      await loadQuestion();
    });
  }
  async function settings(values: {
    current_index?: number;
    auto_next?: boolean;
  }) {
    const a = attempt.value!;
    apply(
      await api<Attempt>(`/attempts/${a.id}`, "PATCH", {
        ...values,
        revision: a.revision,
      }),
    );
  }
  async function go(i: number) {
    if (
      !canOperate.value ||
      !attempt.value ||
      i < 0 ||
      i >= attempt.value.questions.length
    )
      return;
    await run(async () => {
      if (active.value) await settings({ current_index: i });
      else attempt.value = { ...attempt.value!, current_index: i };
      await loadQuestion();
    });
  }
  async function flush(applyLatest = false) {
    const p = pending.value,
      a = attempt.value;
    if (!p || !a) return;
    if (!active.value)
      throw new Error(
        "已到截止时间或已交卷，未同步的本地选择未计入成绩。请保留核对后清除。",
      );
    saveState.value = "保存中…";
    try {
      apply(
        await api<Attempt>(
          `/attempts/${a.id}/questions/${p.qid}/answer`,
          "PUT",
          {
            selection: p.selection,
            revision: applyLatest ? a.revision : p.revision,
          },
        ),
      );
      storePending(null);
      conflict.value = false;
      saveState.value = "已保存到服务端";
    } catch (e) {
      saveState.value = "保存失败 · 本地待同步";
      if (e instanceof ApiError && e.status === 409) {
        apply(await api<Attempt>(`/attempts/${a.id}`));
        conflict.value = true;
      }
      throw e;
    }
  }
  async function choose(choice: Choice | null) {
    if (!canOperate.value || !active.value || !question.value) return;
    if (performance.now() - lastAutoAdvance < 350) return;
    await run(async () => {
      const a = attempt.value!,
        qid = question.value!.id;
      storePending({ aid: a.id, qid, selection: choice, revision: a.revision });
      await flush();
      if (
        choice &&
        attempt.value!.auto_next &&
        index.value < attempt.value!.questions.length - 1
      ) {
        await settings({ current_index: index.value + 1 });
        await loadQuestion();
        lastAutoAdvance = performance.now();
      }
    });
  }
  async function retry(latest = false) {
    await run(async () => {
      await flush(latest);
      await loadQuestion();
    });
  }
  function discardPending() {
    storePending(null);
    conflict.value = false;
    saveState.value = "使用服务端已保存作答";
    error.value = "";
  }
  async function toggleAuto(value: boolean) {
    if (canOperate.value) await run(() => settings({ auto_next: value }));
  }
  async function mark() {
    await run(async () => {
      const a = attempt.value!;
      apply(
        await api<Attempt>(
          `/attempts/${a.id}/questions/${question.value!.id}/mark`,
          "PUT",
          { marked: !response.value?.marked, revision: a.revision },
        ),
      );
    });
  }
  async function reveal() {
    await run(async () => {
      apply(
        await api<Attempt>(
          `/attempts/${attempt.value!.id}/questions/${question.value!.id}/reveal`,
          "POST",
        ),
      );
      await loadQuestion();
    });
  }
  async function finish() {
    await run(async () => {
      if (pending.value) await flush();
      apply(
        await api<Attempt>(`/attempts/${attempt.value!.id}/submit`, "POST"),
      );
      page.value = "result";
      dialog.value = null;
      filter.value = "all";
      location(`#/attempt/${attempt.value!.id}/result`);
    });
  }
  async function resume(a: Attempt) {
    await run(async () => {
      location(`#/attempt/${a.id}${a.status === "finished" ? "/result" : ""}`);
      await loadAttempt(a.id, true);
      if (attempt.value?.paused && active.value)
        apply(await api<Attempt>(`/attempts/${a.id}/resume`, "POST"));
    });
  }
  async function review(qid?: number) {
    const a = attempt.value!;
    page.value = "work";
    if (qid) a.current_index = a.questions.findIndex((q) => q.id === qid);
    location(`#/attempt/${a.id}/review`);
    await run(loadQuestion);
  }
  async function backHome() {
    await run(async () => {
      if (active.value && attempt.value?.mode === "practice")
        await api(`/attempts/${attempt.value.id}/pause`, "POST");
      await home();
    });
  }
  async function pause() {
    if (pending.value) return;
    await run(async () => {
      apply(
        await api<Attempt>(
          `/attempts/${attempt.value!.id}/${attempt.value!.paused ? "resume" : "pause"}`,
          "POST",
        ),
      );
    });
  }
  async function retryPractice(kind: "wrong" | "marked") {
    await run(async () => {
      const a = attempt.value!;
      apply(
        await api<Attempt>("/attempts", "POST", {
          exam_id: a.exam_id,
          mode: "practice",
          source_attempt: a.id,
          retry_filter: kind,
        }),
      );
      page.value = "work";
      location(`#/attempt/${attempt.value!.id}`);
      await loadQuestion();
    });
  }
  function leave() {
    if (active.value) dialog.value = "leave";
    else void backHome();
  }
  function beforeUnload(e: BeforeUnloadEvent) {
    if (pending.value) {
      e.preventDefault();
      e.returnValue = "";
    }
  }
  function popstate() {
    page.value = "home";
    void init();
  }
  function online() {
    if (pending.value && !conflict.value) void retry();
  }
  onMounted(() => {
    void init();
    window.addEventListener("popstate", popstate);
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("online", online);
    interval = setInterval(() => {
      now.value = Date.now() / 1000;
      if (
        active.value &&
        attempt.value?.mode === "exam" &&
        remaining.value === 0 &&
        !busy.value &&
        !expiring
      ) {
        expiring = true;
        void run(async () => {
          apply(await api<Attempt>(`/attempts/${attempt.value!.id}`));
          if (!active.value) {
            page.value = "result";
            dialog.value = null;
          }
        }).finally(() => {
          expiring = false;
        });
      }
    }, 1000);
  });
  onUnmounted(() => {
    clearInterval(interval);
    window.removeEventListener("popstate", popstate);
    window.removeEventListener("beforeunload", beforeUnload);
    window.removeEventListener("online", online);
  });
  return {
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
    openPending,
    conflict,
    index,
    selected,
    response,
    answered,
    remaining,
    active,
    canOperate,
    passages,
    passageId,
    practiceElapsed,
    pause,
    retryPractice,
    setup,
    start,
    go,
    choose,
    retry,
    discardPending,
    toggleAuto,
    mark,
    reveal,
    finish,
    resume,
    review,
    backHome,
    leave,
    init,
  };
}
