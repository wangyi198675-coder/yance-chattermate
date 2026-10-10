<script setup lang="ts">
import { computed } from 'vue'
import type { YanceTranslationProjection } from '../semanticTypes'

const props = defineProps<{
  canonicalMessageId: string | number
  translation: YanceTranslationProjection
  sourceText?: string | null
  silentFailClosed?: boolean
}>()

const identityMatches = computed(
  () => String(props.translation.messageId) === String(props.canonicalMessageId),
)
const translatedText = computed(() => props.translation.text?.trim() || '')
const sourceText = computed(() => props.sourceText?.trim() || '')
const sourceAlreadyChinese = computed(() => {
  const language = props.translation.sourceLanguage?.trim().toLowerCase() || ''
  if (language === 'zh' || language.startsWith('zh-')) return true
  if (/[\u3400-\u9fff\uf900-\ufaff]/.test(sourceText.value)) return true
  return !!sourceText.value && sourceText.value === translatedText.value
})
const state = computed<'loading' | 'success' | 'fail-closed'>(() => {
  if (props.translation.status === 'loading' && identityMatches.value) return 'loading'
  if (
    props.translation.status === 'success' &&
    identityMatches.value &&
    translatedText.value &&
    !sourceAlreadyChinese.value
  ) return 'success'
  return 'fail-closed'
})
</script>

<template>
  <div
    class="yance-bilingual-projection"
    data-yance-bilingual-projection
    :data-state="state"
  >
    <p v-if="state === 'success'" data-yance-translated-text>{{ translatedText }}</p>
    <span v-else-if="state === 'loading' && !silentFailClosed" class="yance-bilingual-projection__status">翻译中…</span>
    <span v-else-if="!silentFailClosed" class="yance-bilingual-projection__status">翻译暂不可用</span>
  </div>
</template>

<style scoped>
.yance-bilingual-projection {
  margin-top: var(--space-xs);
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.yance-bilingual-projection p {
  margin: 0;
  opacity: 0.78;
}

.yance-bilingual-projection__status {
  opacity: 0.7;
}
</style>
