<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PersonProfileProjection } from '@/types/people'
import { personProfileAvatarUrl } from '@/utils/personProfile'
import { getInitials } from '@/utils/text'

const props = withDefaults(defineProps<{
  profile?: PersonProfileProjection | null
  displayName?: string | null
  anonymous?: boolean
  size?: number
  alt?: string
}>(), {
  profile: null,
  displayName: '',
  anonymous: false,
  size: 40,
  alt: '',
})

const failedUrl = ref('')

const canonicalAvatarUrl = computed(() => personProfileAvatarUrl(props.profile))
const visibleAvatarUrl = computed(() => {
  const url = canonicalAvatarUrl.value
  return url && failedUrl.value !== url ? url : ''
})
const initials = computed(() => {
  if (props.anonymous) return ''
  return getInitials((props.displayName || '').trim(), '')
})
const fallbackText = computed(() => initials.value || '·')
const isAnonymousFallback = computed(() => !visibleAvatarUrl.value && !initials.value)
const accessibleAlt = computed(() =>
  props.alt || (props.displayName ? props.displayName + ' avatar' : 'Contact avatar')
)

function handleImageError() {
  if (visibleAvatarUrl.value) failedUrl.value = visibleAvatarUrl.value
}
</script>

<template>
  <span
    class="canonical-customer-avatar"
    :class="{ 'is-anonymous-fallback': isAnonymousFallback }"
    :style="{ '--customer-avatar-size': size + 'px' }"
    data-canonical-customer-avatar
  >
    <img
      v-if="visibleAvatarUrl"
      :src="visibleAvatarUrl"
      :alt="accessibleAlt"
      @error="handleImageError"
    />
    <span
      v-else
      class="canonical-customer-avatar__fallback"
      role="img"
      :aria-label="accessibleAlt"
    >{{ fallbackText }}</span>
  </span>
</template>

<style scoped>
.canonical-customer-avatar {
  width: var(--customer-avatar-size);
  height: var(--customer-avatar-size);
  flex: 0 0 var(--customer-avatar-size);
  border-radius: 50%;
  overflow: hidden;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  font-size: calc(var(--customer-avatar-size) * 0.32);
  font-weight: 700;
  line-height: 1;
}
.canonical-customer-avatar.is-anonymous-fallback {
  background: transparent;
  border: 1px dashed var(--border-color);
  color: var(--muted);
}
.canonical-customer-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.canonical-customer-avatar__fallback {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}
</style>
