import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')

describe('native-hosted Yance structural gate', () => {
  it('/yance routes to the native host rather than legacy YanceShellView', () => {
    const router = read('../../router/index.ts')
    expect(router).toContain("component: () => import('@/yance/YanceNativeHostView.vue')")
    expect(router).not.toContain("component: () => import('@/yance/YanceShellView.vue')")
    expect(router).toContain("path: '/conversations'")
    expect(router).toContain("path: '/people'")
  })

  it('preserves DashboardLayout as theme and notification shell owner', () => {
    const dashboard = read('../../layouts/DashboardLayout.vue')
    const view = read('../../views/ConversationsView.vue')
    const host = read('../YanceNativeHostView.vue')
    expect(dashboard).toContain('useTheme')
    expect(dashboard).toContain('NotificationList')
    expect(view).toContain('<DashboardLayout :hideHeader=\"props.layoutHideHeader\">')
    expect(host).toContain(':layout-hide-header=\"false\"')
  })

  it('keeps ConversationChat as the one message renderer and one composer with thin slots', () => {
    const chat = read('../../components/conversations/ConversationChat.vue')
    expect(chat).toContain('v-for="{ row, message } in virtualMessages"')
    expect(chat).toContain(':key="String(row.key)"')
    expect(chat).toContain('v-model="newMessage"')
    expect(chat).toContain('name="message-secondary"')
    expect(chat).toContain('name="conversation-extension"')
    expect(chat).toContain('const adoptDraft')
    expect(chat).toContain('newMessage.value = draft')
  })

  it('passes semantic slots through native Conversation owners instead of cloning them', () => {
    const list = read('../../components/conversations/ConversationsList.vue')
    const view = read('../../views/ConversationsView.vue')
    expect(list).toContain('#message-secondary')
    expect(list).toContain('#conversation-extension')
    expect(view).toContain('#message-secondary')
    expect(view).toContain('#conversation-extension')
  })

  it('does not introduce a second active composer, message renderer, theme system, or modal framework', () => {
    const host = read('../YanceNativeHostView.vue')
    const bilingual = read('../components/YanceBilingualMessageProjection.vue')
    const card = read('../components/YanceReplyBrainCandidateCard.vue')
    const active = host + bilingual + card
    expect(active).not.toMatch(/<textarea|class="yance-composer|v-for=.*formattedMessages/)
    expect(active).not.toMatch(/YanceOverlay|ModalManager|yance-theme|--yance-/)
    expect(host).toContain('ConversationsView')
    expect(host).not.toMatch(/\.yance-top-actions\s*\{[^}]*display:\s*none/s)
  })
})
