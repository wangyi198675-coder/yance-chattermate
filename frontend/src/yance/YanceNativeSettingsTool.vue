<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import AISetup from '@/components/ai/AISetup.vue'
import UserSettings from '@/components/user/UserSettings.vue'
import Organizations from '@/components/organization/Organizations.vue'
import { useAISetup } from '@/composables/useAISetup'

const route = useRoute()
const router = useRouter()
const tool = computed(() => String(route.params.tool || ''))
const confirmed = ref(false)
const { isLoading: aiLoading, error: aiError, hasExistingConfig } = useAISetup()
watch(tool, () => { confirmed.value = false })
const names: Record<string, string> = {
  ai: 'AI 与模型管理',
  user: '个人资料与通知',
  organization: '工作区管理',
}
</script>
<template>
  <DashboardLayout>
    <main class="yance-settings-tool" data-yance-native-settings-tool>
      <header>
        <div><p>言策 Yance · 设置</p><h1>{{ names[tool] || '设置' }}</h1></div>
        <button type="button" @click="router.push('/yance/settings')">返回言策设置</button>
      </header>
      <p v-if="!names[tool]" role="alert">此设置入口不存在。</p>
      <template v-else>
        <p class="note">这里复用现有配置与权限，不另存一套账号、模型或个人资料。</p>
        <p v-if="tool==='ai'" class="note ai-truth" data-yance-ai-admin-truth
          :data-ai-config-state="aiLoading ? 'loading' : aiError ? 'error' : hasExistingConfig ? 'stored-not-verified' : 'not-configured'">
          {{ aiLoading ? '正在读取原生 AIConfig…' : aiError ? '原生 AIConfig 无法读取，不能确认模型已配置或可用。' : hasExistingConfig ? '已经保存模型配置；实际 Agno 推理尚未验证，不代表 AI 已连接。' : '原生 AIConfig 尚未配置（HTTP 404 表示不存在配置）；目前不能执行已配置模型的推理。' }}
        </p>
        <section v-if="!confirmed" class="confirm-admin" data-yance-advanced-consent>
          <h2>{{ tool === 'organization' ? '工作区高级设置' : '进入原生高级配置' }}</h2>
          <p v-if="tool === 'organization'">后续是系统级管理表单，可能影响整个工作区，请确认后继续。</p>
          <p v-else>下面将使用现有原生{{ tool === 'ai' ? '模型配置' : '个人资料与通知' }}表单，部分内容暂时为英文。只有你主动确认后才会打开；不会替换言策导航。</p>
          <button type="button" @click="confirmed=true">确认进入高级设置</button>
        </section>
        <template v-else>
          <Organizations v-if="tool === 'organization'" />
          <AISetup v-else-if="tool === 'ai'" />
          <UserSettings v-else-if="tool === 'user'" />
        </template>
      </template>
    </main>
  </DashboardLayout>
</template>
<style scoped>
.yance-settings-tool{width:min(1000px,calc(100% - 28px));margin:auto;padding:24px 0 35px;color:var(--text)}
.yance-settings-tool header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.yance-settings-tool h1{margin:0;font-size:25px}
.yance-settings-tool header p,.note,.confirm-admin p{font-size:12px;color:var(--muted)}
.yance-settings-tool button{background:var(--bg2);border:1px solid var(--o14);color:var(--text);border-radius:8px;padding:9px 12px;cursor:pointer}
.confirm-admin{border:1px solid var(--o14);background:var(--bg2);padding:18px;border-radius:12px}
.confirm-admin h2{font-size:17px}
</style>
