<script setup lang="ts">
import { computed } from 'vue'
import type {
  YanceCandidateRuntimeState,
  YanceHumanLikenessState,
  YanceReplyBrainCandidate,
} from '../semanticTypes'

const props = defineProps<{
  candidate: YanceReplyBrainCandidate
  processing?: boolean
}>()

const emit = defineEmits<{
  (event: 'adopt', candidate: YanceReplyBrainCandidate): void
  (event: 'reject', candidate: YanceReplyBrainCandidate): void
}>()

const humanLikeness = computed<YanceHumanLikenessState>(
  () => props.candidate.humanLikeness ?? 'unknown',
)

const runtimeState = computed<YanceCandidateRuntimeState>(() => {
  if (props.candidate.runtimeState) return props.candidate.runtimeState
  return ['voice', 'photo', 'image', 'video', 'file'].includes(props.candidate.type)
    ? 'runtime-pending'
    : 'ready'
})

const modalityCandidate = computed(
  () => ['voice', 'photo', 'image', 'video', 'file'].includes(props.candidate.type),
)

const hasMaterializedAttachment = computed(
  () => modalityCandidate.value && Number.isInteger(props.candidate.attachmentId) && Number(props.candidate.attachmentId) > 0,
)

const adoptionKind = computed(() => {
  if (props.candidate.type === 'text') return 'text-draft'
  if (!modalityCandidate.value) return 'none'
  return hasMaterializedAttachment.value ? 'attachment' : 'generation-intent'
})

const humanLikenessLabel = computed(() => ({
  pass: '真人感通过',
  review: '真人感待复核',
  blocked: '真人感拦截',
  unknown: '真人感未校验',
}[humanLikeness.value]))

const readinessLabel = computed(() => ({
  ready: '可采用',
  'runtime-pending': '运行时未就绪',
  unavailable: '当前不可用',
}[runtimeState.value]))

// Multimodal adoption is a Composer staging action, never a send. A real
// FileAttachment ID adopts the existing canonical asset. Without one, an
// admitted media owner may still stage the generation intent while a live
// provider is pending. Fully unavailable owners remain fail-closed.
const adoptable = computed(() => {
  if (humanLikeness.value !== 'pass') return false
  if (props.candidate.type === 'text') return runtimeState.value === 'ready'
  if (!modalityCandidate.value) return false
  if (hasMaterializedAttachment.value) return true
  return runtimeState.value !== 'unavailable'
})

const adopt = () => {
  if (!adoptable.value || props.processing) return
  emit('adopt', props.candidate)
}
</script>

<template>
  <article
    class="yance-reply-candidate"
    data-yance-reply-candidate
    :data-candidate-type="candidate.type"
    :data-candidate-runtime="runtimeState"
  >
    <header class="yance-reply-candidate__header">
      <strong>{{ candidate.label }}</strong>
      <span>{{ candidate.type }}</span>
    </header>

    <div class="yance-reply-candidate__status">
      <span data-yance-human-likeness :data-human-likeness="humanLikeness">
        {{ humanLikenessLabel }}
      </span>
      <span data-yance-candidate-readiness :data-runtime-state="runtimeState">
        {{ readinessLabel }}
      </span>
    </div>

    <section
      v-if="modalityCandidate"
      class="yance-reply-candidate__modality"
      data-yance-modality-preview
      :data-modality="candidate.type"
      :data-runtime-state="runtimeState"
      :data-adoption-kind="adoptionKind"
    >
      <strong>{{ candidate.previewLabel || '媒体预览状态' }}</strong>
      <span v-if="hasMaterializedAttachment">已有 canonical FileAttachment，可采用到 Composer 附件状态。</span>
      <span v-else-if="runtimeState === 'ready'">成熟 owner 可用；资产尚未物化，可先采用生成意图。</span>
      <span v-else-if="runtimeState === 'runtime-pending'">实时 provider 暂未就绪；生成意图仍可采用到 Composer。</span>
      <span v-else>当前没有可用 owner，采用路径 fail-closed。</span>
    </section>

    <p class="yance-reply-candidate__draft">{{ candidate.draft }}</p>

    <details
      v-if="candidate.why || candidate.evidence?.length"
      class="yance-reply-candidate__why"
      data-yance-candidate-why
    >
      <summary>为什么这样建议？</summary>
      <p v-if="candidate.why">{{ candidate.why }}</p>
      <ul v-if="candidate.evidence?.length" data-yance-candidate-evidence>
        <li v-for="item in candidate.evidence" :key="item">{{ item }}</li>
      </ul>
    </details>

    <p
      v-if="(runtimeState === 'unavailable' && !hasMaterializedAttachment) || (!modalityCandidate && runtimeState !== 'ready')"
      class="yance-reply-candidate__blocked"
      data-yance-candidate-runtime-note
    >
      当前 owner/runtime 不支持采用。
    </p>
    <p
      v-else-if="humanLikeness !== 'pass'"
      class="yance-reply-candidate__blocked"
      data-yance-candidate-human-note
    >
      通过真人感校验后才能采用。
    </p>

    <div class="yance-reply-candidate__actions">
      <button
        type="button"
        data-yance-adopt
        :disabled="!adoptable || processing"
        :aria-disabled="!adoptable || processing"
        :aria-busy="Boolean(processing)"
        :data-adoption-kind="adoptionKind"
        @click="adopt"
      >
        {{ processing ? '采用中…' : '采用' }}
      </button>
      <button
        type="button"
        data-yance-reject
        @click="emit('reject', candidate)"
      >
        不采用
      </button>
    </div>
  </article>
</template>

<style scoped>
.yance-reply-candidate {
  padding: var(--space-sm);
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--bg2);
}

.yance-reply-candidate__header,
.yance-reply-candidate__status {
  display: flex;
  justify-content: space-between;
  gap: var(--space-sm);
}

.yance-reply-candidate__header {
  color: var(--text);
  font-size: 12px;
}

.yance-reply-candidate__header span,
.yance-reply-candidate__why,
.yance-reply-candidate__blocked,
.yance-reply-candidate__modality span {
  color: var(--muted);
}

.yance-reply-candidate__status {
  margin-top: 6px;
  justify-content: flex-start;
  flex-wrap: wrap;
}

.yance-reply-candidate__status span {
  padding: 3px 6px;
  border-radius: 999px;
  background: var(--o05);
  color: var(--muted);
  font-size: 10px;
}

.yance-reply-candidate__modality {
  display: grid;
  gap: 3px;
  margin-top: 8px;
  padding: 8px 9px;
  border: 1px dashed var(--o12);
  border-radius: 8px;
  background: var(--o03);
  font-size: 11px;
  line-height: 1.4;
}

.yance-reply-candidate__modality strong {
  color: var(--text);
}

.yance-reply-candidate__draft {
  margin: var(--space-xs) 0;
  color: var(--text);
  font-size: 13px;
  line-height: 1.45;
}

.yance-reply-candidate__why {
  margin: 0 0 var(--space-xs);
  font-size: 11px;
}

.yance-reply-candidate__why summary {
  color: var(--text3);
  cursor: pointer;
  user-select: none;
}

.yance-reply-candidate__why p,
.yance-reply-candidate__why ul {
  margin: 6px 0 0;
  padding-left: 0;
}

.yance-reply-candidate__why ul {
  padding-left: 16px;
}

.yance-reply-candidate__blocked {
  margin: 0 0 var(--space-xs);
  font-size: 11px;
}

.yance-reply-candidate__actions {
  display: flex;
  gap: 6px;
}

.yance-reply-candidate button {
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--o05);
  color: var(--text);
  padding: 6px 10px;
  cursor: pointer;
}

.yance-reply-candidate button:disabled {
  opacity: .45;
  cursor: not-allowed;
}
</style>
