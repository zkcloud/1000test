<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { api } from "../api";
import { testLabel } from "../vocabulary";
import type { VocabularyDetail, VocabularyList } from "../vocabulary";
import VocabularySense from "./VocabularySense.vue";

const search = ref("");
const test = ref("");
const words = ref<VocabularyList | null>(null);
const listLoading = ref(true);
const listError = ref("");
const selected = ref<number | null>(null);
const detail = ref<VocabularyDetail | null>(null);
const detailLoading = ref(false);
const detailError = ref("");
const detailOpen = ref(false);
const detailHeading = ref<HTMLElement | null>(null);
const listPanel = ref<HTMLElement | null>(null);
const partsOfSpeech = computed(() => [
  ...new Set(
    detail.value?.meanings.map((item) => item.pos).filter(Boolean) ?? [],
  ),
]);
let listRequest = 0;
let detailRequest = 0;
let requestedPage = 1;

async function selectWord(id: number, open = false) {
  if (open) {
    detailOpen.value = true;
    void nextTick(() => {
      if (window.matchMedia("(max-width: 800px)").matches)
        detailHeading.value?.focus();
    });
  }
  if (selected.value === id && (detail.value || detailLoading.value)) return;
  selected.value = id;
  const request = ++detailRequest;
  detail.value = null;
  detailError.value = "";
  detailLoading.value = true;
  try {
    const result = await api<VocabularyDetail>(`/vocabulary/words/${id}`);
    if (request === detailRequest) detail.value = result;
  } catch (error) {
    if (request === detailRequest)
      detailError.value =
        error instanceof Error ? error.message : "词条加载失败";
  } finally {
    if (request === detailRequest) detailLoading.value = false;
  }
}

async function loadWords(page = 1) {
  requestedPage = page;
  const request = ++listRequest;
  listLoading.value = true;
  listError.value = "";
  const params = new URLSearchParams({ page: String(page) });
  if (search.value.trim()) params.set("q", search.value.trim());
  if (test.value) params.set("test", test.value);
  try {
    const result = await api<VocabularyList>(`/vocabulary/words?${params}`);
    if (request !== listRequest) return;
    words.value = result;
    if (result.items.some((word) => word.id === selected.value)) return;
    const first = result.items[0];
    if (first) {
      void selectWord(first.id);
    } else {
      detailRequest++;
      selected.value = null;
      detail.value = null;
      detailError.value = "";
      detailLoading.value = false;
    }
  } catch (error) {
    if (request === listRequest)
      listError.value = error instanceof Error ? error.message : "词表加载失败";
  } finally {
    if (request === listRequest) listLoading.value = false;
  }
}

function backToList() {
  detailOpen.value = false;
  void nextTick(() => {
    listPanel.value
      ?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')
      ?.focus();
  });
}

async function changePage(page: number) {
  await loadWords(page);
  if (listError.value || listLoading.value) return;
  await nextTick(() => {
    listPanel.value
      ?.querySelector<HTMLButtonElement>(".vocabulary-word")
      ?.focus();
  });
}

watch(
  [search, test],
  ([, newTest], previous, onCleanup) => {
    listRequest++;
    detailOpen.value = false;
    listLoading.value = true;
    const immediate = !previous?.length || newTest !== previous[1];
    if (immediate) {
      void loadWords();
    } else {
      const delay = window.setTimeout(() => void loadWords(), 200);
      onCleanup(() => window.clearTimeout(delay));
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  listRequest++;
  detailRequest++;
});
</script>

<template>
  <div class="vocabulary-lookup" :class="{ 'detail-open': detailOpen }">
    <section
      ref="listPanel"
      class="vocabulary-list vocabulary-panel"
      aria-label="词表"
      :aria-busy="listLoading"
    >
      <div class="vocabulary-list-head">
        <div class="vocabulary-search">
          <input
            v-model="search"
            type="search"
            aria-label="搜索英文或中文释义"
            placeholder="搜索英文或中文释义"
            maxlength="160"
          />
          <select v-model="test" aria-label="选择套次">
            <option value="">全部套次</option>
            <option v-for="number in 10" :key="number" :value="String(number)">
              {{ testLabel(number) }}
            </option>
          </select>
        </div>
        <p class="muted">
          常用优先<span v-if="words && !listLoading && !listError">
            · {{ words.total }} 个词条</span
          >
        </p>
      </div>
      <p v-if="listLoading" class="vocabulary-list-message muted" role="status">
        正在加载词表…
      </p>
      <div v-else-if="listError" class="vocabulary-list-message">
        <p role="alert">{{ listError }}</p>
        <button type="button" @click="loadWords(requestedPage)">
          重新加载词表
        </button>
      </div>
      <template v-else-if="words?.items.length">
        <ul class="vocabulary-word-list">
          <li v-for="word in words.items" :key="word.id">
            <button
              type="button"
              class="vocabulary-word"
              :aria-pressed="selected === word.id"
              @click="selectWord(word.id, true)"
            >
              <span class="vocabulary-word-title" lang="en">{{
                word.word
              }}</span>
              <span class="vocabulary-word-meaning muted">
                {{
                  word.meanings
                    .map((item) =>
                      [item.pos, item.meaning].filter(Boolean).join(" "),
                    )
                    .join(" · ")
                }}
              </span>
              <span class="vocabulary-arrow" aria-hidden="true">›</span>
            </button>
          </li>
        </ul>
        <nav
          v-if="words.pages > 1"
          class="vocabulary-pagination"
          aria-label="词表分页"
        >
          <button
            type="button"
            :disabled="words.page === 1"
            @click="changePage(words.page - 1)"
          >
            上一页
          </button>
          <span class="muted">第 {{ words.page }} / {{ words.pages }} 页</span>
          <button
            type="button"
            :disabled="words.page === words.pages"
            @click="changePage(words.page + 1)"
          >
            下一页
          </button>
        </nav>
      </template>
      <p v-else class="vocabulary-list-message muted" role="status">
        没有找到词条，请换个关键词或套次。
      </p>
    </section>
    <section
      class="vocabulary-detail vocabulary-panel"
      aria-label="词条详情"
      :aria-busy="detailLoading"
    >
      <button
        ref="detailHeading"
        type="button"
        class="text-button vocabulary-back"
        @click="backToList"
      >
        ← 返回词表
      </button>
      <p v-if="detailLoading" class="muted" role="status">正在加载词条…</p>
      <div v-else-if="detailError" class="vocabulary-detail-error">
        <p role="alert">{{ detailError }}</p>
        <button
          v-if="selected !== null"
          type="button"
          @click="selectWord(selected)"
        >
          重新加载词条
        </button>
      </div>
      <template v-else-if="detail">
        <h2 class="vocabulary-term">
          <span lang="en">{{ detail.word }}</span>
          <span
            v-for="pos in partsOfSpeech"
            :key="pos"
            class="vocabulary-pos"
            >{{ pos }}</span
          >
        </h2>
        <VocabularySense
          v-for="sense in detail.senses"
          :key="sense.id"
          :sense="sense"
        />
      </template>
      <p v-else class="muted">选择词条，查看释义、用法和例句。</p>
    </section>
  </div>
</template>
