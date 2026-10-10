import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (relative: string) =>
  fs.readFileSync(path.resolve(__dirname, relative), 'utf8')

describe('Window89 client send intent bounded gate', () => {
  const files = read('../../composables/useConversationFiles.ts')
  const chat = read('../../composables/useConversationChat.ts')
  const socket = read('../../services/socket.ts')
  const info = read('../../components/conversations/ChatInfoPanel.vue')
  const conversation = read('../../components/conversations/ConversationChat.vue')

  it('creates one browser UUID per explicit composer action and sends it through ACK path', () => {
    expect(files).toContain('const clientSendIntentId = crypto.randomUUID()')
    expect(files).toContain('client_send_intent_id: clientSendIntentId')
    expect(files).toContain("socketService.emitWithPersistenceAck<")
    expect(files).toContain(">('agent_message', payload)")
    expect(files).toContain('ack.client_send_intent_id !== clientSendIntentId')
    expect(files).toContain('localMessage.id = ack.message_id')
  })

  it('retains the exact transport envelope until persistence ACK and reconnect', () => {
    expect(socket).toContain('emitWithPersistenceAck<T = unknown>')
    expect(socket).toContain('pendingPersistenceAcks = new Map')
    expect(socket).toContain('this.replayPendingPersistenceAcks()')
    expect(socket).toContain('const signature = JSON.stringify(envelope)')
    expect(socket).toContain('response?.message_id != null')
    expect(socket).toContain('this.pendingPersistenceAcks.delete(pending.intentId)')
  })

  it('uses exact delivery reconciliation instead of newest-message guessing', () => {
    expect(chat).toContain('candidate.client_send_intent_id === data.client_send_intent_id')
    expect(chat).toContain('candidate.id === data.message_id')
    expect(chat).not.toContain('markLatestAgentMessageUndelivered')
  })

  it('covers both end-chat agent_message entry points with stable intent ACKs', () => {
    expect(chat).toContain('const clientSendIntentId = crypto.randomUUID()')
    expect(chat).toContain("end_chat: true")
    expect(chat).toContain('ack.client_send_intent_id !== clientSendIntentId')

    expect(info).toContain('const clientSendIntentId = crypto.randomUUID()')
    expect(info).toContain("socketService.emitWithPersistenceAck<")
    expect(info).toContain(">('agent_message', {")
    expect(info).toContain('client_send_intent_id: clientSendIntentId')
  })

  it('preserves the one Frozen final-send composer path', () => {
    expect(conversation.match(/<textarea\b/g) || []).toHaveLength(1)
    expect(conversation).not.toMatch(/<input\b[^>]*class="message-input"/)
    expect(conversation).toContain('@compositionstart="composerIsComposing = true"')
    expect(conversation).toContain('@compositionend="composerIsComposing = false"')
    expect(conversation).toContain('@keydown="handleComposerKeydown"')
    expect(conversation).not.toContain('@keyup.enter')
    expect(conversation).toContain('if (event.shiftKey || composerIsComposing.value || event.isComposing) return')
    expect(conversation).toContain('void handleComposerSend()')
    expect(conversation).toContain('@click="handleComposerSend"')
    expect(conversation).toContain('await handleSendMessageWithAttachments()')
    expect(conversation).toContain('data-yance-final-send')
  })
})
