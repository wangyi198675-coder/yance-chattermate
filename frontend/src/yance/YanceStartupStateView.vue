<template>
  <main class="startup-state" role="status" aria-live="polite">
    <section class="startup-state__card">
      <p class="startup-state__eyebrow">Yance</p>
      <h1>Needs attention</h1>
      <p class="startup-state__title">{{ title }}</p>
      <p class="startup-state__detail">{{ detail }}</p>
      <button type="button" class="startup-state__retry" @click="retry">Retry</button>
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
  state.value === 'NETWORK_ERROR' ? 'Network error' : 'Backend unavailable',
)

const detail = computed(() =>
  state.value === 'NETWORK_ERROR'
    ? 'Yance could not reach the local backend. Check the local connection and try again.'
    : 'The local backend is not ready. Your setup has not been reset or marked incomplete.',
)

const retry = () => router.replace('/yance')
</script>

<style scoped>
.startup-state {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--color-background, #f6f7f8);
}
.startup-state__card {
  width: min(440px, 100%);
  padding: 28px;
  border: 1px solid var(--color-border, #e4e7eb);
  border-radius: 16px;
  background: var(--color-background-soft, #fff);
  box-shadow: 0 12px 36px rgb(0 0 0 / 8%);
}
.startup-state__eyebrow {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
h1 { margin: 0; font-size: 24px; }
.startup-state__title { margin: 18px 0 6px; font-weight: 700; }
.startup-state__detail { margin: 0; line-height: 1.5; }
.startup-state__retry {
  margin-top: 22px;
  min-height: 40px;
  padding: 0 18px;
  border: 1px solid currentColor;
  border-radius: 10px;
  background: transparent;
  cursor: pointer;
}
</style>