<template>
  <main class="startup-state" role="status" aria-live="polite" data-yance-startup-state>
    <section class="startup-state__card">
      <p class="startup-state__eyebrow">言策 · YANCE</p>
      <h1>连接需要检查</h1>
      <p class="startup-state__title">{{ title }}</p>
      <p class="startup-state__detail">{{ detail }}</p>
      <button type="button" class="startup-state__retry" @click="retry">重新检查连接</button>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { SetupFailureState } from '@/services/organization'

const route = useRoute()
const router = useRouter()

const state = computed<SetupFailureState>(() =>
  route.query.state === 'NETWORK_ERROR' ? 'NETWORK_ERROR' : 'BACKEND_UNAVAILABLE',
)

const title = computed(() =>
  state.value === 'NETWORK_ERROR' ? '无法连接本地服务' : '本地服务尚未就绪',
)

const detail = computed(() =>
  state.value === 'NETWORK_ERROR'
    ? '言策尚未连接到本机 ChatterMate 后端。请检查本地服务是否已启动，然后重试。'
    : '本地后端暂未就绪。现有账号与数据不会因此被重置。',
)

const retry = () => router.replace('/yance')
</script>

<style scoped>
.startup-state {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px;
  color: #f4eaf3;
  font-family: 'Microsoft YaHei', Inter, sans-serif;
  background: radial-gradient(ellipse at top left, #443045 0%, transparent 48%), #10121d;
}
.startup-state__card {
  width: min(440px, 100%);
  padding: 28px;
  border: 1px solid #7a5b82;
  border-radius: 16px;
  background: #231e2c;
  color: #f4eaf3;
  box-shadow: 0 12px 36px rgb(0 0 0 / 34%);
}
.startup-state__eyebrow {
  margin: 0 0 8px;
  color: #d4b7e5;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
h1 { margin: 0; font-size: 24px; color: #f4d9a7; }
.startup-state__title { margin: 18px 0 6px; font-weight: 700; }
.startup-state__detail { margin: 0; line-height: 1.6; color: #e3d5e6; }
.startup-state__retry {
  margin-top: 22px;
  min-height: 40px;
  padding: 0 18px;
  border: 1px solid #ba96cc;
  border-radius: 10px;
  background: #533864;
  color: #f4eaf3;
  cursor: pointer;
}
.startup-state__retry:hover { background: #664676; }
.startup-state__retry:focus-visible { outline: 3px solid #f4d9a7; outline-offset: 3px; }
</style>
