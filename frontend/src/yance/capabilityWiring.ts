import type { YanceCapabilityReadinessProjection } from './semanticTypes'

export type FrozenCapabilityRoute = {
  surface: 'girlfriend' | 'reply'
  action: string
}

export const FROZEN_UI_CAPABILITY_ROUTES = {
  contact: { surface: 'girlfriend', action: 'find_contact' },
  persona: { surface: 'girlfriend', action: 'persona_selection' },
  'reply-mode': { surface: 'reply', action: 'reply_mode_selection' },
  'girlfriend-brain': { surface: 'girlfriend', action: 'open_brain' },
  'model-reasoning': { surface: 'girlfriend', action: 'model_selection' },
  'reply-brain': { surface: 'reply', action: 'candidate_generation' },
  attach: { surface: 'reply', action: 'file_attachment' },
  'send-and-learn': { surface: 'reply', action: 'final_send' },
} as const satisfies Record<string, FrozenCapabilityRoute>

export const FROZEN_SURFACE_NATIVE_ROUTES = {
  home: '/yance/home',
  conversation: '/yance',
  relationship: '/yance/relationship',
  settings: '/yance/settings',
} as const

export const FROZEN_VOICE_MEDIA_UI_READINESS = {
  voice: {
    runtimeState: 'runtime-pending',
    label: '语音暂不可用',
  },
  image: {
    runtimeState: 'runtime-pending',
    label: '生成图片暂不可用',
  },
  video: {
    runtimeState: 'runtime-pending',
    label: '生成视频暂不可用',
  },
} as const satisfies Record<'voice' | 'image' | 'video', YanceCapabilityReadinessProjection>
