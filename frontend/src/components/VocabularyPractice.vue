<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { api, ApiError } from "../api";
import type {
  PracticeMode,
  VocabularyAnswer,
  VocabularyQuestion,
  VocabularyRound,
} from "../vocabulary";
import VocabularySense from "./VocabularySense.vue";

const props = defineProps<{ mode: PracticeMode }>();
const emit = defineEmits<{ lookup: [] }>();
const questions = ref<VocabularyQuestion[]>([]);
const index = ref(0);
const score = ref(0);
const response = ref("");
const answer = ref<VocabularyAnswer | null>(null);
const done = ref(false);
const loadingRound = ref(false);
const submitting = ref(false);
const roundError = ref("");
const answerError = ref("");
const expired = ref(false);
const questionHeading = ref<HTMLElement | null>(null);
const feedbackHeading = ref<HTMLElement | null>(null);
const resultHeading = ref<HTMLElement | null>(null);
const question = computed(() => questions.value[index.value]);
const isChoice = computed(() => props.mode === "choice");
const modeLabel = computed(() => (isChoice.value ? "选择练习" : "拼写练习"));
const canSubmit = computed(
  () =>
    Boolean(response.value.trim()) &&
    !submitting.value &&
    !expired.value &&
    !answer.value,
);

async function startRound(moveFocus = false) {
  if (loadingRound.value || submitting.value) return;
  loadingRound.value = true;
  roundError.value = "";
  answerError.value = "";
  expired.value = false;
  done.value = false;
  questions.value = [];
  index.value = 0;
  score.value = 0;
  response.value = "";
  answer.value = null;
  try {
    const result = await api<VocabularyRound>("/vocabulary/rounds", "POST", {
      mode: props.mode,
    });
    questions.value = result.questions;
  } catch (error) {
    roundError.value = error instanceof Error ? error.message : "题目加载失败";
  } finally {
    loadingRound.value = false;
  }
  if (moveFocus) await nextTick(() => questionHeading.value?.focus());
}

async function submitAnswer() {
  if (!question.value || !canSubmit.value) return;
  submitting.value = true;
  answerError.value = "";
  try {
    const result = await api<VocabularyAnswer>("/vocabulary/answers", "POST", {
      question_token: question.value.token,
      answer: response.value.trim(),
    });
    answer.value = result;
    if (result.correct) score.value++;
    await nextTick(() => feedbackHeading.value?.focus());
  } catch (error) {
    expired.value =
      error instanceof ApiError && [400, 410].includes(error.status);
    answerError.value =
      error instanceof Error ? error.message : "判分失败，请重试";
  } finally {
    submitting.value = false;
  }
}

function nextQuestion() {
  if (!answer.value) return;
  if (index.value + 1 === questions.value.length) {
    done.value = true;
    void nextTick(() => resultHeading.value?.focus());
    return;
  }
  index.value++;
  response.value = "";
  answer.value = null;
  void nextTick(() => questionHeading.value?.focus());
}

onMounted(() => void startRound());
</script>

<template>
  <section
    v-if="loadingRound"
    class="vocabulary-round-state vocabulary-panel"
    :aria-label="modeLabel"
  >
    <p class="muted" role="status">正在准备题目…</p>
  </section>
  <section
    v-else-if="roundError || !questions.length"
    class="vocabulary-round-state vocabulary-panel"
    :aria-label="modeLabel"
  >
    <h2>暂时无法开始{{ modeLabel }}</h2>
    <p v-if="roundError" role="alert">{{ roundError }}</p>
    <p v-else>当前题库暂无可用题目。</p>
    <div class="vocabulary-actions">
      <button type="button" @click="emit('lookup')">返回查词</button>
      <button type="button" class="primary" @click="startRound(true)">
        重新加载题目
      </button>
    </div>
  </section>
  <section
    v-else-if="done"
    class="vocabulary-round-state vocabulary-panel"
    aria-label="本轮结果"
  >
    <h2 ref="resultHeading" tabindex="-1">本轮练习完成</h2>
    <p>
      答对 <strong>{{ score }} / {{ questions.length }}</strong> 题
    </p>
    <div class="vocabulary-actions">
      <button type="button" @click="emit('lookup')">返回查词</button>
      <button type="button" class="primary" @click="startRound(true)">
        再练一轮
      </button>
    </div>
  </section>
  <section
    v-else-if="question"
    class="vocabulary-practice"
    :class="{ answered: answer }"
    :aria-label="modeLabel"
  >
    <div class="vocabulary-progress-line">
      <strong>第 {{ index + 1 }} / {{ questions.length }} 题</strong>
      <span class="muted">已答对 {{ score }} 题</span>
    </div>
    <progress
      :value="index + Number(Boolean(answer))"
      :max="questions.length"
      aria-label="本轮练习进度"
    ></progress>
    <div class="vocabulary-practice-body">
      <form
        class="vocabulary-question vocabulary-panel"
        @submit.prevent="submitAnswer"
      >
        <h2 ref="questionHeading" class="muted" tabindex="-1">
          {{ isChoice ? "根据释义和词性选择单词" : "根据中文释义输入单词" }}
        </h2>
        <div class="vocabulary-prompt">
          <strong class="vocabulary-cue">{{ question.prompt }}</strong>
          <span v-if="isChoice && question.pos" class="vocabulary-pos">{{
            question.pos
          }}</span>
        </div>
        <fieldset
          v-if="isChoice"
          class="vocabulary-options"
          :disabled="Boolean(answer) || submitting || expired"
        >
          <legend class="vocabulary-a11y">请选择一个单词</legend>
          <label
            v-for="(option, position) in question.options"
            :key="option.id"
            class="vocabulary-option"
            :class="{
              'option-right': answer?.correct_answer === option.label,
              'option-wrong':
                answer && !answer.correct && response === option.id,
            }"
          >
            <input
              v-model="response"
              type="radio"
              name="vocabulary-option"
              :value="option.id"
            />
            <span aria-hidden="true">{{ "ABCD"[position] }}.</span>
            <span lang="en">{{ option.label }}</span>
            <small v-if="answer?.correct_answer === option.label"
              >正确选项</small
            >
            <small v-else-if="answer && response === option.id">你的选择</small>
          </label>
        </fieldset>
        <label v-else class="vocabulary-spelling">
          <span class="muted">你的拼写</span>
          <input
            v-model="response"
            type="text"
            name="spelling"
            lang="en"
            autocomplete="off"
            autocapitalize="none"
            spellcheck="false"
            maxlength="160"
            placeholder="输入英文单词"
            :readonly="Boolean(answer) || submitting || expired"
          />
        </label>
        <p v-if="answerError" class="vocabulary-answer-error" role="alert">
          {{ answerError }}
        </p>
        <div v-if="!answer" class="vocabulary-actions">
          <button
            v-if="expired"
            type="button"
            class="primary"
            @click="startRound(true)"
          >
            重新开始
          </button>
          <button v-else type="submit" class="primary" :disabled="!canSubmit">
            {{
              submitting ? "正在判分…" : answerError ? "重试提交" : "提交答案"
            }}
          </button>
        </div>
      </form>
      <section
        v-if="answer"
        class="vocabulary-feedback vocabulary-panel"
        aria-label="答题反馈"
      >
        <h2
          ref="feedbackHeading"
          class="vocabulary-verdict"
          :class="{ 'is-wrong': !answer.correct }"
          tabindex="-1"
        >
          <span aria-hidden="true">{{ answer.correct ? "✓" : "×" }}</span>
          {{ answer.correct ? "回答正确" : "回答错误" }}
        </h2>
        <dl class="vocabulary-comparison">
          <div>
            <dt>你的答案</dt>
            <dd lang="en">{{ answer.given_answer }}</dd>
          </div>
          <div>
            <dt>正确答案</dt>
            <dd lang="en">{{ answer.correct_answer }}</dd>
          </div>
        </dl>
        <VocabularySense :sense="answer.sense" />
        <div class="vocabulary-actions">
          <button type="button" class="primary" @click="nextQuestion">
            {{ index + 1 === questions.length ? "查看本轮结果" : "下一题" }}
          </button>
        </div>
      </section>
    </div>
  </section>
</template>
