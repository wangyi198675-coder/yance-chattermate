import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { describe, expect, it } from 'vitest'

const source = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const host = source('../YanceNativeHostView.vue')
const conversationsView = source('../../views/ConversationsView.vue')
const conversationsList = source('../../components/conversations/ConversationsList.vue')
const conversationChat = source('../../components/conversations/ConversationChat.vue')
const replyCandidate = source('../components/YanceReplyBrainCandidateCard.vue')
const girlfriend = source('../components/YanceGirlfriendBrainNativeComposition.vue')

const count = (haystack: string, needle: string) => haystack.split(needle).length - 1

describe('Window 44 Frozen master / Conversation / Reply / Girlfriend closure', () => {
  it('hosts the active product in one bounded 920x620 native composition without fake window controls', () => {
    expect(host).toContain('data-yance-master-frame')
    expect(host).toContain('data-frame-width="920"')
    expect(host).toContain('data-frame-height="620"')
    expect(host).toContain('width: min(920px, 100vw)')
    expect(host).toContain('height: min(620px, 100dvh)')
    expect(host).toContain('data-native-window-control="hold"')
    expect(host).toContain('<ConversationsView')
    expect(host).toContain('frozen-yance')
    expect(host).not.toContain('YanceShellView')
    expect(host).not.toMatch(/data-yance-(?:minimize|maximize|window-close)/)
    expect(conversationsView).toContain('<DashboardLayout :hideHeader="props.layoutHideHeader">')
    expect(conversationsView).toContain('v-if="!props.frozenYance" class="page-header"')
  })

  it('keeps one native contact rail, one timeline, one composer and one final send authority', () => {
    expect(count(conversationsList, 'class="conversations-sidebar"')).toBe(1)
    expect(conversationsList).toContain('data-yance-contact-rail')
    expect(conversationsList).toContain('v-for="conv in railFilteredConversations"')

    expect(count(conversationChat, 'v-for="{ row, message } in virtualMessages"')).toBe(1)
    expect(count(conversationChat, ':key="String(row.key)"')).toBe(1)
    expect(count(conversationChat, 'v-model="newMessage"')).toBe(1)
    expect(count(conversationChat, '@click="handleComposerSend"')).toBe(1)
    expect(conversationChat.match(/<textarea\b/g) || []).toHaveLength(1)
    expect(conversationChat).not.toMatch(/<input\b[^>]*class="message-input"/)
    expect(count(conversationChat, '@compositionstart="composerIsComposing = true"')).toBe(1)
    expect(count(conversationChat, '@compositionend="composerIsComposing = false"')).toBe(1)
    expect(count(conversationChat, '@keydown="handleComposerKeydown"')).toBe(1)
    expect(count(conversationChat, '@keyup.enter')).toBe(0)
    expect(count(conversationChat, 'if (event.shiftKey || composerIsComposing.value || event.isComposing) return')).toBe(1)
    expect(count(conversationChat, 'const handleComposerSend = async () =>')).toBe(1)
    expect(count(conversationChat, 'void handleComposerSend()')).toBe(1)
    expect(count(conversationChat, 'await handleSendMessageWithAttachments()')).toBe(1)
    expect(count(conversationChat, '<FileUpload')).toBe(1)

    expect(host).not.toContain('sendMessage(')
    expect(host).not.toContain('v-model="newMessage"')
    expect(host).not.toContain('v-for="(message, idx) in formattedMessages"')
  })

  it('provides all/unread/follow carriers over canonical SessionToAgent state without browser shadow state', () => {
    expect(conversationsList).toContain('data-yance-rail-collapse')
    expect(conversationsList).toContain("railFilter = ref<InboxFilter>('all')")
    expect(conversationsList).toContain('全部')
    expect(conversationsList).toContain('未读')
    expect(conversationsList).toContain('data-yance-follow-filter')
    expect(conversationsList).toContain('data-yance-follow-action')
    expect(conversationsList).toContain('data-yance-archive-action')
    expect(conversationsList).toContain('data-native-state="SessionToAgent.is_followed"')
    expect(conversationsList).toContain('data-native-state="SessionToAgent.is_archived"')
    expect(conversationsList).not.toMatch(/localStorage[^\n]*(?:follow|archive)/i)
  })

  it('preserves Window 34 CustomerAvatar and adds contact/self avatars per Frozen message row', () => {
    expect(conversationsList).toContain("import CustomerAvatar from '@/components/people/CustomerAvatar.vue'")
    expect(conversationChat).toContain("import CustomerAvatar from '@/components/people/CustomerAvatar.vue'")
    expect(conversationChat).toContain('data-yance-message-avatar="contact"')
    expect(conversationChat).toContain('data-yance-message-avatar="self"')
    expect(conversationChat).toContain('currentUserAvatarSrc')
    expect(conversationChat).toContain('myAvatarUrl(currentUserAvatarVersion)')
  })

  it('keeps unavailable Model fail-closed while Persona and Reply Mode use their admitted owners', () => {
    const personaAt = host.indexOf('data-yance-persona-control')
    expect(personaAt).toBeGreaterThan(-1)
    expect(host.slice(personaAt, personaAt + 240)).toContain('data-owner-state="ready"')
    expect(host.slice(personaAt, personaAt + 240)).not.toContain('disabled')
    const modelAt = host.indexOf('data-yance-model-reasoning-control')
    expect(modelAt).toBeGreaterThan(-1)
    expect(host.slice(modelAt, modelAt + 240)).toContain('disabled')
    expect(host.slice(modelAt, modelAt + 240)).toContain('data-owner-state="unavailable"')

    const replyModeAt = host.indexOf('data-yance-reply-mode-control')
    expect(replyModeAt).toBeGreaterThan(-1)
    expect(host.slice(replyModeAt, replyModeAt + 320)).toContain('data-owner-state="ready"')
    expect(host.slice(replyModeAt, replyModeAt + 320)).toContain('HUMAN / AI_ASSIST / AI_AUTO')
    expect(host.slice(replyModeAt, replyModeAt + 320)).not.toContain('disabled')
  })

  it('composes Frozen Composer carriers around the existing native draft/file/send path', () => {
    expect(conversationChat).toContain('data-yance-frozen-composer')
    expect(conversationChat).toContain("frozenYance ? '发送消息…'")
    expect(conversationChat).toContain('真人打字·自然 ▾')
    expect(conversationChat).toContain('发送并学习 ▾')
    expect(conversationChat).toContain('data-yance-typing-policy')
    expect(conversationChat).toContain('data-yance-send-policy')
    expect(conversationChat).toContain('data-yance-translation-preview')
    expect(conversationChat).toContain('data-integrity-state="fail-closed"')
  })

  it('keeps Reply Brain adoption-only and exposes bounded secondary/media states without fake live candidates', () => {
    expect(host).toContain('slice(0, 5)')
    expect(host).toContain('slice(0, expanded.value ? 5 : 3)')
    expect(host).toContain('data-yance-reply-secondary-state')
    expect(host).toContain('data-yance-recompute')
    expect(host).toContain('暂无合适建议')
    expect(host).toContain('当前不建议发送')
    expect(host).toContain('建议稍后再回复')
    expect(host).toContain('建议切换发送平台')
    expect(replyCandidate).toContain('data-yance-modality-preview')
    expect(replyCandidate).toContain("props.candidate.type === 'text'")
    expect(replyCandidate).not.toContain('sendMessage(')
  })

  it('keeps Girlfriend Brain on BaseModal and projects orchestration/receipt/permission states without a second store', () => {
    expect(girlfriend).toContain("import BaseModal from '@/components/common/BaseModal.vue'")
    expect(girlfriend).toContain('<BaseModal')
    expect(girlfriend).toContain('data-yance-girlfriend-orchestration')
    expect(girlfriend).toContain('data-yance-girlfriend-owner-receipt')
    expect(girlfriend).toContain('data-yance-girlfriend-permission')
    expect(girlfriend).toContain('data-yance-girlfriend-why')
    expect(girlfriend).toContain('data-yance-model-delegation')
    expect(girlfriend).not.toContain('position: fixed')
    expect(girlfriend).not.toMatch(/(?:createPinia|defineStore|localStorage|sessionStorage)/)
  })
})
