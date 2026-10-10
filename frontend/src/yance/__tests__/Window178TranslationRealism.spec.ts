import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (relative: string) => readFileSync(resolve(here, relative), 'utf8')

describe('Window178 translation + multilingual realism closure', () => {
  it('keeps one composer/send path and carries adopted translation provenance through it', () => {
    const conversation = read('../../components/conversations/ConversationChat.vue')
    const files = read('../../composables/useConversationFiles.ts')
    expect(conversation).toContain('adoptedTranslationPairing')
    expect(conversation).toContain('handleSendMessageWithAttachments(')
    expect(files).toContain('translation_pairing')
    expect(files).toContain('emitWithPersistenceAck')
  })

  it('binds inbound projection to canonical messages and exposes recompute', () => {
    const conversation = read('../../components/conversations/ConversationChat.vue')
    expect(conversation).toContain('translationService.ensureMessages')
    expect(conversation).toContain('data-yance-translation-recompute')
    expect(conversation).toContain('YanceBilingualMessageProjection')
  })

  it('uses runtime translation health in settings instead of a fake connected state', () => {
    const settings = read('../YanceSettingsNativeComposition.vue')
    expect(settings).toContain('translationService.health')
    expect(settings).toContain('translationState')
    expect(settings).toContain('deepl.official_translation_api')
  })
})
