<script setup lang="ts">
import { ref } from 'vue'
import { FROZEN_UI_CAPABILITY_ROUTES, type FrozenCapabilityRoute } from './capabilityWiring'

const props = withDefaults(defineProps<{ initialSurface?: 'home' | 'conversation' | 'relationship' | 'settings' }>(), { initialSurface: 'conversation' })
const emit = defineEmits<{
  (event: 'open-control', control: 'contact' | 'persona' | 'reply-mode' | 'model-reasoning'): void
  (event: 'window-action', action: 'minimize' | 'maximize' | 'close'): void
  (event: 'composer-action', action: 'attach' | 'typing-style' | 'send-and-learn'): void
  (event: 'settings-section', section: string): void
  (event: 'capability-route', route: FrozenCapabilityRoute): void
}>()
const activeSurface = ref(props.initialSurface)
const replyBrainOpen = ref(false)
const girlfriendBrainOpen = ref(false)
const contactFilter = ref<'all' | 'unread' | 'followed'>('all')

type HeaderControl = 'contact' | 'persona' | 'reply-mode' | 'model-reasoning'
type ComposerAction = 'attach' | 'typing-style' | 'send-and-learn'

const openControl = (control: HeaderControl) => {
  emit('open-control', control)
  const route = control === 'contact'
    ? FROZEN_UI_CAPABILITY_ROUTES.contact
    : control === 'model-reasoning'
      ? FROZEN_UI_CAPABILITY_ROUTES['model-reasoning']
      : undefined
  if (route) emit('capability-route', route)
}

const toggleReplyBrain = () => {
  replyBrainOpen.value = !replyBrainOpen.value
  if (replyBrainOpen.value) emit('capability-route', FROZEN_UI_CAPABILITY_ROUTES['reply-brain'])
}

const composerAction = (action: ComposerAction) => {
  emit('composer-action', action)
  if (action === 'attach') emit('capability-route', FROZEN_UI_CAPABILITY_ROUTES.attach)
  if (action === 'send-and-learn') emit('capability-route', FROZEN_UI_CAPABILITY_ROUTES['send-and-learn'])
}
</script>

<template>
  <div class="yance-app" data-yance="shell">
    <section v-if="activeSurface === 'home'" class="yance-surface yance-home" data-yance="home">
      <header class="yance-home__header"><div><span class="yance-kicker">言策</span><h1>今天</h1></div><button type="button" @click="activeSurface='settings'">设置</button></header>
      <div class="yance-home__grid">
        <button type="button" class="yance-card" @click="activeSurface='conversation'"><strong>继续对话</strong><span>进入联系人与时间线</span></button>
        <button type="button" class="yance-card" @click="activeSurface='relationship'"><strong>关系世界</strong><span>查看人物与关系信息</span></button>
      </div>
    </section>
    <section v-else-if="activeSurface === 'relationship'" class="yance-surface" data-yance="relationship-world">
      <header class="yance-simple-header"><button type="button" @click="activeSurface='home'">返回首页</button><h1>关系世界</h1><button type="button" @click="activeSurface='settings'">设置</button></header>
      <div class="yance-empty-state">选择联系人后查看已确认事实、推断与来源。</div>
    </section>
    <section v-else-if="activeSurface === 'settings'" class="yance-surface" data-yance="settings">
      <header class="yance-simple-header"><button type="button" @click="activeSurface='home'">返回首页</button><h1>设置</h1><button type="button" @click="activeSurface='conversation'">对话</button></header>
      <div class="yance-settings-grid">
        <button type="button" @click="emit('settings-section','accounts-platforms')">账号与平台</button><button type="button" @click="emit('settings-section','ai-models')">AI 与模型</button>
        <button type="button" @click="emit('settings-section','persona-learning')">人格与学习</button><button type="button" @click="emit('settings-section','memory-relationship')">记忆与关系</button>
        <button type="button" @click="emit('settings-section','translation-language')">翻译与语言</button><button type="button" @click="emit('settings-section','voice-media')">语音与媒体</button>
        <button type="button" @click="emit('settings-section','automation-permissions')">自动化与权限</button><button type="button" @click="emit('settings-section','privacy-backup')">隐私与备份</button>
        <button type="button" @click="emit('settings-section','update-diagnostics')">更新与诊断</button><button type="button" @click="emit('settings-section','appearance-notifications')">外观与通知</button>
      </div>
    </section>
    <section v-else class="yance-conversation" data-yance-surface="conversation">
      <header class="yance-conversation__header" data-yance="conversation-header">
        <button type="button" @click="activeSurface='home'">返回首页</button>
        <button type="button" @click="openControl('contact')">联系人</button>
        <button type="button" @click="openControl('persona')">人格</button>
        <button type="button" @click="openControl('reply-mode')">回复模式</button>
        <button type="button" @click="openControl('model-reasoning')">模型/推理</button>
        <button type="button" data-yance="girlfriend-toggle" :aria-pressed="girlfriendBrainOpen" @click="girlfriendBrainOpen=!girlfriendBrainOpen">闺蜜大脑</button>
        <div class="yance-window-controls" aria-label="Windows controls"><button type="button" aria-label="最小化" @click="emit('window-action','minimize')">－</button><button type="button" aria-label="最大化" @click="emit('window-action','maximize')">□</button><button type="button" aria-label="关闭" @click="emit('window-action','close')">×</button></div>
      </header>
      <div class="yance-conversation__body">
        <aside class="yance-contact-rail" data-yance="contact-rail">
          <div class="yance-contact-tabs"><button type="button" :aria-pressed="contactFilter==='all'" @click="contactFilter='all'">全部</button><button type="button" :aria-pressed="contactFilter==='unread'" @click="contactFilter='unread'">未读</button><button type="button" :aria-pressed="contactFilter==='followed'" @click="contactFilter='followed'">关注</button></div>
          <div class="yance-contact-empty">暂无联系人投影</div>
        </aside>
        <main class="yance-timeline" data-yance="timeline">
          <div class="yance-timeline-empty">选择联系人以查看时间线</div>
          <div class="yance-reply-brain"><button type="button" data-yance="reply-brain-toggle" :aria-expanded="replyBrainOpen" @click="toggleReplyBrain">回复建议</button><section v-if="replyBrainOpen" data-yance="reply-brain-panel" class="yance-reply-panel">当前没有可用建议。</section></div>
          <footer class="yance-composer" data-yance="composer"><button type="button" aria-label="添加附件" @click="composerAction('attach')">+</button><label class="yance-sr-only" for="yance-message">发送消息…</label><textarea id="yance-message" rows="1" placeholder="发送消息…" /><button type="button" @click="composerAction('typing-style')">真人打字·自然 ▾</button><button type="button" @click="composerAction('send-and-learn')">发送并学习 ▾</button></footer>
        </main>
      </div>
      <div v-if="girlfriendBrainOpen" class="yance-overlay" data-yance="girlfriend-overlay" role="dialog" aria-modal="true"><div class="yance-overlay__panel"><header><strong>闺蜜大脑</strong><button type="button" @click="girlfriendBrainOpen=false">关闭</button></header><p>说出你想处理的人或事情。</p><textarea rows="4" aria-label="闺蜜大脑指令" /></div></div>
    </section>
  </div>
</template>
<style src="./yance.css"></style>