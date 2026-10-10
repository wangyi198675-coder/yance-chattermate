<script setup lang="ts">
import { computed, ref } from 'vue'
import BaseModal from '@/components/common/BaseModal.vue'
import type {
  YanceCapabilityReadinessProjection,
  YanceGirlfriendIntentDraft,
  YanceGirlfriendOrchestrationProjection,
  YanceGirlfriendScope,
} from '../semanticTypes'

const props = defineProps<{
  voiceReadiness: YanceCapabilityReadinessProjection
  imageReadiness: YanceCapabilityReadinessProjection
  videoReadiness: YanceCapabilityReadinessProjection
  orchestration?: YanceGirlfriendOrchestrationProjection
}>()

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'intent-draft', draft: YanceGirlfriendIntentDraft): void
  (event: 'undo-request'): void
  (event: 'permission-decision', decision: 'allow-once' | 'cancel'): void
}>()

const instruction = ref('')
const scope = ref<YanceGirlfriendScope>('turn')
const personaNote = ref('')
const goalNote = ref('')
const turnOnly = ref(true)
const staged = ref(false)

const canStage = computed(() => instruction.value.trim().length > 0)
const orchestrationState = computed(() => props.orchestration?.state ?? 'idle')

const orchestrationTitle = computed(() => {
  if (props.orchestration?.title) return props.orchestration.title
  return {
    idle: '',
    interpreting: '正在理解这条要求',
    clarification: '需要你再确认一点',
    'scoped-proposal': '已整理作用范围',
    'delegated-owner-wait': '相关能力暂未就绪',
    receipt: '已收到执行回执',
    'permission-required': '需要你的确认',
    stale: '当前建议已过期',
    recomputing: '正在根据最新上下文重新整理',
  }[orchestrationState.value]
})

const stageIntent = () => {
  if (!canStage.value) return

  emit('intent-draft', {
    instruction: instruction.value.trim(),
    scope: scope.value,
    personaNote: personaNote.value.trim() || undefined,
    goalNote: goalNote.value.trim() || undefined,
    turnOnly: turnOnly.value,
  })
  staged.value = true
}
</script>

<template>
  <BaseModal title="闺蜜大脑" width="620px" @close="emit('close')">
    <section class="girlfriend-brain" data-yance-girlfriend-native>
      <p class="girlfriend-brain__intro">
        告诉我这一轮你想怎么处理。这里先整理意图和范围，不会替你直接发送消息。
      </p>

      <section
        v-if="orchestrationState !== 'idle'"
        class="girlfriend-brain__orchestration"
        data-yance-girlfriend-orchestration
        :data-orchestration-state="orchestrationState"
      >
        <strong>{{ orchestrationTitle }}</strong>
        <p v-if="props.orchestration?.detail">{{ props.orchestration.detail }}</p>

        <div
          v-if="props.orchestration?.capability || props.orchestration?.model"
          class="girlfriend-brain__delegation"
          data-yance-girlfriend-delegation
        >
          <span v-if="props.orchestration?.capability">能力：{{ props.orchestration.capability }}</span>
          <span v-if="props.orchestration?.model">模型：{{ props.orchestration.model }}</span>
        </div>

        <details v-if="props.orchestration?.why" data-yance-girlfriend-why>
          <summary>为什么这样建议？</summary>
          <p>{{ props.orchestration.why }}</p>
        </details>

        <div
          v-if="orchestrationState === 'receipt' && props.orchestration?.receipt"
          class="girlfriend-brain__owner-receipt"
          data-yance-girlfriend-owner-receipt
        >
          {{ props.orchestration.receipt }}
          <button
            type="button"
            data-yance-girlfriend-undo
            :disabled="!props.orchestration.undoAvailable"
            @click="emit('undo-request')"
          >
            {{ props.orchestration.undoAvailable ? '撤销' : '当前不可撤销' }}
          </button>
        </div>

        <div
          v-if="orchestrationState === 'permission-required'"
          class="girlfriend-brain__permission"
          data-yance-girlfriend-permission
        >
          <p>{{ props.orchestration?.permissionPrompt || '这项敏感操作需要你明确确认。' }}</p>
          <div>
            <button type="button" @click="emit('permission-decision', 'cancel')">取消</button>
            <button type="button" @click="emit('permission-decision', 'allow-once')">仅允许这一次</button>
          </div>
        </div>
      </section>

      <label class="girlfriend-brain__field">
        <span>你想让我怎么帮你</span>
        <textarea
          v-model="instruction"
          rows="4"
          data-yance-girlfriend-intent
          placeholder="例如：语气自然一点，别急着问问题，先接住他刚才说的内容。"
        />
      </label>

      <fieldset class="girlfriend-brain__scope" data-yance-girlfriend-scope>
        <legend>这条要求适用于</legend>
        <label><input v-model="scope" type="radio" value="turn"> 仅本轮</label>
        <label><input v-model="scope" type="radio" value="contact"> 当前联系人</label>
        <label><input v-model="scope" type="radio" value="language"> 当前语言</label>
        <label><input v-model="scope" type="radio" value="relationship"> 当前关系</label>
        <label><input v-model="scope" type="radio" value="global"> 全局</label>
      </fieldset>

      <div class="girlfriend-brain__grid">
        <label class="girlfriend-brain__field">
          <span>人格要求（可选）</span>
          <input
            v-model="personaNote"
            data-yance-girlfriend-persona
            type="text"
            placeholder="例如：成熟、自然、不过度热情"
          >
        </label>

        <label class="girlfriend-brain__field">
          <span>当前目标（可选）</span>
          <input
            v-model="goalNote"
            data-yance-girlfriend-goal
            type="text"
            placeholder="例如：把话题自然延续下去"
          >
        </label>
      </div>

      <label class="girlfriend-brain__turn-only">
        <input v-model="turnOnly" data-yance-girlfriend-turn-only type="checkbox">
        仅本轮，不学习
      </label>

      <section class="girlfriend-brain__capabilities" aria-label="能力状态">
        <h4>能力与委派</h4>
        <div class="girlfriend-brain__capability-grid">
          <button
            type="button"
            data-yance-voice-readiness
            :data-runtime-state="props.voiceReadiness.runtimeState"
            disabled
          >
            {{ props.voiceReadiness.label }}
          </button>
          <button
            type="button"
            data-yance-image-readiness
            :data-runtime-state="props.imageReadiness.runtimeState"
            disabled
          >
            {{ props.imageReadiness.label }}
          </button>
          <button
            type="button"
            data-yance-video-readiness
            :data-runtime-state="props.videoReadiness.runtimeState"
            disabled
          >
            {{ props.videoReadiness.label }}
          </button>
          <button
            type="button"
            data-yance-photo-file-delegation
            data-runtime-state="ready-in-composer"
            disabled
          >
            照片 / 文件请在输入框 + 选择
          </button>
          <button
            type="button"
            data-yance-model-delegation
            data-runtime-state="unavailable"
            disabled
          >
            模型切换暂不可用
          </button>
        </div>
        <p class="girlfriend-brain__readiness-note">
          这里只显示已经接通的能力状态；暂不可用的动作不会显示成可执行。
        </p>
      </section>

      <div v-if="staged" class="girlfriend-brain__receipt" data-yance-girlfriend-receipt>
        已整理到本轮意图草稿。最终回复仍需回到对话输入框确认并发送。
      </div>
    </section>

    <template #actions>
      <button type="button" class="girlfriend-brain__secondary" @click="emit('close')">关闭</button>
      <button
        type="button"
        class="girlfriend-brain__primary"
        data-yance-stage-intent
        :disabled="!canStage"
        @click="stageIntent"
      >
        整理这条意图
      </button>
    </template>
  </BaseModal>
</template>

<style scoped>
.girlfriend-brain {
  display: grid;
  gap: var(--space-md);
  color: var(--text);
}

.girlfriend-brain__intro,
.girlfriend-brain__readiness-note,
.girlfriend-brain__orchestration p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.girlfriend-brain__orchestration {
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--o04);
}

.girlfriend-brain__orchestration strong {
  font-size: 12px;
}

.girlfriend-brain__orchestration details {
  color: var(--muted);
  font-size: 12px;
}

.girlfriend-brain__orchestration summary {
  color: var(--text3);
  cursor: pointer;
}

.girlfriend-brain__delegation {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.girlfriend-brain__delegation span {
  padding: 4px 7px;
  border-radius: 999px;
  background: var(--o06);
  color: var(--text3);
  font-size: 11px;
}

.girlfriend-brain__owner-receipt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--text);
  font-size: 12px;
}

.girlfriend-brain__owner-receipt button,
.girlfriend-brain__permission button {
  border: 1px solid var(--o10);
  border-radius: 8px;
  background: var(--o05);
  color: var(--text);
  padding: 6px 8px;
}

.girlfriend-brain__owner-receipt button:disabled {
  opacity: .45;
}

.girlfriend-brain__permission {
  display: grid;
  gap: 8px;
}

.girlfriend-brain__permission > div {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.girlfriend-brain__field {
  display: grid;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
}

.girlfriend-brain__field textarea,
.girlfriend-brain__field input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--bg2);
  color: var(--text);
  padding: 10px 12px;
  font: inherit;
}

.girlfriend-brain__scope {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
}

.girlfriend-brain__scope legend {
  padding: 0 6px;
  color: var(--muted);
  font-size: 12px;
}

.girlfriend-brain__scope label,
.girlfriend-brain__turn-only {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.girlfriend-brain__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-sm);
}

.girlfriend-brain__capabilities {
  display: grid;
  gap: 8px;
  padding-top: 4px;
}

.girlfriend-brain__capabilities h4 {
  margin: 0;
  font-size: 12px;
  color: var(--text);
}

.girlfriend-brain__capability-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.girlfriend-brain__capability-grid button,
.girlfriend-brain__secondary,
.girlfriend-brain__primary {
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  padding: 8px 10px;
  font: inherit;
}

.girlfriend-brain__capability-grid button {
  background: var(--o05);
  color: var(--muted);
  cursor: not-allowed;
  opacity: .78;
}

.girlfriend-brain__secondary {
  background: var(--o05);
  color: var(--text);
  cursor: pointer;
}

.girlfriend-brain__primary {
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  border-color: transparent;
  cursor: pointer;
}

.girlfriend-brain__primary:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.girlfriend-brain__receipt {
  padding: 10px 12px;
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--o05);
  font-size: 12px;
  color: var(--text);
}

@media (max-width: 640px) {
  .girlfriend-brain__grid,
  .girlfriend-brain__capability-grid {
    grid-template-columns: 1fr;
  }
}
</style>
