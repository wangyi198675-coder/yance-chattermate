<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ChatDetail } from '@/types/chat'
import {
  personaService,
  type PersonaHistoryVersion,
  type PersonaProjection,
  type PersonaScope,
  type PersonaSeed,
  type StyleFeature,
} from '@/services/persona'

const props = defineProps<{
  chat: ChatDetail
  open: boolean
}>()

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'turn-override', payload: {
    agentId: string
    customerId: string
    sessionId: string
    seedId: string
    instructions: string[]
  }): void
}>()

const projection = ref<PersonaProjection | null>(null)
const seeds = ref<PersonaSeed[]>([])
const selectedSeedId = ref('')
const compareIds = ref<string[]>([])
const compareSeeds = ref<PersonaSeed[]>([])
const scope = ref<PersonaScope>('contact')
const history = ref<PersonaHistoryVersion[]>([])
const guidelines = ref<Array<Record<string, unknown>>>([])
const features = ref<StyleFeature[]>([])
const featureDrafts = ref<Record<string, { condition: string; action: string }>>({})
const busy = ref(false)
const statusText = ref('')
const errorCode = ref('')

const baseText = ref('')
const importJson = ref('')
const importProvenance = ref('')
const importConsent = ref(false)
const styleTitle = ref('')
const styleText = ref('')
const styleProvenance = ref('')
const styleConsent = ref(false)
const existingKnowledgeId = ref('')
const styleSourceKind = ref('authorized-chat')

const activeSeed = computed(() => seeds.value.find(seed => seed.seed_id === selectedSeedId.value) || null)
const visibleIdentity = computed(() =>
  activeSeed.value?.identity_facts || projection.value?.identity_facts || {},
)
const visibleStyle = computed(() =>
  activeSeed.value?.style_traits || projection.value?.style_traits || {},
)
const visibleRelationship = computed(() =>
  activeSeed.value?.relationship_rules || projection.value?.relationship_rules || {},
)

const formatRecord = (value: Record<string, unknown> | Record<string, string>) =>
  Object.entries(value)
    .filter(([, item]) => item !== null && item !== undefined && String(item).trim())
    .map(([key, item]) => ({ key, value: String(item) }))

const safeFailure = (code: string) => {
  errorCode.value = code
  statusText.value = ''
}

const load = async () => {
  if (!props.open) return
  busy.value = true
  errorCode.value = ''
  try {
    const [nextProjection, nextSeeds, nextHistory, nextGuidelines] = await Promise.all([
      personaService.projection(props.chat.agent.id, props.chat.customer.id, props.chat.session_id),
      personaService.seeds(props.chat.agent.id),
      personaService.history(props.chat.agent.id),
      personaService.guidelines(props.chat.agent.id),
    ])
    projection.value = nextProjection
    seeds.value = nextSeeds
    history.value = nextHistory
    guidelines.value = nextGuidelines
    baseText.value = nextProjection.base_persona.join('\n')
    if (!selectedSeedId.value && nextSeeds.length) selectedSeedId.value = nextSeeds[0].seed_id
  } catch {
    safeFailure('persona_load_unavailable')
  } finally {
    busy.value = false
  }
}

const saveBase = async () => {
  const instructions = baseText.value
    .split('\n')
    .map(item => item.trim())
    .filter(Boolean)
  if (!instructions.length) {
    safeFailure('base_persona_required')
    return
  }
  busy.value = true
  try {
    await personaService.updateBase(props.chat.agent.id, instructions)
    statusText.value = '基础人格已写入 Agent.instructions，并进入版本历史。'
    await load()
  } catch {
    safeFailure('base_persona_update_unavailable')
  } finally {
    busy.value = false
  }
}

const importSeed = async () => {
  errorCode.value = ''
  let card: Record<string, unknown>
  try {
    card = JSON.parse(importJson.value)
  } catch {
    safeFailure('character_card_json_invalid')
    return
  }
  if (!importConsent.value || !importProvenance.value.trim()) {
    safeFailure('provenance_and_consent_required')
    return
  }
  busy.value = true
  try {
    const seed = await personaService.importSeed(
      props.chat.agent.id,
      card,
      importProvenance.value.trim(),
      importConsent.value,
    )
    statusText.value = '人格种子已导入；尚未改变当前人格。'
    importJson.value = ''
    importProvenance.value = ''
    importConsent.value = false
    await load()
    selectedSeedId.value = seed.seed_id
  } catch {
    safeFailure('persona_seed_import_unavailable')
  } finally {
    busy.value = false
  }
}

const toggleCompare = (seedId: string) => {
  const exists = compareIds.value.includes(seedId)
  if (exists) {
    compareIds.value = compareIds.value.filter(item => item !== seedId)
    return
  }
  if (compareIds.value.length >= 3) return
  compareIds.value = [...compareIds.value, seedId]
}

const compare = async () => {
  if (compareIds.value.length < 2) {
    safeFailure('select_two_or_three_personas_to_compare')
    return
  }
  busy.value = true
  try {
    const response = await personaService.compare(props.chat.agent.id, compareIds.value)
    compareSeeds.value = response.seeds
    statusText.value = '比较结果已按身份、风格、关系规则分栏。'
  } catch {
    safeFailure('persona_compare_unavailable')
  } finally {
    busy.value = false
  }
}

const selectSeed = async () => {
  if (!selectedSeedId.value) {
    safeFailure('persona_seed_required')
    return
  }
  busy.value = true
  errorCode.value = ''
  try {
    const response = await personaService.select(props.chat.agent.id, {
      seed_id: selectedSeedId.value,
      scope: scope.value,
      customer_id: scope.value === 'contact' ? props.chat.customer.id : undefined,
      session_id: scope.value === 'conversation' ? props.chat.session_id : undefined,
    })
    if (response.scope === 'turn') {
      emit('turn-override', {
        agentId: props.chat.agent.id,
        customerId: props.chat.customer.id,
        sessionId: props.chat.session_id,
        seedId: response.seed_id,
        instructions: response.instructions,
      })
      statusText.value = '仅本轮人格已交给 Reply Brain public seam；未写入数据库。'
    } else {
      statusText.value = '人格范围已更新：' + response.scope
      await load()
    }
  } catch {
    safeFailure('persona_selection_unavailable')
  } finally {
    busy.value = false
  }
}

const clearCurrentScope = async () => {
  if (scope.value !== 'contact' && scope.value !== 'conversation') return
  busy.value = true
  try {
    await personaService.clearScope(props.chat.agent.id, {
      scope: scope.value,
      customer_id: scope.value === 'contact' ? props.chat.customer.id : undefined,
      session_id: scope.value === 'conversation' ? props.chat.session_id : undefined,
    })
    statusText.value = '范围覆盖已清除，恢复上一级人格。'
    await load()
  } catch {
    safeFailure('persona_scope_clear_unavailable')
  } finally {
    busy.value = false
  }
}

const addStyleEvidence = async () => {
  if (!styleConsent.value || !styleProvenance.value.trim()) {
    safeFailure('style_provenance_and_consent_required')
    return
  }
  busy.value = true
  try {
    await personaService.addStyleText(props.chat.agent.id, {
      title: styleTitle.value,
      content: styleText.value,
      provenance: styleProvenance.value.trim(),
      consent: styleConsent.value,
      source_kind: styleSourceKind.value,
    })
    statusText.value = '素材已显式标记为风格学习证据；不会自动修改人格。'
    styleTitle.value = ''
    styleText.value = ''
  } catch {
    safeFailure('style_evidence_add_unavailable')
  } finally {
    busy.value = false
  }
}

const markExistingKnowledge = async () => {
  const knowledgeId = Number(existingKnowledgeId.value)
  if (!Number.isInteger(knowledgeId) || knowledgeId <= 0) {
    safeFailure('knowledge_id_invalid')
    return
  }
  if (!styleConsent.value || !styleProvenance.value.trim()) {
    safeFailure('style_provenance_and_consent_required')
    return
  }
  busy.value = true
  try {
    await personaService.markStyleSource(props.chat.agent.id, knowledgeId, {
      provenance: styleProvenance.value.trim(),
      consent: styleConsent.value,
      source_kind: 'authorized-web',
    })
    statusText.value = '现有 Knowledge 已显式加入 Style Corpus。'
  } catch {
    safeFailure('style_source_mark_unavailable')
  } finally {
    busy.value = false
  }
}

const extractStyle = async () => {
  busy.value = true
  errorCode.value = ''
  try {
    const response = await personaService.extractStyle(props.chat.agent.id)
    features.value = response.features
    featureDrafts.value = Object.fromEntries(
      response.features.map(feature => [
        feature.feature,
        {
          condition: 'MATCH_ALWAYS',
          action: 'Style trait (' + feature.feature + '): ' + feature.value,
        },
      ]),
    )
    statusText.value = '已生成可解释风格特征；仍需逐条审核后才成为 guideline。'
  } catch {
    safeFailure('style_extraction_unavailable')
  } finally {
    busy.value = false
  }
}

const reviewFeature = async (feature: StyleFeature, decision: 'adopt' | 'edit' | 'reject') => {
  const draft = featureDrafts.value[feature.feature] || {
    condition: 'MATCH_ALWAYS',
    action: 'Style trait (' + feature.feature + '): ' + feature.value,
  }
  busy.value = true
  try {
    await personaService.reviewGuideline(props.chat.agent.id, {
      decision,
      condition: draft.condition,
      action: draft.action,
      confidence: feature.confidence,
      evidence_ids: feature.evidence_ids,
      provenance: feature.provenance.join(' | '),
    })
    statusText.value = decision === 'reject'
      ? '该特征已拒绝，不会进入 guideline。'
      : '已保存为用户审核过的 behavioral guideline。'
    guidelines.value = await personaService.guidelines(props.chat.agent.id)
    if (decision !== 'edit') {
      features.value = features.value.filter(item => item !== feature)
    }
  } catch {
    safeFailure('guideline_review_unavailable')
  } finally {
    busy.value = false
  }
}

const rollback = async (transactionId: number) => {
  if (!window.confirm('恢复这个 Agent.instructions 历史版本？')) return
  busy.value = true
  try {
    await personaService.rollback(props.chat.agent.id, transactionId)
    statusText.value = '人格历史已回滚；回滚本身也会形成可审计的新版本。'
    await load()
  } catch {
    safeFailure('persona_rollback_unavailable')
  } finally {
    busy.value = false
  }
}

watch(
  () => [props.open, props.chat.session_id] as const,
  ([open]) => {
    if (!open) return
    selectedSeedId.value = ''
    compareIds.value = []
    compareSeeds.value = []
    features.value = []
    void load()
  },
  { immediate: true },
)
</script>

<template>
  <div
    v-if="open"
    class="yance-persona-studio-backdrop"
    data-yance-persona-studio
    @click.self="emit('close')"
  >
    <section class="yance-persona-studio" role="dialog" aria-modal="true" aria-label="人格工作室">
      <header>
        <div>
          <strong>人格工作室</strong>
          <small>Agent.instructions 是当前基础人格真值；Knowledge 只提供显式证据与种子。</small>
        </div>
        <button type="button" aria-label="关闭人格工作室" @click="emit('close')">×</button>
      </header>

      <div class="yance-persona-studio__body">
        <section data-yance-persona-current>
          <h3>当前人格</h3>
          <div class="semantic-grid">
            <article data-persona-section="identity">
              <strong>身份事实</strong>
              <dl>
                <template v-for="item in formatRecord(visibleIdentity)" :key="item.key">
                  <dt>{{ item.key }}</dt><dd>{{ item.value }}</dd>
                </template>
              </dl>
              <p v-if="!formatRecord(visibleIdentity).length">当前基础人格没有结构化身份种子。</p>
            </article>
            <article data-persona-section="style">
              <strong>风格特征</strong>
              <dl>
                <template v-for="item in formatRecord(visibleStyle)" :key="item.key">
                  <dt>{{ item.key }}</dt><dd>{{ item.value }}</dd>
                </template>
              </dl>
              <p v-if="!formatRecord(visibleStyle).length">尚无结构化风格 seed；可从 Style Corpus 提取。</p>
            </article>
            <article data-persona-section="relationship">
              <strong>关系范围规则</strong>
              <dl>
                <template v-for="item in formatRecord(visibleRelationship)" :key="item.key">
                  <dt>{{ item.key }}</dt><dd>{{ item.value }}</dd>
                </template>
              </dl>
              <p v-if="!formatRecord(visibleRelationship).length">未设置 seed 级关系规则。</p>
            </article>
          </div>
          <label>
            基础人格 / Agent.instructions
            <textarea v-model="baseText" rows="5" data-yance-base-persona />
          </label>
          <button type="button" :disabled="busy" data-yance-save-base-persona @click="saveBase">
            保存基础人格
          </button>
        </section>

        <section data-yance-persona-seed-library>
          <h3>Persona Seed Library</h3>
          <p>支持 Character Card V2；V3 仅保守读取 V2 稳定字段。导入不会自动选择。</p>
          <div class="seed-import">
            <textarea
              v-model="importJson"
              rows="5"
              placeholder="粘贴 Character Card JSON"
              data-yance-character-card-json
            />
            <input v-model="importProvenance" placeholder="来源 / provenance" data-yance-seed-provenance />
            <label><input v-model="importConsent" type="checkbox" data-yance-seed-consent /> 我确认有权使用该素材</label>
            <button type="button" :disabled="busy" data-yance-import-seed @click="importSeed">导入种子</button>
          </div>

          <div v-if="seeds.length" class="seed-list">
            <label v-for="seed in seeds" :key="seed.seed_id" class="seed-row">
              <input v-model="selectedSeedId" type="radio" :value="seed.seed_id" />
              <span>
                <strong>{{ seed.name }}</strong>
                <small>{{ seed.format }} · {{ seed.provenance }}</small>
              </span>
              <input
                type="checkbox"
                :checked="compareIds.includes(seed.seed_id)"
                aria-label="加入人格比较"
                @change="toggleCompare(seed.seed_id)"
              />
            </label>
          </div>

          <div class="scope-row">
            <select v-model="scope" data-yance-persona-scope>
              <option value="global">全局</option>
              <option value="contact">仅此联系人</option>
              <option value="conversation">仅此会话</option>
              <option value="turn">仅本轮</option>
            </select>
            <button type="button" :disabled="busy || !selectedSeedId" data-yance-select-persona @click="selectSeed">
              选择人格
            </button>
            <button
              v-if="scope === 'contact' || scope === 'conversation'"
              type="button"
              :disabled="busy"
              data-yance-clear-persona-scope
              @click="clearCurrentScope"
            >
              清除覆盖
            </button>
            <button type="button" :disabled="busy || compareIds.length < 2" data-yance-compare-persona @click="compare">
              比较 2–3 个
            </button>
          </div>

          <div v-if="compareSeeds.length" class="compare-grid" data-yance-persona-comparison>
            <article v-for="seed in compareSeeds" :key="seed.seed_id">
              <strong>{{ seed.name }}</strong>
              <p><b>身份</b> {{ JSON.stringify(seed.identity_facts) }}</p>
              <p><b>风格</b> {{ JSON.stringify(seed.style_traits) }}</p>
              <p><b>关系</b> {{ JSON.stringify(seed.relationship_rules) }}</p>
            </article>
          </div>
        </section>

        <section data-yance-style-corpus>
          <h3>Style Corpus</h3>
          <p>只有显式勾选授权的网页/聊天素材才进入风格学习；普通 Knowledge 永远保持普通知识。</p>
          <input v-model="styleTitle" placeholder="素材标题" data-yance-style-title />
          <textarea v-model="styleText" rows="5" placeholder="粘贴已授权聊天/文本素材" data-yance-style-text />
          <input v-model="styleProvenance" placeholder="来源 / provenance" data-yance-style-provenance />
          <select v-model="styleSourceKind" data-yance-style-source-kind>
            <option value="authorized-chat">已授权聊天</option>
            <option value="authorized-public">公开素材</option>
            <option value="authorized-writing">用户提供写作样本</option>
          </select>
          <label><input v-model="styleConsent" type="checkbox" data-yance-style-consent /> 明确作为风格学习素材</label>
          <button type="button" :disabled="busy" data-yance-add-style-evidence @click="addStyleEvidence">
            加入 Style Corpus
          </button>

          <div class="inline-row">
            <input v-model="existingKnowledgeId" placeholder="现有 Knowledge ID" data-yance-style-knowledge-id />
            <button type="button" :disabled="busy" data-yance-mark-style-source @click="markExistingKnowledge">
              把现有 Knowledge 显式标为风格素材
            </button>
            <button type="button" :disabled="busy" data-yance-extract-style @click="extractStyle">
              提取风格特征
            </button>
          </div>

          <article
            v-for="feature in features"
            :key="feature.feature"
            class="feature-card"
            data-yance-style-feature
          >
            <div>
              <strong>{{ feature.feature }}</strong>
              <small>confidence {{ feature.confidence.toFixed(2) }} · {{ feature.evidence_ids.join(', ') }}</small>
            </div>
            <p>{{ feature.value }}</p>
            <input
              v-model="featureDrafts[feature.feature].condition"
              aria-label="guideline condition"
              data-yance-guideline-condition
            />
            <textarea
              v-model="featureDrafts[feature.feature].action"
              rows="2"
              aria-label="guideline action"
              data-yance-guideline-action
            />
            <div class="inline-row">
              <button type="button" @click="reviewFeature(feature, 'adopt')">采纳</button>
              <button type="button" @click="reviewFeature(feature, 'edit')">按编辑稿采纳</button>
              <button type="button" @click="reviewFeature(feature, 'reject')">拒绝</button>
            </div>
          </article>
        </section>

        <section data-yance-reviewed-guidelines>
          <h3>Reviewed behavioral guidelines</h3>
          <p>条件由 rule-engine 匹配，动作仅在命中时进入现有 ChatAgent / Reply Brain 上下文。</p>
          <ul>
            <li v-for="item in guidelines" :key="String(item.guideline_id)">
              <strong>{{ item.action }}</strong>
              <small>{{ item.condition }} · confidence {{ item.confidence }} · {{ item.provenance }}</small>
            </li>
          </ul>
        </section>

        <section data-yance-persona-history>
          <h3>人格历史 / Rollback</h3>
          <ul>
            <li v-for="version in history" :key="version.transaction_id">
              <span>#{{ version.transaction_id }} · {{ version.instructions.length }} 条 instructions</span>
              <button type="button" @click="rollback(version.transaction_id)">回滚</button>
            </li>
          </ul>
        </section>
      </div>

      <footer>
        <span v-if="statusText" data-yance-persona-status>{{ statusText }}</span>
        <span v-if="errorCode" data-yance-persona-error>{{ errorCode }}</span>
        <span v-if="projection" class="owner-note">
          {{ projection.effective_scope }} · {{ projection.owner_contract.history }}
        </span>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.yance-persona-studio-backdrop {
  position: absolute;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, .38);
}
.yance-persona-studio {
  width: min(860px, calc(100% - 24px));
  max-height: calc(100% - 24px);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  border: 1px solid var(--o10);
  border-radius: 14px;
  background: var(--bg);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.yance-persona-studio > header,
.yance-persona-studio > footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--o08);
}
.yance-persona-studio > footer {
  border-top: 1px solid var(--o08);
  border-bottom: 0;
  font-size: 11px;
}
.yance-persona-studio header div {
  display: grid;
  gap: 2px;
}
.yance-persona-studio small,
.yance-persona-studio p,
.yance-persona-studio dd,
.owner-note {
  color: var(--muted);
}
.yance-persona-studio__body {
  overflow: auto;
  padding: 12px 14px;
  display: grid;
  gap: 12px;
}
.yance-persona-studio__body > section {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--o08);
  border-radius: 10px;
  background: var(--o02);
}
.yance-persona-studio h3,
.yance-persona-studio p,
.yance-persona-studio dl,
.yance-persona-studio ul {
  margin: 0;
}
.semantic-grid,
.compare-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.semantic-grid article,
.compare-grid article,
.feature-card {
  display: grid;
  gap: 5px;
  padding: 8px;
  border: 1px solid var(--o08);
  border-radius: 8px;
}
.semantic-grid dl {
  display: grid;
  gap: 4px;
}
.semantic-grid dt {
  font-size: 10px;
  color: var(--text3);
}
.semantic-grid dd {
  margin: 0;
  font-size: 11px;
}
.seed-import,
.seed-list {
  display: grid;
  gap: 6px;
}
.seed-row,
.scope-row,
.inline-row {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.seed-row > span {
  display: grid;
  flex: 1;
}
.yance-persona-studio input,
.yance-persona-studio textarea,
.yance-persona-studio select,
.yance-persona-studio button {
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--o05);
  color: var(--text);
  padding: 6px 8px;
  font: inherit;
}
.yance-persona-studio textarea {
  width: 100%;
  resize: vertical;
}
.yance-persona-studio button {
  cursor: pointer;
}
.yance-persona-studio button:disabled {
  opacity: .45;
  cursor: not-allowed;
}
.feature-card > div:first-child {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.yance-persona-studio ul {
  display: grid;
  gap: 6px;
  padding-left: 18px;
}
.yance-persona-studio li {
  font-size: 11px;
}
.yance-persona-studio li small {
  display: block;
}
[data-yance-persona-error] {
  color: var(--danger, #b42318);
}
@media (max-width: 720px) {
  .semantic-grid,
  .compare-grid {
    grid-template-columns: 1fr;
  }
}
</style>
