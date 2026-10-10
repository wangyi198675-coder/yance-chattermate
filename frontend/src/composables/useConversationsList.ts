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

import { ref, computed, watch, onMounted, onBeforeUnmount, reactive } from 'vue'
import type { Conversation, ChatDetail, Message } from '@/types/chat'
import { formatDistanceToNow } from 'date-fns'
import { chatService, mergeCanonicalMessages, newestCanonicalCursor } from '@/services/chat'
import { socketService } from '@/services/socket'
import { userService } from '@/services/user'

export function useConversationsList(props: {
  conversations: Conversation[]
  loading: boolean
  error: string
  hasMore?: boolean
  loadingMore?: boolean
}, emit: {
  (e: 'refresh'): void
  (e: 'chatUpdated', data: ChatDetail): void
  (e: 'clearUnread', sessionId: string): void
  (e: 'updateFilter', status: 'open' | 'closed'): void
  (e: 'loadMore'): void
}) {
  const selectedChat = ref<ChatDetail | null>(null)
  const selectedId = ref<string | null>(null)
  const chatLoading = ref<boolean>(false)
  const currentUserId = ref(userService.getUserId())
  const unreadMessages = reactive<Record<string, number>>({})
  let detailRequestGeneration = 0
  let catchUpRequestGeneration = 0

  const catchUpSelectedChat = async (sessionId: string) => {
    const requestGeneration = ++catchUpRequestGeneration
    if (!selectedChat.value || selectedId.value !== sessionId) return

    let cursor = newestCanonicalCursor(selectedChat.value.messages || []) || {
      // Empty-history reconnect still needs an exhaustive forward keyset.
      // Session creation precedes its ChatHistory rows; id=0 is a transient
      // lower-bound sentinel and is never persisted or returned as identity.
      created_at: selectedChat.value.created_at,
      id: 0,
    }

    while (true) {
      const page = await chatService.getMessagePage(sessionId, 'newer', cursor)
      if (
        requestGeneration !== catchUpRequestGeneration ||
        selectedId.value !== sessionId ||
        selectedChat.value?.session_id !== sessionId
      ) {
        return
      }

      const currentMessages = selectedChat.value.messages || []
      const mergedMessages = mergeCanonicalMessages(currentMessages, page.messages)

      selectedChat.value = {
        ...selectedChat.value,
        messages: mergedMessages,
        updated_at: mergedMessages[mergedMessages.length - 1]?.created_at || selectedChat.value.updated_at,
      }

      if (!page.has_more || !page.next_cursor) break
      cursor = page.next_cursor
    }

    if (selectedChat.value?.session_id === sessionId) {
      emit('chatUpdated', selectedChat.value)
    }
  }

  // Socket event handlers. Persisted rows are accepted only with canonical
  // ChatHistory identity; an identity-less event triggers REST catch-up instead
  // of timestamp/content guessing.
  const handleChatReply = (data: {
    message: string
    message_id?: number
    client_send_intent_id?: string
    type: string
    agent_name?: string
    created_at?: string
    timestamp?: string
    session_id: string
    attributes?: any
    attachments?: any[]
  }) => {
    const createdAtRaw = data.created_at || data.timestamp
    if (data.message_id == null || !createdAtRaw) {
      emit('refresh')
      if (selectedId.value === data.session_id) {
        void catchUpSelectedChat(data.session_id)
      }
      return
    }

    if (selectedId.value !== data.session_id) {
      // Socket frames signal a refresh, never an unverified unread increment.
      // The authoritative unread number is derived server-side from ChatHistory
      // and SessionToAgent.last_read_message_id.
      emit('refresh')
      return
    }

    if (!selectedChat.value || selectedChat.value.session_id !== data.session_id) return

    const created_at = new Date(createdAtRaw).toISOString()
    const newMessage: Message = {
      id: data.message_id,
      client_send_intent_id: data.client_send_intent_id,
      message: data.message,
      message_type: data.type === 'agent_message' ? 'agent' : data.type,
      created_at,
      session_id: data.session_id,
      attributes: data.attributes || {},
      agent_name: data.agent_name,
      attachments: data.attachments || undefined,
    }

    if (data.attributes?.shopify_output && typeof data.attributes.shopify_output === 'object') {
      newMessage.message_type = 'product'
      newMessage.shopify_output = data.attributes.shopify_output
    }

    const updatedChat: ChatDetail = {
      ...selectedChat.value,
      messages: mergeCanonicalMessages(selectedChat.value.messages || [], [newMessage]),
      updated_at: created_at,
    }
    selectedChat.value = updatedChat
    emit('chatUpdated', updatedChat)
    // A visible inbound message is read; persist that fact through the same
    // canonical SessionToAgent owner rather than a browser-only counter.
    void chatService.updateInboxState(data.session_id, { mark_read: true })
      .catch((err) => console.error('Failed to persist read state:', err))
      .finally(() => emit('refresh'))
  }

  const handleRoomEvent = (data: unknown) => {
    console.log('Room event received:', data)
    // You can handle join/leave events here if needed
  }

  const setupSocketListeners = () => {

    socketService.on('chat_reply', handleChatReply)
    socketService.on('room_event', handleRoomEvent)
  }

  const cleanupSocketListeners = () => {

    socketService.off('chat_reply', handleChatReply)
    socketService.off('room_event', handleRoomEvent)
  }

  // Handle socket reconnection
  const handleSocketReconnect = () => {
    console.log('Socket reconnected, re-establishing listeners and room')
    cleanupSocketListeners()
    setupSocketListeners()
    
    // Rejoin room if necessary
    const userId = userService.getUserId()
    if (userId) {
      socketService.emit('join_room', { session_id: `user_${userId}` })
    }

    // SocketService invokes pending W89 persistence replay before this callback.
    // Catch up every strict newer page after listener/room recovery so outages
    // longer than one page cannot leave a silent hole.
    const sessionId = selectedId.value
    if (sessionId) {
      void catchUpSelectedChat(sessionId)
    }
    emit('refresh')
  }

 

  /**
   * @param force refetch even when this chat is already open — the Refresh
   *   button. Live socket updates only arrive once a human takes a chat over;
   *   while the AI is answering, this is how an agent pulls the latest turns.
   */
  const loadChatDetail = async (sessionId: string, force = false) => {
    if (!force && selectedChat.value?.session_id === sessionId) return

    const requestGeneration = ++detailRequestGeneration
    catchUpRequestGeneration++
    const optimisticRows = selectedChat.value?.session_id === sessionId
      ? selectedChat.value.messages.filter(
          message => message.id == null && !!message.client_send_intent_id,
        )
      : []

    chatLoading.value = true
    selectedId.value = sessionId
    try {
      const detail = await chatService.getChatDetail(sessionId)
      if (
        requestGeneration !== detailRequestGeneration ||
        selectedId.value !== sessionId
      ) {
        return
      }

      detail.messages = mergeCanonicalMessages(detail.messages || [], optimisticRows)
      selectedChat.value = detail

      try {
        await chatService.updateInboxState(sessionId, { mark_read: true })
        emit('refresh')
      } catch (stateErr) {
        console.error('Failed to persist read state:', stateErr)
      }
    } catch (err) {
      if (requestGeneration === detailRequestGeneration) {
        console.error('Failed to load chat:', err)
      }
    } finally {
      if (requestGeneration === detailRequestGeneration) {
        chatLoading.value = false
      }
    }
  }

  // Watch for conversations changes and load first conversation
  watch(() => props.conversations, (newConversations) => {
    // Project unread counts exclusively from the canonical server query.
    // No optimistic socket counter or browser-side unread authority.
    for (const conversation of newConversations) {
      const count = conversation.unread_count || 0
      if (count > 0) unreadMessages[conversation.session_id] = count
      else delete unreadMessages[conversation.session_id]
    }

    if (newConversations.length > 0 && !selectedId.value) {
      // Use Promise.resolve().then() to break the reactive chain
      // This prevents the recursive update error
      Promise.resolve().then(() => {
        if (!selectedId.value) {
         // loadChatDetail(newConversations[0].session_id)
        }
      })
    }
  }, { immediate: true })

  const formattedConversations = computed(() => {
    // Ensure conversations is an array before mapping
    if (!Array.isArray(props.conversations)) {
      return []
    }
    
    return props.conversations.map(conv => ({
      ...conv,
      timeAgo: formatDistanceToNow(new Date(conv.updated_at), { addSuffix: true }),
      message_type: conv.attributes?.message_type || 'text',
      shopify_output: conv.attributes?.shopify_output
    }))
  })

  // Connect to socket and setup listeners on mount
  onMounted(() => {
    console.log('Connecting to socket')
    socketService.connect()
    setupSocketListeners()
    socketService.onReconnect(handleSocketReconnect)
    
    // Join user-specific room
    const userId = userService.getUserId()
    if (userId) {
      socketService.emit('join_room', { session_id: `user_${userId}` })
    }
  })

  // Cleanup on unmount
  onBeforeUnmount(() => {
    console.log('Disconnecting from socket')
    const userId = userService.getUserId()
    if (userId) {
      socketService.emit('leave_room', { session_id: `user_${userId}` })
    }
    cleanupSocketListeners()
    socketService.offReconnect(handleSocketReconnect)
  })

  // Refresh the canonical unread projection after any external read action.
  const clearUnread = (_sessionId: string) => {
    emit('refresh')
  }

  return {
    selectedChat,
    selectedId,
    chatLoading,
    formattedConversations,
    loadChatDetail,
    unreadMessages,
    clearUnread
  }
} 