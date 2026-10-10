<!--
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { toast } from 'vue-sonner'
import channelsService, { type ChannelAccount } from '@/services/channels'
import { agentService } from '@/services/agent'
import type { Agent } from '@/types/agent'
import MessengerPagePicker from './MessengerPagePicker.vue'
import { useMetaSignup } from '@/composables/useMetaSignup'

const props = defineProps<{
  channel: 'whatsapp' | 'messenger' | 'instagram'
  existingAccount?: ChannelAccount | null
  reconnectAccount?: ChannelAccount | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'connected', account: ChannelAccount): void
  (e: 'account-updated', account: ChannelAccount): void
  (e: 'connection-failed', target: { id?: string; externalAccountId?: string }): void
}>()

// Where the credentials are copied from — linked so it's one click, not a
// hostname to retype.
const META_APPS_URL = 'https://developers.facebook.com/apps/'

// Per-channel copy + credential fields. The intro is split around the link
// rather than carrying markup, so it renders as escaped text.
const META_FORMS = {
  whatsapp: {
    title: '连接 WhatsApp Business',
    introBefore: '从 Meta 开发者应用（',
    introAfter: ' → WhatsApp → API 设置）复制电话号码 ID 和永久访问令牌。',
    fields: [
      { key: 'phone_number_id', label: '电话号码 ID', placeholder: '1234567890', secret: false },
      { key: 'access_token', label: '访问令牌', placeholder: 'EAAG…', secret: true },
      { key: 'waba_id', label: 'WhatsApp 商业账号 ID（选填）', optional: true, placeholder: '用于自动订阅 Webhook（选填）', secret: false },
    ],
  },
  messenger: {
    title: '连接 Facebook 专页（Messenger）',
    introBefore: 'From your Meta app (',
    introAfter: ' → Messenger → 设置）为目标 Facebook 专页生成访问令牌。',
    fields: [
      { key: 'page_id', label: 'Facebook 专页 ID', placeholder: '1234567890', secret: false },
      { key: 'page_access_token', label: '专页访问令牌', placeholder: 'EAAG…', secret: true },
    ],
  },
  instagram: {
    title: '连接 Instagram 商业账号',
    introBefore: '手动连接时，请从 ',
    introAfter: ' → Instagram 取得专业账号 ID 与关联专页访问令牌。',
    fields: [
      { key: 'ig_id', label: 'Instagram 账号 ID', placeholder: '17841400000000000', secret: false },
      { key: 'page_access_token', label: '关联专页访问令牌', placeholder: 'EAAG…', secret: true },
    ],
  },
} as const

const form = computed(() => META_FORMS[props.channel])
const values = ref<Record<string, string>>({})
const connecting = ref(false)
const account = ref<ChannelAccount | null>(props.existingAccount ?? null)
const recovering = ref(false)
// Updating the exact native row in Settings must also update the open modal.
watch(() => props.existingAccount, current => {
  if (current) account.value = current
})

const reportMessengerFailure = (target: { id?: string; externalAccountId?: string }) => {
  if (props.channel !== 'messenger') return
  const exact = {
    id: target.id ?? account.value?.id,
    externalAccountId: target.externalAccountId ?? account.value?.external_account_id,
  }
  if (account.value && (
    account.value.id === exact.id || account.value.external_account_id === exact.externalAccountId
  )) account.value = { ...account.value, is_active: false }
  emit('connection-failed', exact)
}

const agents = ref<Agent[]>([])
const selectedAgentId = ref('')
const savingAgent = ref(false)

// The three one-click logins live in their own composable; this component owns
// the manual credentials form and agent assignment.
const {
  signupEnabled,
  signingUp,
  showManualForm,
  signupPages,
  connectingPage,
  copy: signupCopy,
  startSignup,
  onPageSelected,
} = useMetaSignup({
  channel: props.channel,
  existingAccount: props.existingAccount,
  reconnectAccountId: props.reconnectAccount?.id,
  onConnected: (connected) => {
    account.value = connected
    recovering.value = false
    if (props.channel === 'messenger') emit('account-updated', connected)
  },
  onConnectionFailed: reportMessengerFailure,
})

onMounted(async () => {
  try {
    agents.value = await agentService.getOrganizationAgents()
    selectedAgentId.value = String(
      props.existingAccount?.agent_id || props.reconnectAccount?.agent_id || agents.value[0]?.id || '')
  } catch (error) {
    console.error('Error loading agents:', error)
  }
})

const connect = async () => {
  const missing = form.value.fields.filter(f => !('optional' in f && f.optional) && !values.value[f.key]?.trim())
  if (missing.length > 0) {
    toast.error(`请填写：${missing.map(f => f.label).join('、')}`)
    return
  }
  try {
    connecting.value = true
    const payload: any = Object.fromEntries(
      form.value.fields
        .map(f => [f.key, values.value[f.key]?.trim()])
        .filter(([, v]) => v)
    )
    if (props.channel === 'whatsapp') {
      account.value = await channelsService.connectWhatsApp(payload)
    } else if (props.channel === 'messenger') {
      account.value = await channelsService.connectMessenger(payload)
    } else {
      account.value = await channelsService.connectInstagram(payload)
    }
    if (props.channel === 'messenger') {
      if (!account.value.is_active) throw new Error('Facebook 专页订阅尚未确认')
      emit('account-updated', account.value)
    }
    recovering.value = false
    toast.success(`已保存 ${account.value.display_name || form.value.title}，消息收发仍需验证`)
  } catch (error: any) {
    if (props.channel === 'messenger') {
      reportMessengerFailure({ externalAccountId: values.value.page_id?.trim() })
    }
    toast.error(`连接失败：${error?.response?.data?.detail || error?.message || '请检查账号凭据及平台状态'}`)
  } finally {
    connecting.value = false
  }
}

const saveAgent = async () => {
  if (!account.value || !selectedAgentId.value) return
  try {
    savingAgent.value = true
    const updated = await channelsService.setAccountAgent(account.value.id, selectedAgentId.value)
    toast.success('已分配接待助手，外部消息收发仍需单独验证')
    emit('connected', updated)
  } catch (error: any) {
    toast.error(`分配接待助手失败：${error?.response?.data?.detail || '请稍后重试'}`)
  } finally {
    savingAgent.value = false
  }
}
</script>

<template>
  <div class="meta-modal" @click.self="emit('close')">
    <div class="meta-modal-content">
      <div class="meta-modal-header">
        <h3>{{ form.title }}</h3>
        <button type="button" class="meta-close-btn" aria-label="关闭弹窗" @click="emit('close')">×</button>
      </div>

      <!-- Step 1: credentials -->
      <div v-if="!account || (channel === 'messenger' && (!account.is_active || recovering))" class="meta-modal-body">
        <section v-if="channel === 'whatsapp'" class="meta-intro" data-whatsapp-connection-modes aria-label="WhatsApp 连接方式">
          <strong>WhatsApp Business（官方 Cloud API）</strong>：使用 Meta 官方授权或手动填写商业账号凭据。
          <p><strong>个人 WhatsApp（手机扫码）</strong>：尚未通过安全、断线重连和消息收发验收，当前不可用。此处不会生成二维码。</p>
        </section>
        <p v-if="account && channel === 'messenger'" class="meta-intro" data-facebook-recovery-state>
          <strong>{{ account.display_name }}</strong>
          {{ account.is_active ? '请通过 Facebook 企业登录重新授权此专页。' : '需要检查：此专页当前未正常连接，请通过 Facebook 企业登录重新授权。' }}
        </p>
        <!-- Login for Business can grant several accounts at once; the customer
             picks which one this channel answers. -->
        <MessengerPagePicker
          v-if="signupPages.length"
          :pages="signupPages"
          :connecting="connectingPage"
          @select="onPageSelected"
        />

        <!-- One-click signup under ChatterMate's Meta app; the manual form
             remains only on channels whose supported product path allows it. -->
        <div v-else-if="signupEnabled && !showManualForm" class="meta-signup">
          <p class="meta-intro">{{ signupCopy.intro }}</p>
          <button class="meta-btn meta-btn-primary meta-signup-btn" :disabled="signingUp" @click="startSignup">
            <font-awesome-icon v-if="signingUp" icon="fa-solid fa-spinner" spin />
            {{ signingUp ? '正在等待 Meta 授权…' : (account && channel === 'messenger' ? '重新授权 Facebook 专页' : signupCopy.cta) }}
          </button>
          <template v-if="channel !== 'messenger'">
            <button v-if="!reconnectAccount" class="meta-link-btn" @click="showManualForm = true">
              改用手动凭据连接
            </button>
          </template>
        </div>

        <div
          v-else-if="channel === 'messenger'"
          class="meta-signup"
          data-messenger-login-unavailable
        >
          <p class="meta-intro">
            需要配置 Facebook 应用：本机尚未启用 Facebook 企业登录。
            请先完成 Meta 应用配置，再选择专页授权。
          </p>
          <button class="meta-btn meta-btn-secondary" @click="emit('close')">关闭</button>
        </div>

        <template v-else-if="!reconnectAccount">
        <p class="meta-intro">
          {{ form.introBefore }}<a
            :href="META_APPS_URL"
            target="_blank"
            rel="noopener noreferrer"
            class="meta-intro-link"
          >developers.facebook.com</a>{{ form.introAfter }}
        </p>
        <div v-for="field in form.fields" :key="field.key" class="meta-field">
          <label class="meta-label" :for="`meta-${field.key}`">{{ field.label }}</label>
          <input
            :id="`meta-${field.key}`"
            v-model="values[field.key]"
            :type="field.secret ? 'password' : 'text'"
            class="meta-input"
            :placeholder="field.placeholder"
            :name="`meta-${channel}-${field.key}`"
            :autocomplete="field.secret ? 'new-password' : 'off'"
          />
        </div>
        <div class="meta-actions">
          <button class="meta-btn meta-btn-secondary" @click="emit('close')">取消</button>
          <button class="meta-btn meta-btn-primary" :disabled="connecting" @click="connect">
            {{ connecting ? '正在连接…' : '连接' }}
          </button>
        </div>
        </template>
        <p v-else class="meta-intro">当前未配置 Instagram 官方登录，暂时无法重新授权此账号。</p>
      </div>

      <!-- Step 2: route to an agent -->
      <div v-else class="meta-modal-body">
        <p class="meta-intro">
          <strong>{{ account.display_name }}</strong> 已保存授权信息，外部 Webhook 与实时收发仍需验证。
          请选择负责处理消息的 AI 助手：
        </p>
        <label class="meta-label" for="meta-agent">AI 助手</label>
        <select id="meta-agent" v-model="selectedAgentId" class="meta-input">
          <option v-for="agent in agents" :key="String(agent.id)" :value="String(agent.id)">
            {{ agent.display_name || agent.name }}
          </option>
        </select>
        <div class="meta-actions">
          <button v-if="channel === 'messenger'" class="meta-btn meta-btn-secondary" @click="recovering = true">重新授权专页</button>
          <button class="meta-btn meta-btn-secondary" @click="emit('connected', account)">稍后再设置</button>
          <button class="meta-btn meta-btn-primary" :disabled="savingAgent || !selectedAgentId" @click="saveAgent">
            {{ savingAgent ? '正在保存…' : '分配助手' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.meta-modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.meta-modal-content {
  background: var(--background-color);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg, 12px);
  width: min(460px, calc(100vw - 32px));
  max-height: calc(100dvh - 32px);
  padding: 24px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.meta-modal-header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.meta-modal-header h3 {
  margin: 0;
  font-family: var(--font-display);
}

.meta-close-btn {
  background: none;
  border: none;
  font-size: 22px;
  cursor: pointer;
  color: var(--muted);
}

.meta-modal-body {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.meta-intro {
  margin: 0 0 16px;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.6;
}

.meta-intro-link {
  /* --accent-ink, not --accent-solid: the latter is the lime fill and stays
     lime in both themes, which is unreadable as text on a light background. */
  color: var(--accent-ink);
  text-decoration: underline;
  font-weight: 600;
}

.meta-intro-link:hover {
  text-decoration: none;
}

.meta-field {
  margin-bottom: 12px;
}

.meta-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}

.meta-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-btn, 8px);
  background: var(--background-soft);
  color: inherit;
  font-size: 14px;
}

.meta-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}

.meta-btn {
  padding: 9px 16px;
  border-radius: var(--radius-btn, 8px);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--background-soft);
  color: inherit;
}

.meta-btn-primary {
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  border-color: transparent;
}

.meta-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.meta-signup {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 12px;
}

.meta-signup-btn {
  width: 100%;
  padding: 12px;
}

.meta-link-btn {
  background: none;
  border: none;
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
  text-decoration: underline;
  padding: 4px;
}

.meta-link-btn:hover {
  color: inherit;
}
</style>
