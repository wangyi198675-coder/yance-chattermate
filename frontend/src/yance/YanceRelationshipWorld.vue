<script setup lang="ts">
import YanceWebShell from './components/YanceWebShell.vue'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import CustomerAvatar from '@/components/people/CustomerAvatar.vue'
import YanceRelationshipContextPanel from './components/YanceRelationshipContextPanel.vue'
import { peopleService } from '@/services/people'
import type { PersonDetail } from '@/types/people'

type FactRow = {
  label: string
  value: string
  source: string
}

type EvidenceRow = {
  id: string
  title: string
  detail: string
  source: string
  at?: string | null
  sourceRef?: string | null
  sessionId?: string
}

const route = useRoute()
const router = useRouter()
const person = ref<PersonDetail | null>(null)
const loading = ref(false)
const error = ref('')

const customerId = computed(() => {
  const value = route.params.customerId
  return Array.isArray(value) ? value[0] ?? '' : value ?? ''
})

const displayName = computed(() =>
  person.value?.name || person.value?.email || person.value?.phone || '未命名人物'
)

const profileSummary = computed(() => {
  const profile = person.value?.profile
  if (!profile) return ''
  return [
    profile.city || profile.region || profile.country || profile.raw_location,
    profile.age != null ? `${profile.age}岁` : '',
    profile.occupation || '',
  ].filter(Boolean).join(' · ')
})

const factRows = computed<FactRow[]>(() => {
  const current = person.value
  if (!current) return []

  const profile = current.profile
  const rows: FactRow[] = []

  if (current.name) {
    rows.push({ label: '姓名', value: current.name, source: '人物资料' })
  }
  if (profile?.city || profile?.region || profile?.country || profile?.raw_location) {
    rows.push({
      label: '所在地',
      value: [profile.city || profile.region || profile.raw_location, profile.country]
        .filter(Boolean)
        .join(' · '),
      source: '人物资料',
    })
  }
  if (profile?.age != null) {
    rows.push({ label: '年龄', value: `${profile.age}岁`, source: '人物资料' })
  }
  if (profile?.occupation) {
    rows.push({ label: '职业', value: profile.occupation, source: '人物资料' })
  }
  if (current.email) {
    rows.push({ label: '邮箱', value: current.email, source: '人物身份' })
  }
  if (current.phone) {
    rows.push({ label: '电话', value: current.phone, source: '人物身份' })
  }

  return rows
})

const evidenceRows = computed<EvidenceRow[]>(() => {
  const current = person.value
  if (!current) return []

  const rows: EvidenceRow[] = []

  if (current.created_at) {
    rows.push({
      id: 'person-created',
      title: '人物记录',
      detail: '此人物已存在于人物目录中。',
      source: '人物资料',
      at: current.created_at,
    })
  }

  const ageObservation = current.profile?.age_observation
  if (ageObservation?.observed_at || ageObservation?.source_ref) {
    rows.push({
      id: 'age-observation',
      title: '年龄资料来源',
      detail: `记录值：${ageObservation.value}岁`,
      source: '人物资料',
      at: ageObservation.observed_at,
      sourceRef: ageObservation.source_ref,
    })
  }

  const avatar = current.profile?.avatar
  if (avatar?.observed_at || avatar?.source_ref || avatar?.source_channel) {
    rows.push({
      id: 'avatar-observation',
      title: '头像资料来源',
      detail: avatar.source_channel ? `来自 ${avatar.source_channel}` : '已记录头像来源',
      source: '人物资料',
      at: avatar.observed_at,
      sourceRef: avatar.source_ref,
    })
  }

  current.timeline.slice(0, 4).forEach((entry, index) => {
    rows.push({
      id: `people-timeline-${index}`,
      title: '人物状态记录',
      detail: entry.stage,
      source: '人物资料',
      at: entry.at,
    })
  })

  current.conversations.slice(0, 5).forEach((conversation, index) => {
    rows.push({
      id: `conversation-${conversation.session_id}-${index}`,
      title: '对话记录',
      detail: conversation.last_message || conversation.status || '已有对话记录',
      source: '对话记录',
      at: conversation.created_at,
      sessionId: conversation.session_id,
    })
  })

  return rows
})

async function loadPerson() {
  person.value = null
  error.value = ''

  if (!customerId.value) return

  loading.value = true
  try {
    person.value = await peopleService.getPerson(customerId.value)
  } catch {
    error.value = '暂时无法读取这个人物的资料'
  } finally {
    loading.value = false
  }
}

function formatDate(value?: string | null): string {
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

function openConversation(sessionId: string) {
  router.push({ path: '/yance', query: { session: sessionId } })
}

watch(customerId, () => {
  void loadPerson()
}, { immediate: true })
</script>

<template>
  <DashboardLayout>
    <YanceWebShell>
    <main class="relationship-world" data-yance-relationship-world>
      <header class="world-topbar">
        <div class="brand-block">
          <p class="eyebrow">言策 Yance</p>
          <h1>关系世界</h1>
        </div>
        <nav class="world-nav" aria-label="言策主导航">
          <button type="button" @click="router.push('/yance/home')">首页</button>
          <button type="button" @click="router.push('/yance')">对话</button>
          <button type="button" class="active" aria-current="page">关系世界</button>
          <button type="button" @click="router.push('/yance/settings')">设置</button>
        </nav>
      </header>

      <section v-if="!customerId" class="selection-state">
        <div class="selection-icon" aria-hidden="true">人</div>
        <h2>选择一个人物</h2>
        <p>从人物目录或首页的最近对话进入后，可以查看已确认资料和现有证据。</p>
        <div class="selection-actions">
          <button type="button" class="primary-action" @click="router.push('/yance/people')">打开人物目录</button>
          <button type="button" @click="router.push('/yance/home')">返回首页</button>
        </div>
      </section>

      <section v-else-if="loading" class="selection-state">
        <h2>正在读取人物资料…</h2>
      </section>

      <section v-else-if="error" class="selection-state error-state">
        <h2>{{ error }}</h2>
        <p>人物资料没有被替代或补写。</p>
        <div class="selection-actions">
          <button type="button" class="primary-action" @click="loadPerson">重试</button>
          <button type="button" @click="router.push('/yance/people')">打开人物目录</button>
        </div>
      </section>

      <template v-else-if="person">
        <section class="person-hero">
          <CustomerAvatar
            class="world-avatar"
            :profile="person.profile"
            :display-name="displayName"
            :anonymous="person.is_anonymous"
            :size="88"
          />
          <div class="person-copy">
            <div class="person-name-row">
              <h2>{{ displayName }}</h2>
              <span class="identity-badge">人物资料</span>
            </div>
            <p class="provenance-line">资料可追溯到人物记录与现有对话。</p>
            <p v-if="profileSummary" class="profile-summary">{{ profileSummary }}</p>
          </div>
          <button type="button" class="change-person" @click="router.push('/yance/people')">换一个人物</button>
        </section>

        <nav class="section-tabs" aria-label="关系世界内容">
          <a href="#facts">资料与事实</a>
          <a href="#inference">推测</a>
          <a href="#insight">关系洞察</a>
          <a href="#evidence">历史与证据</a>
        </nav>

        <YanceRelationshipContextPanel :customer-id="customerId" />

        <section
          v-if="false"
          class="truth-notice unavailable"
          data-truth-kind="unavailable-runtime"
          data-relationship-runtime-state="unavailable"
        >
          <div>
            <strong>关系洞察尚未启用</strong>
            <p>
              目前可以查看人物事实和已有证据。关系阶段、节奏、风险、开放事项、意图与下一步建议不会在没有可信来源时生成。
            </p>
          </div>
        </section>

        <div class="relationship-grid">
          <div class="relationship-column">
            <section id="facts" class="truth-card facts-card" data-truth-kind="fact" data-relationship-facts>
              <header class="card-heading">
                <div>
                  <span class="truth-label fact-label">事实</span>
                  <h3>已确认资料</h3>
                  <p>来自当前人物资料的可展示信息。</p>
                </div>
                <span class="count-badge">{{ factRows.length }} 条</span>
              </header>

              <div v-if="factRows.length" class="fact-list">
                <div v-for="fact in factRows" :key="`${fact.label}-${fact.value}`" class="fact-row">
                  <span>{{ fact.label }}</span>
                  <strong>{{ fact.value }}</strong>
                  <small>{{ fact.source }}</small>
                </div>
              </div>
              <p v-else class="empty-copy">没有可展示的已确认资料。</p>
            </section>

            <section
              v-if="false"
              id="inference"
              class="truth-card unavailable-card"
              data-truth-kind="inference"
              data-relationship-inference
            >
              <header class="card-heading">
                <div>
                  <span class="truth-label inference-label">推测</span>
                  <h3>待确认推测</h3>
                </div>
                <span class="unavailable-badge">暂不可用</span>
              </header>
              <p>
                当前没有已接入的可信推测来源，因此不会展示兴趣、偏好、意图或其它猜测。
              </p>
            </section>
          </div>

          <div class="relationship-column">
            <section
              v-if="false"
              id="insight"
              class="truth-card unavailable-card"
              data-truth-kind="derived-insight"
              data-relationship-derived-insight
            >
              <header class="card-heading">
                <div>
                  <span class="truth-label insight-label">关系洞察</span>
                  <h3>关系理解与建议</h3>
                </div>
                <span class="unavailable-badge">暂不可用</span>
              </header>
              <p>
                暂不生成关系阶段、关系温度、互动节奏、风险、开放事项、承诺、意图或下一步建议。
              </p>
            </section>

            <section id="evidence" class="truth-card evidence-card" data-truth-kind="evidence" data-relationship-evidence>
              <header class="card-heading">
                <div>
                  <span class="truth-label evidence-label">证据</span>
                  <h3>来源与证据</h3>
                  <p>只展示当前人物资料和已有对话中的可追溯记录。</p>
                </div>
                <span class="count-badge">{{ evidenceRows.length }} 条</span>
              </header>

              <div v-if="evidenceRows.length" class="evidence-list">
                <article v-for="item in evidenceRows" :key="item.id" class="evidence-row">
                  <div class="evidence-copy">
                    <strong>{{ item.title }}</strong>
                    <p>{{ item.detail }}</p>
                    <small>
                      {{ item.source }}
                      <template v-if="item.at"> · {{ formatDate(item.at) }}</template>
                    </small>
                    <small v-if="item.sourceRef" class="source-ref">{{ item.sourceRef }}</small>
                  </div>
                  <button
                    v-if="item.sessionId"
                    type="button"
                    class="evidence-action"
                    @click="openConversation(item.sessionId)"
                  >
                    查看对话
                  </button>
                </article>
              </div>
              <p v-else class="empty-copy">暂无可展示的证据记录。</p>
            </section>
          </div>
        </div>
      </template>
    </main>
      </YanceWebShell>
  </DashboardLayout>
</template>

<style scoped>
.relationship-world {
  width: min(1160px, calc(100% - 40px));
  margin: 0 auto;
  padding: 26px 0 44px;
  color: var(--text);
}
.world-topbar,
.person-hero,
.person-name-row,
.card-heading,
.evidence-row {
  display: flex;
  align-items: center;
}
.world-topbar,
.card-heading,
.evidence-row {
  justify-content: space-between;
}
.world-topbar {
  gap: 18px;
  margin-bottom: 18px;
}
.brand-block h1,
.person-copy h2,
.card-heading h3 {
  margin: 0;
}
.brand-block h1 {
  font-size: 26px;
}
.eyebrow {
  margin: 0 0 4px;
  color: var(--muted);
  font-size: 12px;
}
.world-nav,
.selection-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.world-nav button,
.selection-actions button,
.change-person,
.evidence-action {
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--o05);
  color: var(--text);
  padding: 8px 12px;
  cursor: pointer;
}
.world-nav button.active,
.primary-action {
  border-color: var(--accent-border, var(--o20)) !important;
  background: var(--accent-bg-12, var(--o08)) !important;
  color: var(--accent-ink, var(--text)) !important;
}
.selection-state {
  min-height: 390px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 10px;
  padding: 40px;
  border: 1px solid var(--o08);
  border-radius: var(--radius-lg, 16px);
  background: var(--bg2);
  text-align: center;
}
.selection-state h2,
.selection-state p {
  margin: 0;
}
.selection-state p {
  max-width: 520px;
  color: var(--muted);
  line-height: 1.6;
}
.selection-icon {
  width: 58px;
  height: 58px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--accent-bg-12, var(--o08));
  color: var(--accent-ink, var(--text));
  font-weight: 700;
}
.selection-actions {
  margin-top: 8px;
  justify-content: center;
}
.person-hero {
  gap: 18px;
  padding: 18px;
  border: 1px solid var(--o08);
  border-radius: var(--radius-lg, 16px);
  background: var(--bg2);
}
.world-avatar {
  flex: 0 0 auto;
}
.person-copy {
  min-width: 0;
  flex: 1;
}
.person-name-row {
  gap: 10px;
  flex-wrap: wrap;
}
.person-copy h2 {
  font-size: 27px;
}
.identity-badge,
.count-badge,
.unavailable-badge,
.truth-label {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 9px;
  border: 1px solid var(--o10);
  border-radius: 999px;
  color: var(--muted);
  font-size: 11px;
}
.provenance-line,
.profile-summary {
  margin: 5px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.profile-summary {
  color: var(--text2, var(--text));
  font-size: 13px;
}
.change-person {
  flex: 0 0 auto;
}
.section-tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 14px 0;
}
.section-tabs a {
  padding: 11px 12px;
  border: 1px solid var(--o08);
  border-radius: 10px;
  background: var(--bg2);
  color: var(--text2, var(--text));
  text-align: center;
  text-decoration: none;
  font-size: 13px;
}
.truth-notice {
  margin-bottom: 14px;
  padding: 14px 16px;
  border: 1px solid var(--o10);
  border-radius: 12px;
  background: var(--bg2);
}
.truth-notice strong {
  display: block;
  margin-bottom: 4px;
}
.truth-notice p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
.relationship-grid {
  display: grid;
  grid-template-columns: minmax(0, .95fr) minmax(0, 1.05fr);
  gap: 14px;
  align-items: start;
}
.relationship-column {
  display: grid;
  gap: 14px;
}
.truth-card {
  padding: 18px;
  border: 1px solid var(--o08);
  border-radius: var(--radius-lg, 14px);
  background: var(--bg2);
}
.card-heading {
  gap: 12px;
  align-items: flex-start;
}
.card-heading h3 {
  margin-top: 7px;
  font-size: 18px;
}
.card-heading p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.fact-label {
  color: var(--success, var(--accent-ink));
}
.inference-label {
  color: var(--c-purple, var(--muted));
}
.insight-label,
.evidence-label {
  color: var(--accent-ink, var(--text));
}
.fact-list,
.evidence-list {
  margin-top: 14px;
}
.fact-row {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-height: 44px;
  padding: 8px 0;
  border-top: 1px solid var(--o08);
}
.fact-row:first-child {
  border-top: 0;
}
.fact-row span,
.fact-row small {
  color: var(--muted);
  font-size: 11px;
}
.fact-row strong {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 13px;
}
.unavailable-card p,
.empty-copy {
  margin: 14px 0 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}
.unavailable-badge {
  flex: 0 0 auto;
}
.evidence-row {
  gap: 14px;
  align-items: flex-start;
  padding: 12px 0;
  border-top: 1px solid var(--o08);
}
.evidence-row:first-child {
  border-top: 0;
}
.evidence-copy {
  min-width: 0;
  flex: 1;
}
.evidence-copy strong {
  font-size: 13px;
}
.evidence-copy p {
  margin: 4px 0;
  color: var(--text2, var(--text));
  font-size: 12px;
  overflow-wrap: anywhere;
}
.evidence-copy small {
  display: block;
  color: var(--muted);
  font-size: 11px;
}
.source-ref {
  margin-top: 3px;
  overflow-wrap: anywhere;
  font-family: var(--font-mono, ui-monospace, monospace);
}
.evidence-action {
  flex: 0 0 auto;
  padding: 6px 9px;
  font-size: 11px;
}

@media (max-width: 860px) {
  .relationship-grid {
    grid-template-columns: 1fr;
  }
  .section-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 640px) {
  .relationship-world {
    width: calc(100% - 24px);
    padding-top: 16px;
  }
  .world-topbar,
  .person-hero {
    align-items: flex-start;
    flex-direction: column;
  }
  .world-nav {
    width: 100%;
  }
  .world-nav button {
    flex: 1 1 calc(50% - 8px);
  }
  .change-person {
    align-self: stretch;
  }
  .fact-row {
    grid-template-columns: 72px minmax(0, 1fr);
  }
  .fact-row small {
    grid-column: 2;
  }
}
</style>
