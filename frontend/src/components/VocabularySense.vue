<script setup lang="ts">
import { pdfPageLink, testLabel } from "../vocabulary";
import type { VocabularySense } from "../vocabulary";

defineProps<{ sense: VocabularySense }>();
</script>

<template>
  <div class="vocabulary-sense">
    <section>
      <h3>释义</h3>
      <p>
        <span v-if="sense.pos" lang="en">{{ sense.pos }} </span>{{
          sense.meaning
        }}
      </p>
    </section>
    <section v-if="sense.usage">
      <h3>用法</h3>
      <p>{{ sense.usage }}</p>
    </section>
    <section v-if="sense.example">
      <h3>例句</h3>
      <p class="muted">
        {{ sense.example.kind === "original" ? "原书例句" : "补充例句" }}
        <template v-if="sense.example.pdf_page !== null">
          ·
          <a
            :href="pdfPageLink(sense.example.pdf_page)"
            target="_blank"
            rel="noopener noreferrer"
            >PDF 第 {{ sense.example.pdf_page }} 页</a
          >
          <span v-if="sense.example.printed_page">
            · 书内第 {{ sense.example.printed_page }} 页</span
          >
        </template>
      </p>
      <blockquote class="vocabulary-example">
        <p lang="en">{{ sense.example.text }}</p>
        <p v-if="sense.example.translation" class="muted">
          {{ sense.example.translation }}
        </p>
      </blockquote>
    </section>
    <p v-if="!sense.usage || !sense.example" class="muted">
      {{
        !sense.usage && !sense.example
          ? "用法和例句待核对"
          : !sense.usage
            ? "用法待核对"
            : "例句待核对"
      }}
    </p>
    <ul
      v-if="sense.sources.length"
      class="vocabulary-sources muted"
      aria-label="词条出处"
    >
      <li
        v-for="source in sense.sources"
        :key="`${source.test_number}-${source.pdf_page}`"
      >
        <span lang="en">{{ testLabel(source.test_number) }}</span>
        ·
        <a
          :href="pdfPageLink(source.pdf_page)"
          target="_blank"
          rel="noopener noreferrer"
          >PDF 第 {{ source.pdf_page }} 页</a
        >
        <span v-if="source.printed_page">
          · 书内第 {{ source.printed_page }} 页</span
        >
      </li>
    </ul>
  </div>
</template>
