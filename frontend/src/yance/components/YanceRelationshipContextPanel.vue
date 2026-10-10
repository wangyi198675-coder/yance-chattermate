<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { peopleService } from '@/services/people'
import type {
  RelationshipContextProjection,
  RelationshipMemoryEffect,
  RelationshipMemoryEntry,
  RelationshipMemoryKind,
} from '@/types/people'

const props = defineProps<{ customerId: string }>()

const router = useRouter()
const context = ref<RelationshipContextProjection | null>(null)
const loading = ref(false)
const error = ref('')
const saving = ref(false)
const showAdd = ref(false)
const memoryKind = ref<RelationshipMemoryKind>('note')
const memoryEffect = ref<RelationshipMemoryEffect>('context')
const memoryText = ref('')
const memorySourceRefs = ref('')
const occurredAt = ref('')
const timezone = ref('')
const preferredStart = ref('')
const preferredEnd = ref('')

const kindLabels: Record<RelationshipMemoryKind, string> = {
  fact: '确认事实',
  note: '连续性备注',
  event: '重要日期 / 事件',
  interest: '兴趣 / 稳定偏好',
  shared_moment: '共同经历',
  open_loop: '开放事项',
  promise: '承诺',
  boundary: '边界',
  sensitive_topic: '敏感话题',
}

const stageLabels = {
  unknown: '未知',
  new: '刚开始',
  developing: '发展中',
  established: '较稳定',
}

const momentumLabels = {
  unknown: '未知',
  rising: '升温',
  steady: '稳定',
  quiet: '安静',
  cooling: '降温',
}

const temperatureLabels = {
  unknown: '未知',
  warm: '温暖',
  neutral: '中性',
  cool: '偏冷',
}

const riskLabels = {
  unknown: '未知',
  low: '低',
  watch: '留意',
  elevated: '较高',
}

const daypartLabels = {
  morning: '上午',
  afternoon: '下午',
  evening: '晚上',
  night: '深夜',
}

const actionLabels = {
  reply: '回复',
  defer: '稍后',
  no_reply: '不回复',
  next_action: '下一步',
}

const allMemory = computed<RelationshipMemoryEntry[]>(() => {
  const value = context.value
  if (!value) return []
  return [
    ...value.notes,
    ...value.dated_events,
    ...value.interests,
    ...value.shared_moments,
    ...value.open_loops,
    ...value.promises,
    ...value.boundaries,
    ...value.sensitive_topics,
    ...value.confirmed_facts.filter(item => !item.id.startsWith('profile-') && !item.id.startsWith('captured-')),
  ].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
})

const activeAttention = computed(() => {
  const value = context.value
  if (!value) return []
  return [
    ...value.open_loops,
    ...value.promises,
    ...value.boundaries,
    ...value.sensitive_topics,
  ]
})

async function loadContext() {
  context.value = null
  error.value = ''
  if (!props.customerId) return
  loading.value = true
  try {
    context.value = await peopleService.getRelationshipContext(props.customerId)
    const temporal = context.value.temporal
    timezone.value = temporal.contact_timezone || ''
    preferredStart.value = temporal.preferred_contact_start || ''
    preferredEnd.value = temporal.preferred_contact_end || ''
  } catch {
    error.value = '关系上下文暂时无法读取。人物资料和原始对话证据没有被替代。'
  } finally {
    loading.value = false
  }
}

async function saveMemory() {
  const text = memoryText.value.trim()
  if (!text || saving.value) return
  saving.value = true
  error.value = ''
  try {
    await peopleService.putRelationshipMemory(props.customerId, {
      kind: memoryKind.value,
      text,
      effect: memoryEffect.value,
      occurred_at: occurredAt.value ? new Date(occurredAt.value).toISOString() : null,
      source_refs: memorySourceRefs.value
        .split(',')
        .map(item => item.trim())
        .filter(Boolean),
    })
    memoryText.value = ''
    memorySourceRefs.value = ''
    occurredAt.value = ''
    showAdd.value = false
    await loadContext()
  } catch {
    error.value = '这条记录没有保存。请检查证据引用是否属于当前人物。'
  } finally {
    saving.value = false
  }
}

async function toggleMemory(item: RelationshipMemoryEntry) {
  if (saving.value) return
  saving.value = true
  error.value = ''
  try {
    await peopleService.putRelationshipMemory(props.customerId, {
      id: item.id,
      kind: item.kind,
      text: item.text,
      active: !item.active,
      effect: item.effect,
      occurred_at: item.occurred_at || null,
      source_refs: item.evidence
        .filter(source => source.source_type !== 'operator_confirmation')
        .map(source => source.source_ref),
    })
    await loadContext()
  } catch {
    error.value = '状态没有更新，原记录保持不变。'
  } finally {
    saving.value = false
  }
}

async function saveTemporal() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  try {
    context.value = await peopleService.patchRelationshipTemporal(props.customerId, {
      contact_timezone: timezone.value.trim() || null,
      preferred_contact_start: preferredStart.value || null,
      preferred_contact_end: preferredEnd.value || null,
    })
  } catch {
    error.value = '时区或联系时段没有保存。请使用有效的 IANA 时区，例如 Europe/Berlin。'
  } finally {
    saving.value = false
  }
}

function openEvidence(source: { session_id?: string | null }) {
  if (!source.session_id) return
  router.push({ path: '/yance', query: { session: source.session_id } })
}

function formatDate(value?: string | null) {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return value
  }
}

watch(() => props.customerId, () => {
  void loadContext()
}, { immediate: true })
</script>

<template>
  <section
    class="relationship-runtime"
    :data-relationship-runtime-state="loading ? 'loading' : error && !context ? 'error' : 'ready'"
    data-window177-relationship-context
  >
    <div v-if="loading" class="runtime-notice">
      正在组合人物、对话、记忆与时间上下文…
    </div>

    <div v-else-if="error && !context" class="runtime-notice runtime-error">
      <strong>{{ error }}</strong>
      <button type="button" @click="loadContext">重试</button>
    </div>

    <template v-else-if="context">
      <div class="runtime-notice runtime-ready">
        <div>
          <strong>关系上下文已接入</strong>
          <p>
            人物身份仍来自 Customer / People，对话证据仍来自 ChatHistory；关系阶段、节奏、温度、风险与下一步只是可重算投影。
          </p>
        </div>
        <span>{{ context.relationship.message_count }} 条对话证据</span>
      </div>

      <p v-if="error" class="inline-error">{{ error }}</p>

      <div class="context-grid">
        <section id="inference" class="context-card" data-relationship-memory>
          <header class="card-head">
            <div>
              <span class="kicker">记忆与连续性</span>
              <h3>已确认记录</h3>
              <p>只保存显式确认的记录；没有证据的 AI 推测不会自动写成人物事实。</p>
            </div>
            <button type="button" class="compact-button" @click="showAdd = !showAdd">
              {{ showAdd ? '取消' : '添加确认记录' }}
            </button>
          </header>

          <form v-if="showAdd" class="memory-form" @submit.prevent="saveMemory">
            <div class="form-row">
              <label>
                类型
                <select v-model="memoryKind">
                  <option v-for="(label, key) in kindLabels" :key="key" :value="key">{{ label }}</option>
                </select>
              </label>
              <label>
                动作影响
                <select v-model="memoryEffect">
                  <option value="context">仅上下文</option>
                  <option value="defer">满足条件前稍后</option>
                  <option value="no_reply">当前不回复</option>
                </select>
              </label>
            </div>
            <label>
              内容
              <textarea v-model="memoryText" rows="3" maxlength="2000" placeholder="写下已确认的事实、承诺、边界或开放事项" />
            </label>
            <div class="form-row">
              <label>
                发生时间（可选）
                <input v-model="occurredAt" type="datetime-local">
              </label>
              <label>
                证据引用（可选，逗号分隔）
                <input v-model="memorySourceRefs" placeholder="chat_history:123">
              </label>
            </div>
            <div class="form-actions">
              <small>即使没有消息引用，也会记录“由当前操作人显式确认”的 provenance。</small>
              <button type="submit" class="primary-button" :disabled="saving || !memoryText.trim()">保存确认记录</button>
            </div>
          </form>

          <div v-if="allMemory.length" class="memory-list">
            <article v-for="item in allMemory" :key="item.id" class="memory-row">
              <div class="memory-main">
                <div class="memory-title">
                  <span>{{ kindLabels[item.kind] }}</span>
                  <small v-if="item.effect !== 'context'">{{ actionLabels[item.effect === 'no_reply' ? 'no_reply' : 'defer'] }}</small>
                </div>
                <strong>{{ item.text }}</strong>
                <small>
                  {{ item.occurred_at ? formatDate(item.occurred_at) : formatDate(item.updated_at) }}
                  · 已确认
                </small>
                <div class="source-chips">
                  <button
                    v-for="source in item.evidence"
                    :key="`${item.id}-${source.source_type}-${source.source_ref}`"
                    type="button"
                    :disabled="!source.session_id"
                    @click="openEvidence(source)"
                  >
                    {{ source.source_ref }}
                  </button>
                </div>
              </div>
              <button type="button" class="compact-button" :disabled="saving" @click="toggleMemory(item)">
                {{ item.active ? '标记不再有效' : '恢复' }}
              </button>
            </article>
          </div>
          <p v-else class="empty-copy">还没有额外的已确认关系记忆。人物资料与 ChatHistory 仍然可以直接参与投影。</p>
        </section>

        <section id="insight" class="context-card" data-relationship-derived-insight>
          <header class="card-head">
            <div>
              <span class="kicker">关系洞察</span>
              <h3>当前关系投影</h3>
              <p>所有标签都来自可见证据和规则，可随 ChatHistory 变化重新计算。</p>
            </div>
          </header>

          <div class="metric-grid">
            <div><span>阶段</span><strong>{{ stageLabels[context.relationship.stage] }}</strong></div>
            <div><span>节奏</span><strong>{{ momentumLabels[context.relationship.momentum] }}</strong></div>
            <div><span>温度</span><strong>{{ temperatureLabels[context.relationship.temperature] }}</strong></div>
            <div><span>风险</span><strong>{{ riskLabels[context.relationship.risk] }}</strong></div>
          </div>

          <div class="decision-card" :data-decision-action="context.decision.action">
            <span>下一步 · {{ actionLabels[context.decision.action] }}</span>
            <strong>{{ context.decision.next_best_action }}</strong>
            <ul>
              <li v-for="reason in context.decision.why_now" :key="reason">{{ reason }}</li>
            </ul>
            <small v-if="context.decision.defer_until">建议时间：{{ formatDate(context.decision.defer_until) }}</small>
          </div>

          <div v-if="activeAttention.length" class="attention-list">
            <article v-for="item in activeAttention" :key="`attention-${item.id}`">
              <span>{{ kindLabels[item.kind] }}</span>
              <strong>{{ item.text }}</strong>
            </article>
          </div>

          <div class="temporal-card" data-relationship-temporal>
            <div class="temporal-copy">
              <span>时间上下文</span>
              <strong>
                {{ context.temporal.contact_timezone_known ? context.temporal.contact_timezone : '联系人时区未知' }}
              </strong>
              <small>
                {{ context.temporal.contact_timezone_known ? '联系人当地' : `仅使用操作人时区 ${context.temporal.operator_timezone} 作为回退，不当作联系人当地时间` }}
                · {{ daypartLabels[context.temporal.daypart] }}
              </small>
            </div>
            <div class="temporal-form">
              <input v-model="timezone" aria-label="联系人 IANA 时区" placeholder="Europe/Berlin">
              <input v-model="preferredStart" aria-label="建议联系开始时间" type="time">
              <input v-model="preferredEnd" aria-label="建议联系结束时间" type="time">
              <button type="button" class="compact-button" :disabled="saving" @click="saveTemporal">保存时间条件</button>
            </div>
          </div>

          <div v-if="context.dated_events.length || context.shared_moments.length || context.journey.length" class="journey">
            <h4>关系旅程与重要时刻</h4>
            <article v-for="event in context.dated_events" :key="`event-${event.id}`">
              <span>{{ formatDate(event.occurred_at || event.created_at) }}</span>
              <strong>{{ event.text }}</strong>
            </article>
            <article v-for="moment in context.shared_moments" :key="`moment-${moment.id}`">
              <span>{{ formatDate(moment.occurred_at || moment.created_at) }}</span>
              <strong>{{ moment.text }}</strong>
            </article>
            <article v-for="(item, index) in context.journey.slice(-8).reverse()" :key="`journey-${index}`">
              <span>{{ formatDate(String(item.at || '')) }}</span>
              <strong>{{ item.kind === 'conversation' ? `${item.channel || 'conversation'} · ${item.status || ''}` : String(item.label || '共同经历') }}</strong>
            </article>
          </div>

          <div class="owner-note">
            <strong>图谱增强：可选，当前保持关闭</strong>
            <small>{{ context.graph_owner_reason }}</small>
          </div>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.relationship-runtime {
  display: grid;
  gap: 14px;
  margin-bottom: 14px;
}
.runtime-notice,
.context-card {
  border: 1px solid var(--o08);
  border-radius: var(--radius-lg, 14px);
  background: var(--bg2);
}
.runtime-notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  color: var(--text2, var(--text));
  font-size: 12px;
}
.runtime-notice strong,
.runtime-notice p {
  margin: 0;
}
.runtime-notice p {
  margin-top: 4px;
  color: var(--muted);
  line-height: 1.55;
}
.runtime-ready > span {
  flex: 0 0 auto;
  color: var(--muted);
}
.runtime-error {
  color: var(--danger, var(--text));
}
.inline-error {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--o10);
  border-radius: 10px;
  color: var(--danger, var(--text));
  font-size: 12px;
}
.context-grid {
  display: grid;
  grid-template-columns: minmax(0, .95fr) minmax(0, 1.05fr);
  gap: 14px;
  align-items: start;
}
.context-card {
  padding: 18px;
}
.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.card-head h3,
.card-head p,
.card-head .kicker {
  margin: 0;
}
.card-head h3 {
  margin-top: 6px;
  font-size: 18px;
}
.card-head p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
.kicker {
  color: var(--accent-ink, var(--text));
  font-size: 11px;
}
.compact-button,
.primary-button,
.source-chips button {
  border: 1px solid var(--o10);
  border-radius: 8px;
  background: var(--o05);
  color: var(--text);
  cursor: pointer;
}
.compact-button {
  padding: 7px 10px;
  font-size: 11px;
}
.primary-button {
  padding: 8px 12px;
}
.compact-button:disabled,
.primary-button:disabled,
.source-chips button:disabled {
  cursor: default;
  opacity: .58;
}
.memory-form,
.temporal-card,
.decision-card,
.owner-note,
.journey {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--o08);
  border-radius: 10px;
  background: var(--o03);
}
.memory-form {
  display: grid;
  gap: 10px;
}
.form-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.memory-form label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 11px;
}
.memory-form input,
.memory-form select,
.memory-form textarea,
.temporal-form input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--o10);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
  padding: 8px 9px;
  font: inherit;
}
.memory-form textarea {
  resize: vertical;
}
.form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.form-actions small {
  color: var(--muted);
  font-size: 10px;
  line-height: 1.45;
}
.memory-list {
  margin-top: 12px;
}
.memory-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 0;
  border-top: 1px solid var(--o08);
}
.memory-row:first-child {
  border-top: 0;
}
.memory-main {
  min-width: 0;
  display: grid;
  gap: 4px;
}
.memory-title {
  display: flex;
  align-items: center;
  gap: 6px;
}
.memory-title span,
.memory-title small,
.memory-main > small {
  color: var(--muted);
  font-size: 10px;
}
.memory-main > strong {
  font-size: 13px;
  overflow-wrap: anywhere;
}
.source-chips {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  margin-top: 3px;
}
.source-chips button {
  padding: 3px 6px;
  color: var(--muted);
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 9px;
}
.empty-copy {
  margin: 14px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}
.metric-grid > div {
  display: grid;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--o08);
  border-radius: 9px;
  background: var(--o03);
}
.metric-grid span,
.decision-card span,
.temporal-copy span,
.owner-note small,
.journey span {
  color: var(--muted);
  font-size: 10px;
}
.metric-grid strong {
  font-size: 13px;
}
.decision-card {
  display: grid;
  gap: 6px;
}
.decision-card > strong {
  font-size: 13px;
}
.decision-card ul {
  margin: 0;
  padding-left: 18px;
  color: var(--muted);
  font-size: 10px;
}
.decision-card small {
  color: var(--muted);
}
.attention-list {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}
.attention-list article {
  display: grid;
  gap: 3px;
  padding: 8px 10px;
  border-left: 2px solid var(--accent-border, var(--o20));
  background: var(--o03);
}
.attention-list span {
  color: var(--muted);
  font-size: 10px;
}
.attention-list strong {
  font-size: 12px;
}
.temporal-card {
  display: grid;
  gap: 10px;
}
.temporal-copy {
  display: grid;
  gap: 4px;
}
.temporal-copy strong {
  font-size: 13px;
}
.temporal-copy small {
  color: var(--muted);
  font-size: 10px;
  line-height: 1.45;
}
.temporal-form {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) 100px 100px auto;
  gap: 7px;
}
.journey {
  display: grid;
  gap: 7px;
}
.journey h4 {
  margin: 0 0 2px;
  font-size: 12px;
}
.journey article {
  display: grid;
  grid-template-columns: 118px minmax(0, 1fr);
  gap: 8px;
}
.journey strong {
  font-size: 11px;
  overflow-wrap: anywhere;
}
.owner-note {
  display: grid;
  gap: 4px;
}
.owner-note strong {
  font-size: 11px;
}
@media (max-width: 900px) {
  .context-grid {
    grid-template-columns: 1fr;
  }
  .temporal-form {
    grid-template-columns: 1fr 1fr;
  }
}
@media (max-width: 620px) {
  .metric-grid,
  .form-row,
  .temporal-form {
    grid-template-columns: 1fr;
  }
  .memory-row,
  .form-actions,
  .card-head {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
