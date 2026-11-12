<script setup lang="ts">
import { ref } from "vue";
import type { Passage } from "../types";
defineProps<{ passage: Passage }>();
const view = ref<"image" | "text">("image"),
  zoom = ref(100),
  expanded = ref(true);
</script>

<template>
  <section class="material-panel panel" aria-label="共用阅读材料">
    <header class="material-header">
      <div>
        <span class="eyebrow">READING MATERIAL</span>
        <h2>Questions {{ passage.first_number }}–{{ passage.last_number }}</h2>
      </div>
      <div class="button-row">
        <button :aria-pressed="view === 'image'" @click="view = 'image'">
          原版</button
        ><button :aria-pressed="view === 'text'" @click="view = 'text'">
          文字</button
        ><button :aria-expanded="expanded" @click="expanded = !expanded">
          {{ expanded ? "收起" : "展开" }}材料
        </button>
      </div>
    </header>
    <div v-show="expanded" class="material-scroll">
      <template v-if="view === 'image'">
        <div class="zoom-controls">
          <label
            >阅读缩放
            <select v-model="zoom">
              <option :value="100">适合宽度</option>
              <option :value="125">125%</option>
              <option :value="150">150%</option>
              <option :value="200">200%</option>
            </select></label
          >
        </div>
        <div class="image-canvas" :data-zoom="zoom">
          <figure v-for="(asset, i) in passage.assets" :key="asset.id">
            <img
              :src="asset.url"
              :alt="`原版材料第 ${i + 1} 页，PDF 第 ${asset.page} 页`"
              @error="
                ($event.target as HTMLImageElement).dataset.failed = 'true'
              "
            />
            <figcaption>
              材料 {{ i + 1 }}/{{ passage.assets.length }} · PDF
              {{ asset.page }} 页
            </figcaption>
            <a :href="asset.url" target="_blank" rel="noopener">单独打开原图</a>
          </figure>
        </div>
      </template>
      <template v-else
        ><p class="notice">
          纯文本不包含图片内文字。邮件、表格等内容请以原版为准。
        </p>
        <p class="reading-text">
          {{ passage.content || "本组材料以图片呈现，请切换到原版。" }}
        </p></template
      >
    </div>
  </section>
</template>
