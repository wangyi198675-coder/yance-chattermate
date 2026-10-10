/*
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

import api from './api'
import type { Conversation, ChatDetail, ChatHistoryCursor, ChatMessagePage, Message, ConversationState, ConversationStatePatch } from '@/types/chat'

interface ChatParams {
  skip?: number
  limit?: number
  agent_id?: string
  status?: 'open' | 'closed' | 'transferred' | string
  inbox_filter?: 'all' | 'unread' | 'followed' | 'favourite' | 'archived'
  user_id?: string
  customer_email?: string
  date_from?: string
  date_to?: string
}

export function messageStableKey(message: Message): string {
  if (message.id != null) return `msg:${message.id}`
  if (message.client_send_intent_id) return `intent:${message.client_send_intent_id}`
  throw new Error('Conversation message is missing canonical or optimistic identity')
}

function compareMessageOrder(left: Message, right: Message): number {
  const leftTime = new Date(left.created_at).getTime()
  const rightTime = new Date(right.created_at).getTime()
  if (leftTime !== rightTime) return leftTime - rightTime

  if (left.id != null && right.id != null) return left.id - right.id
  if (left.id != null) return -1
  if (right.id != null) return 1
  return (left.client_send_intent_id || '').localeCompare(right.client_send_intent_id || '')
}

export function mergeCanonicalMessages(existing: Message[], incoming: Message[]): Message[] {
  const merged: Message[] = []
  const byId = new Map<number, number>()

  const mergeOne = (candidate: Message) => {
    if (candidate.id == null && !candidate.client_send_intent_id) {
      return
    }

    if (candidate.id != null) {
      const sameIdIndex = byId.get(candidate.id)
      if (sameIdIndex != null) {
        const current = merged[sameIdIndex]
        const next: Message = {
          ...current,
          ...candidate,
          attributes: {
            ...(current.attributes || {}),
            ...(candidate.attributes || {}),
          },
        }
        merged[sameIdIndex] = next
        return
      }

      if (candidate.client_send_intent_id) {
        const optimisticIndex = merged.findIndex(current =>
          current.id == null &&
          current.client_send_intent_id === candidate.client_send_intent_id
        )
        if (optimisticIndex !== -1) {
          merged[optimisticIndex] = {
            ...candidate,
            attributes: candidate.attributes
              ? { ...candidate.attributes }
              : undefined,
          }
          byId.set(candidate.id, optimisticIndex)
          return
        }
      }

      const nextIndex = merged.length
      merged.push({ ...candidate })
      byId.set(candidate.id, nextIndex)
      return
    }

    const intentId = candidate.client_send_intent_id
    if (!intentId) {
      return
    }

    const hasCanonicalMatch = merged.some(current =>
      current.id != null &&
      current.client_send_intent_id === intentId
    )
    if (hasCanonicalMatch) {
      return
    }

    merged.push({ ...candidate })
  }

  existing.forEach(mergeOne)
  incoming.forEach(mergeOne)
  return merged.sort(compareMessageOrder)
}

export function newestCanonicalCursor(messages: Message[]): ChatHistoryCursor | null {
  let newest: Message | null = null
  for (const message of messages) {
    if (message.id == null) continue
    if (!newest || compareMessageOrder(newest, message) < 0) {
      newest = message
    }
  }
  return newest && newest.id != null
    ? { created_at: newest.created_at, id: newest.id }
    : null
}

export const chatService = {
  async getRecentChats(params?: ChatParams) {
    // Check if we're in a Shopify context
    const urlParams = new URLSearchParams(window.location.search)
    const hasShopParam = urlParams.has('shop') || urlParams.has('host')
    
    const endpoint = hasShopParam ? '/chats/recent/shopify' : '/chats/recent'
    const response = await api.get(endpoint, { params })
    return response.data as Conversation[]
  },

  async getChatDetail(sessionId: string) {
    // Check if we're in a Shopify context
    const urlParams = new URLSearchParams(window.location.search)
    const hasShopParam = urlParams.has('shop') || urlParams.has('host')
    
    const endpoint = hasShopParam ? `/chats/${sessionId}/shopify` : `/chats/${sessionId}`
    const response = await api.get<ChatDetail>(endpoint)
    return response.data
  },

  async getMessagePage(
    sessionId: string,
    direction: 'older' | 'newer',
    cursor: ChatHistoryCursor,
    limit = 50,
  ): Promise<ChatMessagePage> {
    const response = await api.get<ChatMessagePage>(`/chats/${sessionId}/messages`, {
      params: {
        direction,
        cursor_created_at: cursor.created_at,
        cursor_id: cursor.id,
        limit,
      },
    })
    return response.data
  },

  async updateInboxState(sessionId: string, patch: ConversationStatePatch): Promise<ConversationState> {
    const response = await api.patch<ConversationState>(`/chats/${sessionId}/inbox-state`, patch)
    return response.data
  },

  async takeoverChat(sessionId: string): Promise<void> {
    const response = await api.post(`/sessions/${sessionId}/takeover`)
    return response.data
  },

  /** Stop the AI on this chat and queue it for the team, without claiming it. */
  async routeToHuman(sessionId: string): Promise<ChatDetail> {
    const response = await api.post(`/sessions/${sessionId}/route-to-human`)
    return response.data as ChatDetail
  },

  async reassignChat(sessionId: string, toUserId: string) {
    const response = await api.post(`/sessions/${sessionId}/reassign`, null, { params: { to_user_id: toUserId } })
    return response.data as ChatDetail
  },

  async exportChat(sessionId: string): Promise<Blob> {
    const response = await api.get(`/chats/${sessionId}/export`, { responseType: 'blob' })
    return response.data as Blob
  }
}
