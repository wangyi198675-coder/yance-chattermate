import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { useConversationFiles } from '@/composables/useConversationFiles'

describe('Window139 private media URLs', () => {
  function subject() {
    const currentChat = ref({
      session_id: 'session-1',
      messages: [],
      updated_at: '',
    } as any)
    return useConversationFiles(
      currentChat,
      ref(''),
      ref(true),
      () => undefined,
    )
  }

  it('routes legacy local inline media through the authenticated download owner', () => {
    const { getImageUrl } = subject()

    const url = getImageUrl(
      '/uploads/chat_attachments/bab82aab-d095-46f8-bf16-da638671bcf4/photo.jpg',
    )

    expect(url).toContain(
      '/api/v1/files/download/chat_attachments/bab82aab-d095-46f8-bf16-da638671bcf4/photo.jpg',
    )
    expect(url).not.toContain('/api/v1/uploads/chat_attachments/')
  })

  it('preserves authenticated local routes, blob previews, and absolute S3 URLs', () => {
    const { getImageUrl } = subject()
    const authenticated =
      '/api/v1/files/download/chat_attachments/bab82aab-d095-46f8-bf16-da638671bcf4/photo.jpg'

    expect(getImageUrl(authenticated)).toContain(authenticated)
    expect(getImageUrl('blob:window139-preview')).toBe('blob:window139-preview')
    expect(getImageUrl('https://bucket.example/private/photo.jpg')).toBe(
      'https://bucket.example/private/photo.jpg',
    )
  })
})
