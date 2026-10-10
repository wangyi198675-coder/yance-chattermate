import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import type { Message } from '@/types/chat'
import {
  mergeCanonicalMessages,
  messageStableKey,
  newestCanonicalCursor,
} from '@/services/chat'

const read = (relative: string) =>
  fs.readFileSync(path.resolve(__dirname, relative), 'utf8')

const message = (
  id: number | undefined,
  created_at: string,
  client_send_intent_id?: string,
): Message => ({
  id,
  client_send_intent_id,
  session_id: 'session-1',
  message: id == null ? 'optimistic' : `message-${id}`,
  message_type: 'agent',
  created_at,
})

describe('Window151 large-history pagination and virtualization', () => {
  it('keeps an existing canonical row authoritative over an incoming same-intent optimistic row', () => {
    const canonical: Message = {
      ...message(51, '2026-10-07T08:00:01.000Z', 'intent-reverse'),
      message: 'persisted canonical',
      attachments: [{
        id: 501,
        filename: 'canonical.png',
        file_url: '/api/v1/files/download/canonical.png',
        content_type: 'image/png',
        file_size: 501,
      }],
      attributes: {
        delivery_status: 'sent',
        projection: 'canonical',
      },
    }
    const optimistic: Message = {
      ...message(undefined, '2026-10-07T08:00:00.000Z', 'intent-reverse'),
      message: 'temporary optimistic',
      attachments: [{
        id: -1,
        filename: 'temporary.png',
        file_url: 'blob:temporary',
        content_type: 'image/png',
        file_size: 1,
      }],
      attributes: {
        delivery_status: 'pending',
        projection: 'optimistic',
      },
    }

    const merged = mergeCanonicalMessages([canonical], [optimistic])

    expect(merged).toHaveLength(1)
    expect(merged[0].id).toBe(51)
    expect(merged[0].message).toBe('persisted canonical')
    expect(merged[0].attachments).toEqual(canonical.attachments)
    expect(merged[0].attributes).toEqual(canonical.attributes)
  })

  it('reconciles an existing optimistic row to an incoming canonical row with canonical fields winning', () => {
    const optimistic: Message = {
      ...message(undefined, '2026-10-07T08:10:00.000Z', 'intent-forward'),
      message: 'temporary optimistic',
      attachments: [{
        id: -2,
        filename: 'temporary-audio.webm',
        file_url: 'blob:temporary-audio',
        content_type: 'audio/webm',
        file_size: 2,
      }],
      attributes: {
        delivery_status: 'pending',
        projection: 'optimistic',
      },
    }
    const canonical: Message = {
      ...message(52, '2026-10-07T08:10:01.000Z', 'intent-forward'),
      message: 'persisted canonical ack',
      attachments: [{
        id: 502,
        filename: 'canonical-audio.webm',
        file_url: '/api/v1/files/download/canonical-audio.webm',
        content_type: 'audio/webm',
        file_size: 502,
      }],
      attributes: {
        delivery_status: 'sent',
        projection: 'canonical',
      },
    }

    const merged = mergeCanonicalMessages([optimistic], [canonical])

    expect(merged).toHaveLength(1)
    expect(merged[0].id).toBe(52)
    expect(merged[0].message).toBe('persisted canonical ack')
    expect(merged[0].attachments).toEqual(canonical.attachments)
    expect(merged[0].attributes).toEqual(canonical.attributes)
    expect(messageStableKey(merged[0])).toBe('msg:52')
  })

  it('keeps distinct canonical ids even when they share client_send_intent_id', () => {
    const first = message(61, '2026-10-07T08:20:00.000Z', 'shared-intent')
    const second = message(62, '2026-10-07T08:20:01.000Z', 'shared-intent')

    const merged = mergeCanonicalMessages([first], [second])

    expect(merged).toHaveLength(2)
    expect(merged.map(row => row.id)).toEqual([61, 62])
  })

  it('preserves normal same-canonical-id update semantics', () => {
    const first: Message = {
      ...message(71, '2026-10-07T08:30:00.000Z', 'intent-same-id'),
      message: 'canonical before update',
      attachments: [{
        id: 701,
        filename: 'before.txt',
        file_url: '/api/v1/files/download/before.txt',
        content_type: 'text/plain',
        file_size: 7,
      }],
      attributes: {
        delivery_status: 'sending',
        retained: 'yes',
      },
    }
    const update: Message = {
      ...message(71, '2026-10-07T08:30:00.000Z', 'intent-same-id'),
      message: 'canonical after update',
      attachments: [{
        id: 702,
        filename: 'after.txt',
        file_url: '/api/v1/files/download/after.txt',
        content_type: 'text/plain',
        file_size: 8,
      }],
      attributes: {
        delivery_status: 'sent',
      },
    }

    const merged = mergeCanonicalMessages([first], [update])

    expect(merged).toHaveLength(1)
    expect(merged[0].id).toBe(71)
    expect(merged[0].message).toBe('canonical after update')
    expect(merged[0].attachments).toEqual(update.attachments)
    expect(merged[0].attributes).toEqual({
      delivery_status: 'sent',
      retained: 'yes',
    })
  })

  it('keeps the ordinary Window151 optimistic-to-ACK/socket path deduped once', () => {
    const optimistic = message(undefined, '2026-10-07T08:40:00.000Z', 'intent-a')
    const canonical = message(42, '2026-10-07T08:40:01.000Z', 'intent-a')
    const duplicateCanonical = {
      ...canonical,
      attributes: { delivery_status: 'sent' },
    }

    const merged = mergeCanonicalMessages(
      [optimistic],
      [canonical, duplicateCanonical],
    )

    expect(merged).toHaveLength(1)
    expect(merged[0].id).toBe(42)
    expect(merged[0].client_send_intent_id).toBe('intent-a')
    expect(merged[0].attributes?.delivery_status).toBe('sent')
    expect(messageStableKey(merged[0])).toBe('msg:42')
  })

  it('keeps same-timestamp canonical rows in id order and ignores optimistic rows for catch-up cursor', () => {
    const timestamp = '2026-10-07T08:30:00.000Z'
    const merged = mergeCanonicalMessages(
      [message(11, timestamp), message(undefined, '2026-10-07T09:00:00.000Z', 'intent-b')],
      [message(9, timestamp), message(10, timestamp), message(11, timestamp)],
    )

    expect(merged.filter(row => row.id != null).map(row => row.id)).toEqual([9, 10, 11])
    expect(newestCanonicalCursor(merged)).toEqual({
      created_at: timestamp,
      id: 11,
    })
  })

  it('wires TanStack Vue Virtual as the only timeline virtualizer with stable identity and pin-aware following', () => {
    const conversation = read('../../components/conversations/ConversationChat.vue')
    const pkg = JSON.parse(read('../../../package.json'))

    expect(pkg.dependencies['@tanstack/vue-virtual']).toBe('3.13.39')
    expect(conversation).toContain(
      "import { observeElementRect, useVirtualizer } from '@tanstack/vue-virtual'",
    )
    expect(conversation).toContain('observeElementRect(instance, (rect) => {')
    expect(conversation).toContain("anchorTo: 'end' as const")
    expect(conversation).toContain('followOnAppend: true')
    expect(conversation).toContain('getItemKey: getVirtualMessageKey')
    expect(conversation).toContain('messageStableKey(formattedMessages.value[index])')
    expect(conversation).toContain('rowVirtualizer.value.measureElement(element)')
    expect(conversation).toContain("rowVirtualizer.value.scrollToEnd({ behavior: 'auto' })")
    expect(conversation).toContain('rowVirtualizer.value.isAtEnd(160)')
    expect(conversation).toContain('v-for="{ row, message } in virtualMessages"')
    expect(conversation).toContain(':key="String(row.key)"')
    expect(conversation).not.toContain(':key="idx"')
    expect(conversation).not.toContain('v-for="(message, idx) in formattedMessages"')
  })

  it('loads older pages and reconnect catch-up by strict canonical page APIs without timestamp identity guessing', () => {
    const list = read('../../composables/useConversationsList.ts')
    const chat = read('../../composables/useConversationChat.ts')
    const service = read('../../services/chat.ts')

    expect(service).toContain("direction: 'older' | 'newer'")
    expect(service).toContain('cursor_created_at: cursor.created_at')
    expect(service).toContain('cursor_id: cursor.id')

    expect(chat).toContain("chatService.getMessagePage(sessionId, 'older', cursor)")
    expect(chat).toContain('historyPageGeneration')
    expect(chat).toContain('messages: mergeCanonicalMessages(chat.value.messages || [], page.messages)')
    expect(chat).not.toContain("watch(() => chat.value.messages, (messages) =>")
    expect(chat).not.toContain('chat.value.updated_at = timestamp\n    scrollToBottom()')

    expect(list).toContain('const catchUpSelectedChat = async (sessionId: string) =>')
    expect(list).toContain("chatService.getMessagePage(sessionId, 'newer', cursor)")
    expect(list).toContain('while (true)')
    expect(list).toContain('created_at: selectedChat.value.created_at')
    expect(list).toContain('id: 0')
    expect(list).toContain('mergeCanonicalMessages(currentMessages, page.messages)')
    expect(list).not.toContain('processedCanonicalMessageIds')
    expect(list).not.toContain('const messageKey = `${data.session_id}-${data.created_at}`')
  })

  it('preserves the reviewed single Timeline, Composer and FileUpload owners', () => {
    const conversation = read('../../components/conversations/ConversationChat.vue')

    expect(conversation.match(/class="messages"/g) || []).toHaveLength(1)
    expect(conversation.match(/<textarea\b/g) || []).toHaveLength(1)
    expect(conversation.match(/<FileUpload\b/g) || []).toHaveLength(1)
    expect(conversation.match(/await handleSendMessageWithAttachments\(\)/g) || []).toHaveLength(1)
  })
})
