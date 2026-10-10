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
import { ref, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import channelsService, { type ChannelAccount } from '@/services/channels'
import { agentService } from '@/services/agent'
import type { Agent } from '@/types/agent'

const props = defineProps<{
  existingAccount?: ChannelAccount | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'connected', account: ChannelAccount): void
}>()

const botToken = ref('')
const connecting = ref(false)
const account = ref<ChannelAccount | null>(props.existingAccount ?? null)

const agents = ref<Agent[]>([])
const selectedAgentId = ref('')
const savingAgent = ref(false)

onMounted(async () => {
  try {
    agents.value = await agentService.getOrganizationAgents()
    selectedAgentId.value = String(
      props.existingAccount?.agent_id || agents.value[0]?.id || '')
  } catch (error) {
    console.error('Error loading agents:', error)
  }
})

const connect = async () => {
  if (!botToken.value.trim()) {
    toast.error('请填写 @BotFather 提供的机器人令牌')
    return
  }
  try {
    connecting.value = true
    account.value = await channelsService.connectTelegram(botToken.value.trim())
    toast.success(`已保存 ${account.value.display_name || 'Telegram 机器人'}，收发仍需验证`)
  } catch (error: any) {
    const detail = `Telegram 机器人连接失败：${error?.response?.data?.detail || '请检查令牌'}`
    toast.error(detail)
  } finally {
    connecting.value = false
  }
}

const saveAgent = async () => {
  if (!account.value || !selectedAgentId.value) return
  try {
    savingAgent.value = true
    const updated = await channelsService.setAccountAgent(account.value.id, selectedAgentId.value)
    toast.success('已保存接待助手，Telegram 收发仍需验证')
    emit('connected', updated)
  } catch (error: any) {
    toast.error(`分配接待助手失败：${error?.response?.data?.detail || '请重试'}`)
  } finally {
    savingAgent.value = false
  }
}
</script>

<template>
  <div class="tg-modal" @click.self="emit('close')">
    <div class="tg-modal-content">
      <div class="tg-modal-header">
        <h3>连接 Telegram 机器人</h3>
        <button type="button" class="tg-close-btn" aria-label="关闭弹窗" @click="emit('close')">×</button>
      </div>

      <!-- Step 1: bot token -->
      <div v-if="!account" class="tg-modal-body">
        <ol class="tg-steps">
          <li>在 Telegram 中打开 <strong>@BotFather</strong>，发送 <code>/newbot</code></li>
          <li>按提示为机器人命名</li>
          <li>复制机器人令牌并填写在下方</li>
        </ol>
        <label class="tg-label" for="tg-token">机器人令牌</label>
        <input
          id="tg-token"
          v-model="botToken"
          type="password"
          class="tg-input"
          placeholder="123456789:AAF…"
          name="tg-bot-token"
          autocomplete="new-password"
          @keyup.enter="connect"
        />
        <div class="tg-actions">
          <button class="tg-btn tg-btn-secondary" @click="emit('close')">取消</button>
          <button class="tg-btn tg-btn-primary" :disabled="connecting" @click="connect">
            {{ connecting ? '正在连接…' : '连接' }}
          </button>
        </div>
      </div>

      <!-- Step 2: route to an agent -->
      <div v-else class="tg-modal-body">
        <p class="tg-connected-note">
          <strong>{{ account.display_name }}</strong> 已保存连接信息，收发仍需验证。请选择负责回复消息的 AI 助手：
        </p>
        <label class="tg-label" for="tg-agent">AI 助手</label>
        <select id="tg-agent" v-model="selectedAgentId" class="tg-input">
          <option v-for="agent in agents" :key="String(agent.id)" :value="String(agent.id)">
            {{ agent.display_name || agent.name }}
          </option>
        </select>
        <div class="tg-actions">
          <button class="tg-btn tg-btn-secondary" @click="emit('connected', account)">稍后再设置</button>
          <button class="tg-btn tg-btn-primary" :disabled="savingAgent || !selectedAgentId" @click="saveAgent">
            {{ savingAgent ? '正在保存…' : '分配助手' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tg-modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.tg-modal-content {
  background: var(--background-color);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg, 12px);
  width: min(440px, calc(100vw - 32px));
  max-height: calc(100dvh - 32px);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  padding: 24px;
}

.tg-modal-header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.tg-modal-header h3 {
  margin: 0;
  font-family: var(--font-display);
}

.tg-close-btn {
  background: none;
  border: none;
  font-size: 22px;
  cursor: pointer;
  color: var(--muted);
}

.tg-modal-body {min-height:0;overflow-y:auto;overscroll-behavior:contain}

.tg-steps {
  margin: 0 0 16px;
  padding-left: 20px;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.7;
}

.tg-steps code {
  font-family: var(--font-mono);
  background: var(--background-mute);
  padding: 1px 5px;
  border-radius: 4px;
}

.tg-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}

.tg-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-btn, 8px);
  background: var(--background-soft);
  color: inherit;
  font-size: 14px;
}

.tg-connected-note {
  margin: 0 0 16px;
  color: var(--muted);
  font-size: 14px;
}

.tg-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}

.tg-btn {
  padding: 9px 16px;
  border-radius: var(--radius-btn, 8px);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--background-soft);
  color: inherit;
}

.tg-btn-primary {
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  border-color: transparent;
}

.tg-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
