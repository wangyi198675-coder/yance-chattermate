import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')

describe('Window 31 Conversation native composition structural gate', () => {
  it('keeps native ConversationChat as the only timeline/composer/send owner', () => {
    const chat = read('../../components/conversations/ConversationChat.vue')
    const host = read('../YanceNativeHostView.vue')
    const candidate = read('../components/YanceReplyBrainCandidateCard.vue')
    const girlfriend = read('../components/YanceGirlfriendBrainNativeComposition.vue')
    const yanceActive = host + candidate + girlfriend

    expect(chat).toContain('v-for="{ row, message } in virtualMessages"')
    expect(chat).toContain(':key="String(row.key)"')
    expect(chat).toContain('v-model="newMessage"')
    expect(chat.match(/<textarea\b/g) || []).toHaveLength(1)
    expect(chat).toContain('class="message-input"')
    expect(chat).not.toMatch(/<input\b[^>]*class="message-input"/)
    expect(chat).toContain('@compositionstart="composerIsComposing = true"')
    expect(chat).toContain('@compositionend="composerIsComposing = false"')
    expect(chat).toContain('@keydown="handleComposerKeydown"')
    expect(chat).not.toContain('@keyup.enter')
    expect(chat).toContain('if (event.shiftKey || composerIsComposing.value || event.isComposing) return')
    expect(chat).toContain('void handleComposerSend()')
    expect(chat).toContain('@click="handleComposerSend"')
    expect(chat).toContain('await handleSendMessageWithAttachments()')
    expect(chat).toContain('const adoptDraft = (draft: string) =>')
    expect(chat).toContain('newMessage.value = draft')

    expect(host).toContain('ConversationsView')
    expect(host).toContain('adoptCandidate(adoptDraft, adoptAttachment, adoptMediaIntent, $event)')
    expect(chat).toContain(':adopt-attachment="adoptComposerAttachment"')
    expect(chat).toContain(':adopt-media-intent="adoptMediaIntent"')
    expect(yanceActive).not.toMatch(/handleSendMessageWithAttachments|\bsendMessage\s*\(/)
    expect(yanceActive).not.toMatch(/v-for=.*formattedMessages/)
    expect(yanceActive).not.toMatch(/class="yance-composer/)
  })

  it('hosts Girlfriend Brain in the native modal primitive rather than a second overlay framework', () => {
    const girlfriend = read('../components/YanceGirlfriendBrainNativeComposition.vue')
    const host = read('../YanceNativeHostView.vue')

    expect(girlfriend).toContain("import BaseModal from '@/components/common/BaseModal.vue'")
    expect(girlfriend).toContain('<BaseModal')
    expect(girlfriend).not.toMatch(/YanceOverlay|ModalManager|position:\s*fixed/)
    expect(host).not.toContain('YanceShellView')
  })

  it('does not add Graphiti, provider APIs, a second store, or persistent runtime state', () => {
    const host = read('../YanceNativeHostView.vue')
    const girlfriend = read('../components/YanceGirlfriendBrainNativeComposition.vue')
    const wiring = read('../capabilityWiring.ts')
    const active = host + girlfriend + wiring

    expect(active).not.toMatch(/Graphiti|ElevenLabs|Runway|OpenAI|Images API/i)
    expect(active).not.toMatch(/localStorage|sessionStorage|indexedDB|defineStore|pinia/i)
  })

  it('projects Voice and Generative Media readiness as qualified-but-runtime-pending', () => {
    const wiring = read('../capabilityWiring.ts')
    const girlfriend = read('../components/YanceGirlfriendBrainNativeComposition.vue')

    expect(wiring).toContain("runtimeState: 'runtime-pending'")
    expect(wiring).toContain('语音暂不可用')
    expect(wiring).toContain('生成图片暂不可用')
    expect(wiring).toContain('生成视频暂不可用')
    expect(girlfriend).toContain('disabled')
    expect(girlfriend).not.toMatch(/fetch\(|axios|\.post\(|\.get\(/)
  })

  it('keeps dormant standalone YanceShellView out of the active route', () => {
    const router = read('../../router/index.ts')
    expect(router).toContain("component: () => import('@/yance/YanceNativeHostView.vue')")
    expect(router).not.toContain("component: () => import('@/yance/YanceShellView.vue')")
  })
})
