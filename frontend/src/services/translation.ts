import api from './api'
import type { YanceTranslationProjection } from '@/yance/semanticTypes'

export type TranslationHealth = {
  owner: string
  state: 'connected' | 'not_configured' | 'needs_attention'
  stylePolicy: string
  errorCode?: string
}

export type TranslationPreview = {
  status: 'success' | 'failed' | 'same_language' | 'stale'
  text?: string
  sourceLanguage?: string
  targetLanguage?: string
  integrity: 'passed' | 'failed'
  integrityFailures?: string[]
  errorCode?: string
  provider?: string
  providerModel?: string
  sourceSha256?: string
  stylePolicy: string
  humanLikeness?: 'preserved' | 'blocked'
}

export const translationService = {
  async health(): Promise<TranslationHealth> {
    const response = await api.get<TranslationHealth>('/translation/health')
    return response.data
  },

  async setContactLanguage(customerId: string, language: string): Promise<{
    customerId: string
    preferredLanguage: string
    effectiveLanguage?: string
  }> {
    const response = await api.put(`/translation/contacts/${customerId}/language`, { language })
    return response.data
  },

  async ensureMessages(messageIds: number[]): Promise<YanceTranslationProjection[]> {
    const response = await api.post<{ translations: YanceTranslationProjection[] }>(
      '/translation/messages/ensure',
      { message_ids: messageIds },
    )
    return response.data.translations
  },

  async recomputeMessage(messageId: number): Promise<YanceTranslationProjection[]> {
    const response = await api.post<{ translations: YanceTranslationProjection[] }>(
      `/translation/messages/${messageId}/recompute`,
    )
    return response.data.translations
  },

  async preview(customerId: string, sessionId: string, text: string): Promise<TranslationPreview> {
    const response = await api.post<TranslationPreview>('/translation/preview', {
      customer_id: customerId,
      session_id: sessionId,
      text,
    })
    return response.data
  },
}
