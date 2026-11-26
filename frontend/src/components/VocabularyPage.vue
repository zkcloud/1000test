<script setup lang="ts">
import { nextTick, ref } from "vue";
import type { PracticeMode } from "../vocabulary";
import VocabularyLookup from "./VocabularyLookup.vue";
import VocabularyPractice from "./VocabularyPractice.vue";
import "../vocabulary.css";

type View = "lookup" | PracticeMode;

const view = ref<View>("lookup");
const lookupButton = ref<HTMLButtonElement | null>(null);
const practiceModes = { choice: "选择练习", spelling: "拼写练习" } as const;

function returnToLookup() {
  view.value = "lookup";
  void nextTick(() => lookupButton.value?.focus());
}
</script>

<template>
  <div class="vocabulary-page">
    <div class="vocabulary-intro">
      <h1>我要背单词</h1>
      <p v-if="view === 'lookup'" class="muted">《阅读全真模拟1000题》词汇</p>
    </div>
    <nav class="vocabulary-tabs" aria-label="背单词功能">
      <button
        ref="lookupButton"
        type="button"
        :aria-pressed="view === 'lookup'"
        @click="view = 'lookup'"
      >
        查单词
      </button>
      <button
        v-for="(label, practiceMode) in practiceModes"
        :key="practiceMode"
        type="button"
        :aria-pressed="view === practiceMode"
        @click="view = practiceMode"
      >
        {{ label }}
      </button>
    </nav>
    <VocabularyLookup v-show="view === 'lookup'" />
    <VocabularyPractice
      v-if="view !== 'lookup'"
      :key="view"
      :mode="view"
      @lookup="returnToLookup"
    />
  </div>
</template>
