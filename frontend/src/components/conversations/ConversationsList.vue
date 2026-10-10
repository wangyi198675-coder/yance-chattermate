<!--
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
-->

<script setup lang="ts">
import type { Conversation, ChatDetail } from '@/types/chat'
import ConversationChat from '@/components/conversations/ConversationChat.vue'
import ChannelBadge from '@/components/common/ChannelBadge.vue'
import HandlerBadge from '@/components/conversations/HandlerBadge.vue'
import CustomerAvatar from '@/components/people/CustomerAvatar.vue'
import { useConversationsList } from '@/composables/useConversationsList'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { chatHandler } from '@/utils/chatState'
import { personProfileLine } from '@/utils/personProfile'
import { userService } from '@/services/user'
import { chatService } from '@/services/chat'
import { Menu, MenuButton, MenuItems, MenuItem } from '@headlessui/vue'
import { computed, ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'

const props = defineProps<{
  conversations: Conversation[]
  loading: boolean
  error: string
  statusFilter: 'open' | 'closed'
  hasMore: boolean
  loadingMore: boolean
  showChatInfo?: boolean
  initialSessionId?: string | null
  mobilePane?: 'list' | 'chat'
  frozenYance?: boolean
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'chatUpdated', data: ChatDetail): void
  (e: 'chatSelected', data: ChatDetail): void
  (e: 'clearUnread', sessionId: string): void
  (e: 'updateFilter', status: 'open' | 'closed'): void
  (e: 'updateInboxFilter', filter: 'all' | 'unread' | 'followed' | 'favourite' | 'archived'): void
  (e: 'loadMore'): void
  (e: 'select', sessionId: string): void
  (e: 'back'): void
  (e: 'info'): void
}>()

const { isMobile } = useBreakpoint()
const currentUserId = userService.getUserId()

// The preview used to be prefixed with the AI agent's name unconditionally,
// which read as "the bot said this" even on a chat a colleague had taken over.
const previewPrefix = (conv: Conversation) => {
  const handler = chatHandler(conv, currentUserId)
  return handler.kind === 'human' ? handler.label : conv.agent.name
}

const railProfileLine = (conv: Conversation) =>
  personProfileLine(conv.customer.profile, 'zh-CN')

const {
  selectedChat,
  selectedId,
  chatLoading,
  formattedConversations,
  loadChatDetail,
  unreadMessages,
  clearUnread
} = useConversationsList(props, emit)

// Frozen rail controls project canonical backend state. The browser keeps no
// follow/archive shadow owner.
const railCollapsed = ref(false)
type InboxFilter = 'all' | 'unread' | 'followed' | 'favourite' | 'archived'
const railFilter = ref<InboxFilter>('all')
const setRailFilter = (filter: InboxFilter) => {
  railFilter.value = filter
  // The parent issues a new server-filtered, paginated canonical query.
  emit('updateInboxFilter', filter)
}
const railFilteredConversations = computed(() => {
  if (!props.frozenYance) return formattedConversations.value
  if (railFilter.value === 'archived') {
    return formattedConversations.value.filter(conversation => conversation.archived)
  }
  // Archiving removes a conversation from the active views without changing its
  // native ChatterMate lifecycle status. The archived view permits restoration.
  const active = formattedConversations.value.filter(conversation => !conversation.archived)
  if (railFilter.value === 'followed') return active.filter(conversation => conversation.followed)
  if (railFilter.value === 'favourite') return active.filter(conversation => conversation.favourite)
  if (railFilter.value === 'unread') {
    return active.filter(conversation => Boolean(unreadMessages[conversation.session_id]))
  }
  return active
})

// Enhanced loadChatDetail to also emit chat-selected event
const loadChatDetailWithSelection = async (sessionId: string) => {
  await loadChatDetail(sessionId)
  // Emit the chat-selected event with the loaded chat detail
  if (selectedChat.value) {
    emit('chatSelected', selectedChat.value)
  }
}

// On mobile a tap routes through the URL (?session=) so back navigation works;
// the parent pushes the query, which flows back in via initialSessionId.
const handleConversationClick = (sessionId: string) => {
  if (isMobile.value) {
    emit('select', sessionId)
  } else {
    loadChatDetailWithSelection(sessionId)
  }
}

const stateUpdateError = ref('')
const persistConversationState = async (
  conversation: Conversation,
  patch: { followed?: boolean; favourite?: boolean; archived?: boolean },
) => {
  stateUpdateError.value = ''
  try {
    // The response is the committed SessionToAgent state; no browser-side
    // favourite/archive/follow cache is allowed to become authoritative.
    const state = await chatService.updateInboxState(conversation.session_id, patch)
    if (selectedChat.value?.session_id === conversation.session_id) {
      selectedChat.value = {
        ...selectedChat.value,
        followed: state.followed,
        favourite: state.favourite,
        archived: state.archived,
        last_read_message_id: state.last_read_message_id,
      }
    }
  } catch (error) {
    console.error('Failed to persist conversation state:', error)
    stateUpdateError.value = '操作未保存，请重试'
  } finally {
    emit('refresh')
  }
}

const handleConversationDetails = async (sessionId: string) => {
  if (isMobile.value) {
    emit('select', sessionId)
    await nextTick()
  } else {
    await loadChatDetailWithSelection(sessionId)
  }
  emit('info')
}

const openRowMenuFromContext = (event: MouseEvent, triggerSelector: string) => {
  const row = event.currentTarget as HTMLElement | null
  const trigger = row?.querySelector<HTMLButtonElement>(triggerSelector)
  trigger?.click()
}

// Function to update the selected chat from parent
const updateSelectedChat = (updatedChat: ChatDetail) => {
  console.log('updateSelectedChat', updatedChat)
  if (selectedChat.value && selectedChat.value.session_id === updatedChat.session_id) {
    selectedChat.value = updatedChat
  }
}

// Function to clear the selected chat from parent
const clearSelectedChat = () => {
  selectedChat.value = null
  selectedId.value = null
}

// Expose the function to parent component
defineExpose({
  updateSelectedChat,
  clearSelectedChat
})

// Intersection observer for infinite scrolling
const listContainer = ref<HTMLElement | null>(null)
const loadMoreTrigger = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

// Scroll to top functionality
const showScrollToTop = ref(false)
const scrollThreshold = 300 // Show button after scrolling down 300px

// Handle scroll event to show/hide scroll-to-top button
const handleScroll = () => {
  if (listContainer.value) {
    showScrollToTop.value = listContainer.value.scrollTop > scrollThreshold
  }
}

// Scroll to top function
const scrollToTop = () => {
  if (listContainer.value) {
    listContainer.value.scrollTo({
      top: 0,
      behavior: 'smooth'
    })
  }
}

// Flag to track filter changes
const filterChanged = ref(false)

// Watch for filter changes to set the flag
watch(() => props.statusFilter, () => {
  filterChanged.value = true
})

// Watch for loading state changes to select first conversation after filter change
watch(() => props.loading, (isLoading, prevLoading) => {
  // Only proceed if loading has just completed (was true, now false)
  if (prevLoading === true && isLoading === false && filterChanged.value) {
    // Reset the flag
    filterChanged.value = false

    // When loading completes after filter change, select the first conversation if
    // available (desktop only — on mobile the list pane stays put until a tap)
    if (props.conversations.length > 0 && !isMobile.value) {
      loadChatDetailWithSelection(props.conversations[0].session_id)
    } else {
      // If no conversations available, clear the selected chat
      selectedChat.value = null
      selectedId.value = null
    }
  }
})

// Deep-link: open a specific session directly (from analytics "Sessions Needing
// Attention", mobile ?session= navigation, or a push notification). Fetches the
// chat detail by id, so it works even if the session isn't in the currently
// loaded/filtered list. Reacts to every change so in-app deep-links keep working.
watch(
  () => props.initialSessionId,
  (sessionId) => {
    if (sessionId && sessionId !== selectedId.value) {
      loadChatDetailWithSelection(sessionId)
    }
  },
  { immediate: true }
)

// Setup intersection observer for infinite scrolling
onMounted(() => {
  setupIntersectionObserver()
  
  // Add scroll event listener
  if (listContainer.value) {
    listContainer.value.addEventListener('scroll', handleScroll)
  }
})

// Watch for changes in the loadMoreTrigger ref
watch(loadMoreTrigger, (newValue) => {
  if (newValue && observer) {
    observer.observe(newValue)
  }
})

// Watch for changes in the listContainer ref to add scroll listener
watch(listContainer, (newValue) => {
  if (newValue) {
    newValue.addEventListener('scroll', handleScroll)
  }
})

// Setup intersection observer
const setupIntersectionObserver = () => {
  if (window.IntersectionObserver) {
    // Disconnect previous observer if it exists
    if (observer) {
      observer.disconnect()
    }
    
    observer = new IntersectionObserver((entries) => {
      const entry = entries[0]
      if (entry.isIntersecting && props.hasMore && !props.loadingMore) {
        emit('loadMore')
      }
    }, { threshold: 0.5 })
    
    if (loadMoreTrigger.value) {
      observer.observe(loadMoreTrigger.value)
    }
  }
}

// Cleanup intersection observer and event listeners
onBeforeUnmount(() => {
  if (observer) {
    observer.disconnect()
    observer = null
  }
  
  // Remove scroll event listener
  if (listContainer.value) {
    listContainer.value.removeEventListener('scroll', handleScroll)
  }
})
</script>

<template>
  <div
    class="conversations-container"
    :class="{
      'with-chat-info': showChatInfo,
      'mobile-show-chat': mobilePane === 'chat',
      'rail-collapsed': frozenYance && railCollapsed,
    }"
  >
    <!-- One native sidebar remains the only contact rail. Frozen controls are
         composed into it rather than creating a second rail. -->
    <div
      class="conversations-sidebar"
      :data-yance-contact-rail="frozenYance ? 'native' : undefined"
    >
      <div v-if="frozenYance" class="frozen-rail-controls" data-yance-rail-controls>
        <div class="frozen-rail-heading">
          <strong v-if="!railCollapsed">联系人</strong>
          <button
            type="button"
            class="rail-collapse-btn"
            data-yance-rail-collapse
            :aria-label="railCollapsed ? '展开联系人栏' : '收起联系人栏'"
            :aria-pressed="railCollapsed"
            @click="railCollapsed = !railCollapsed"
          >
            {{ railCollapsed ? '›' : '‹' }}
          </button>
        </div>
        <div v-if="!railCollapsed" class="frozen-rail-tabs" aria-label="联系人筛选">
          <button
            type="button"
            :class="{ active: railFilter === 'all' }"
            :aria-pressed="railFilter === 'all'"
            @click="setRailFilter('all')"
          >
            全部
          </button>
          <button
            type="button"
            :class="{ active: railFilter === 'unread' }"
            :aria-pressed="railFilter === 'unread'"
            @click="setRailFilter('unread')"
          >
            未读
          </button>
          <button
            type="button"
            data-yance-follow-filter
            data-native-state="SessionToAgent.is_followed"
            :class="{ active: railFilter === 'followed' }"
            :aria-pressed="railFilter === 'followed'"
            @click="setRailFilter('followed')"
          >
            关注
          </button>
          <button
            type="button"
            data-yance-favourite-filter
            data-native-state="SessionToAgent.is_favourite"
            :class="{ active: railFilter === 'favourite' }"
            :aria-pressed="railFilter === 'favourite'"
            @click="setRailFilter('favourite')"
          >
            收藏
          </button>
          <button
            type="button"
            data-yance-archive-filter
            data-native-state="SessionToAgent.is_archived"
            :class="{ active: railFilter === 'archived' }"
            :aria-pressed="railFilter === 'archived'"
            @click="setRailFilter('archived')"
          >
            归档
          </button>
        </div>
      </div>

      <!-- ChatterMate status filtering remains available outside the bounded
           Frozen composition. It is not repurposed as follow/archive state. -->
      <div v-if="!frozenYance" class="filter-controls">
        <button 
          class="filter-btn" 
          :class="{ active: statusFilter === 'open' }"
          @click="emit('updateFilter', 'open')"
        >
          Open
        </button>
        <button 
          class="filter-btn" 
          :class="{ active: statusFilter === 'closed' }"
          @click="emit('updateFilter', 'closed')"
        >
          Closed
        </button>
      </div>

      <p v-if="stateUpdateError" class="rail-state-error" role="alert">{{ stateUpdateError }}</p>
      <div v-if="loading && !loadingMore" class="loading-state">
        Loading conversations...
      </div>

      <div v-else-if="error" class="error-state">
        {{ error }}
        <button @click="emit('refresh')" class="refresh-button">Retry</button>
      </div>

      <div v-else-if="railFilteredConversations.length === 0" class="empty-state">
        {{ frozenYance && railFilter === 'unread' ? '暂无未读对话' : frozenYance && railFilter === 'followed' ? '暂无关注对话' : frozenYance && railFilter === 'favourite' ? '暂无收藏对话' : frozenYance && railFilter === 'archived' ? '暂无归档对话' : '暂无对话' }}
      </div>

      <div v-else class="conversations-list" ref="listContainer">
        <div 
          v-for="conv in railFilteredConversations"
          :key="conv.session_id"
          class="conversation-item"
          :class="{ active: selectedId === conv.session_id }"
          role="button"
          tabindex="0"
          :aria-current="selectedId === conv.session_id ? 'true' : undefined"
          @click="handleConversationClick(conv.session_id)"
          @keydown.enter.prevent="handleConversationClick(conv.session_id)"
          @keydown.space.prevent="handleConversationClick(conv.session_id)"
          @contextmenu.prevent="openRowMenuFromContext($event, '[data-yance-contact-menu-button]')"
        >
          <div class="conversation-item-header">
            <CustomerAvatar
              :profile="conv.customer.profile"
              :display-name="conv.customer.full_name || conv.customer.email"
              :size="34"
            />
            <h3>{{ conv.customer.full_name || conv.customer.email }}</h3>
            <ChannelBadge :channel="conv.channel" />
            <span class="timestamp">{{ conv.timeAgo }}</span>
            <Menu
              v-if="frozenYance"
              as="div"
              class="contact-context-menu"
              data-yance-contact-context
              @click.stop
              @keydown.stop
              @contextmenu.stop
            >
              <MenuButton
                type="button"
                class="contact-context-menu__button"
                data-yance-contact-menu-button
                :aria-label="`联系人操作：${conv.customer.full_name || conv.customer.email}`"
              >
                ⋯
              </MenuButton>
              <MenuItems
                class="contact-context-menu__panel"
                data-yance-contact-menu-items
              >
                <MenuItem v-slot="{ active }">
                  <button
                    type="button"
                    :class="{ active }"
                    data-yance-contact-action="open"
                    @click="handleConversationClick(conv.session_id)"
                  >
                    打开
                  </button>
                </MenuItem>
                <MenuItem v-slot="{ active }">
                  <button
                    type="button"
                    :class="{ active }"
                    data-yance-contact-action="details"
                    @click="handleConversationDetails(conv.session_id)"
                  >
                    详情
                  </button>
                </MenuItem>
                <MenuItem v-slot="{ active }">
                  <button
                    type="button"
                    :class="{ active }"
                    data-yance-follow-action
                    data-native-state="SessionToAgent.is_followed"
                    @click="persistConversationState(conv, { followed: !conv.followed })"
                  >
                    {{ conv.followed ? '取消关注' : '关注' }}
                  </button>
                </MenuItem>
                <MenuItem v-slot="{ active }">
                  <button
                    type="button"
                    :class="{ active }"
                    data-yance-favourite-action
                    data-native-state="SessionToAgent.is_favourite"
                    @click="persistConversationState(conv, { favourite: !conv.favourite })"
                  >
                    {{ conv.favourite ? '取消收藏' : '收藏' }}
                  </button>
                </MenuItem>
                <MenuItem v-slot="{ active }">
                  <button
                    type="button"
                    :class="{ active }"
                    data-yance-archive-action
                    data-native-state="SessionToAgent.is_archived"
                    @click="persistConversationState(conv, { archived: !conv.archived })"
                  >
                    {{ conv.archived ? '取消归档' : '归档' }}
                  </button>
                </MenuItem>
              </MenuItems>
            </Menu>
          </div>
          <p
            v-if="frozenYance && railProfileLine(conv)"
            class="contact-profile-line"
            data-yance-contact-profile-line
          >
            {{ railProfileLine(conv) }}
          </p>
          <div class="conversation-preview">
            <span class="agent-name">{{ previewPrefix(conv) }}:</span>
            <!-- Product message preview -->
            <template v-if="conv.message_type === 'product' && conv.shopify_output?.products?.length">
              <p class="last-message product-preview">
                <span class="product-icon">🛍️</span>
                {{ conv.shopify_output.products.length }} product{{ conv.shopify_output.products.length > 1 ? 's' : '' }} shared
              </p>
            </template>
            <!-- Regular message preview -->
            <template v-else>
              <p class="last-message">{{ conv.last_message }}</p>
            </template>
            <slot name="conversation-secondary" :conversation="conv" />
            <div v-if="unreadMessages[conv.session_id]" class="unread-bubble">
              {{ unreadMessages[conv.session_id] }}
            </div>
          </div>
          <div class="message-count">{{ conv.message_count }} messages</div>
          <div class="conversation-footer">
            <div class="conversation-status" :class="conv.status">
              {{ conv.status }}
            </div>
            <HandlerBadge :chat="conv" :current-user-id="currentUserId" />
          </div>
        </div>
        
        <!-- Loading more indicator -->
        <div 
          v-if="hasMore || loadingMore" 
          class="load-more-trigger" 
          ref="loadMoreTrigger"
        >
          <div v-if="loadingMore" class="loading-more">
            <div class="loading-spinner"></div>
            <span>Loading more conversations...</span>
          </div>
          <div v-else-if="hasMore" class="load-more-container">
            <span class="load-more-hint">Scroll down to load more</span>
            <button 
              class="load-more-button"
              @click="emit('loadMore')"
              :disabled="loadingMore"
            >
              Load More
            </button>
          </div>
        </div>
      </div>
      
      <!-- Scroll to top button -->
      <button 
        v-if="showScrollToTop" 
        class="scroll-to-top-btn"
        @click="scrollToTop"
        aria-label="Scroll to top"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 15l-6-6-6 6"/>
        </svg>
      </button>
    </div>

    <!-- Chat view -->
    <div class="chat-view">
      <div v-if="chatLoading" class="loading-state">
        Loading chat...
      </div>
      <ConversationChat
        v-else-if="selectedChat"
        :key="selectedChat.session_id"
        :chat="selectedChat"
        :frozen-yance="frozenYance"
        @refresh="() => {
          // force: this chat is already open, and loadChatDetail skips a session
          // it thinks it has — without it this refetch was a silent no-op.
          selectedChat && loadChatDetail(selectedChat.session_id, true);
          emit('refresh');
        }"
        @chatUpdated="(updated) => {
          // Forward as well as store locally. Taking a chat over from the chat
          // pane changes user_id, and the info panel decides whether to offer
          // 'End Chat' from its own chatInfo prop — which only the parent can
          // update. Without this the button stayed hidden until a refresh.
          selectedChat = updated;
          emit('chatUpdated', updated);
        }"
        @clearUnread="clearUnread"
        @back="emit('back')"
        @info="emit('info')"
      >
        <template #conversation-header-actions="slotProps">
          <slot name="conversation-header-actions" v-bind="slotProps" />
        </template>
        <template #message-secondary="slotProps">
          <slot name="message-secondary" v-bind="slotProps" />
        </template>
        <template #conversation-extension="slotProps">
          <slot name="conversation-extension" v-bind="slotProps" />
        </template>
      </ConversationChat>
    </div>
  </div>
</template>

<style scoped>
.conversations-container {
  display: grid;
  grid-template-columns: 320px 1fr;
  /* Same as the parent grid: without a bounded row the sidebar's height: 100%
     resolves against content, so .conversations-list can never scroll. */
  grid-template-rows: minmax(0, 1fr);
  gap: 0;
  height: 100%;
  width: 100%;
  background: var(--bg);
  color: var(--text);
  position: relative;
}

.conversations-container.with-chat-info {
  grid-template-columns: 320px 1fr;
}

.conversations-sidebar {
  border-right: 1px solid var(--o08);
  background: var(--bg2);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  min-width: 0;
  position: relative;
}

.frozen-rail-controls {
  flex: 0 0 auto;
  border-bottom: 1px solid var(--o07);
  background: var(--bg2);
}

.frozen-rail-heading {
  display: flex;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px 4px 12px;
}

.frozen-rail-heading strong {
  color: var(--text);
  font-size: 12px;
  font-weight: 650;
}

.rail-collapse-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--o10);
  border-radius: 8px;
  background: var(--o04);
  color: var(--text3);
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
}

.frozen-rail-tabs {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 4px;
  padding: 4px 10px 9px;
}

.frozen-rail-tabs button {
  min-width: 0;
  padding: 6px 5px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
}

.rail-state-error {
  padding: 5px 12px;
  color: var(--danger, #b91c1c);
  font-size: 11px;
}

.frozen-rail-tabs button.active {
  background: var(--o10);
  color: var(--text);
  font-weight: 600;
}

.frozen-rail-tabs button:disabled {
  opacity: .42;
  cursor: not-allowed;
}

.rail-unavailable-note {
  grid-column: 1 / -1;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.3;
  padding: 0 4px;
}

.filter-controls {
  display: flex;
  padding: 10px 12px;
  border-bottom: 1px solid var(--o07);
  background: var(--bg2);
  gap: 4px;
}

.filter-btn {
  flex: 1;
  padding: 7px 12px;
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  border-radius: 8px;
}

.filter-btn:hover {
  background: var(--o05);
  color: var(--text);
}

.filter-btn.active {
  background: var(--o10);
  color: var(--text);
  font-weight: 600;
}

.conversations-list {
  overflow-y: auto;
  flex: 1;
  min-height: 0;
  padding: 0;
  margin: 0;
  scrollbar-width: thin; /* For Firefox */
  scrollbar-color: var(--border-color) transparent; /* For Firefox */
}

/* Webkit scrollbar styling */
.conversations-list::-webkit-scrollbar {
  width: 6px;
}

.conversations-list::-webkit-scrollbar-track {
  background: transparent;
}

.conversations-list::-webkit-scrollbar-thumb {
  background-color: var(--border-color);
  border-radius: 3px;
}

/* Status and handler sit on one line and wrap together on a narrow row. */
.conversation-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 4px;
  min-width: 0;
}

.conversation-status {
  font-size: 10px;
  font-family: var(--font-mono);
  letter-spacing: 0.04em;
  padding: 2px 7px;
  border-radius: var(--radius-full);
  text-transform: uppercase;
  display: inline-block;
  font-weight: 600;
}

.conversation-status.open {
  background: rgba(201,242,78,.12);
  color: var(--accent-ink);
}

.conversation-status.closed {
  background: var(--o06);
  color: var(--muted);
}

.conversation-status.transferred {
  background-color: var(--warning-color-soft);
  color: var(--warning-color);
}

.chat-view {
  height: 100%;
  width: 100%;
  overflow: hidden;
  position: relative;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sidebar-header h2 {
  font-size: 14px;
  font-weight: 500;
}

.conversation-item {
  position: relative;
  padding: 12px 16px;
  border-bottom: 1px solid var(--o06);
  cursor: pointer;
  transition: all var(--transition-fast);
  min-height: 72px;
}

.conversation-item:hover {
  background: var(--o05);
}

.conversation-item:focus-visible {
  outline: 2px solid var(--ring-focus);
  outline-offset: -2px;
}

.conversation-item.active {
  background: var(--accent-bg-06);
  border-left: 3px solid var(--accent-ink);
}

.conversation-item-header {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  gap: 8px;
  margin-bottom: var(--space-xs);
}

.conversation-item-header h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
  flex: 1;
}

.timestamp {
  margin-left: auto;
  font-size: 11px;
  color: var(--muted);
}

.contact-context-menu {
  position: relative;
  flex: 0 0 auto;
}

.contact-context-menu__button {
  display: inline-flex;
  width: 24px;
  height: 24px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  user-select: none;
}

.contact-context-menu__button:hover,
.contact-context-menu__button:focus-visible {
  background: var(--o06);
  color: var(--text);
}

.contact-context-menu__panel {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 20;
  display: grid;
  min-width: 150px;
  padding: 5px;
  border: 1px solid var(--o12);
  border-radius: 9px;
  background: var(--bg2);
  box-shadow: var(--shadow-md);
}

.contact-context-menu__panel button {
  width: 100%;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--muted);
  padding: 7px 9px;
  text-align: left;
  font-size: 11px;
}

.contact-context-menu__panel button.active,
.contact-context-menu__panel button:hover:not(:disabled) {
  background: var(--o06);
  color: var(--text);
}

.contact-context-menu__panel button:disabled {
  opacity: .55;
  cursor: not-allowed;
}

.contact-context-menu__note {
  margin: 4px 4px 1px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.3;
}

.contact-profile-line {
  margin: 2px 0 4px 44px;
  color: var(--muted);
  font-size: 10.5px;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conversation-preview {
  display: flex;
  gap: 4px;
  margin-bottom: 4px;
  font-size: 12px;
  align-items: center;
}

.agent-name {
  font-weight: 500;
  color: var(--muted);
}

.last-message {
  font-size: 12px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 140px;
}

.message-count {
  font-size: 11px;
  color: var(--faint);
}

.unread-bubble {
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  border-radius: 50%;
  min-width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  margin-left: auto;
}

.no-chat-selected {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--muted);
  opacity: 0.7;
}

.loading-state,
.error-state,
.empty-state {
  padding: 16px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}

.refresh-button {
  padding: 4px 8px;
  background: var(--o06);
  border: 1px solid var(--o10);
  border-radius: var(--radius-sm);
  color: var(--text3);
  cursor: pointer;
  font-size: 12px;
}

.load-more-trigger {
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px 0;
  margin: 8px 0;
}

.loading-more {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  display: flex;
  align-items: center;
  gap: 8px;
}

.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--primary-color);
  border-radius: 50%;
  border-top-color: transparent;
  animation: spin 1s linear infinite;
}

.load-more-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.load-more-hint {
  font-size: 12px;
  color: var(--text-muted);
  opacity: 0.7;
}

.load-more-button {
  padding: 6px 12px;
  background-color: var(--background-soft);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.load-more-button:hover {
  background-color: var(--accent-solid);
  color: var(--on-accent-solid);
  border-color: var(--primary-color);
}

.load-more-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.scroll-to-top-btn {
  position: absolute;
  bottom: 16px;
  right: 16px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  transition: all var(--transition-fast);
  z-index: 10;
}

.scroll-to-top-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.scroll-to-top-btn:active {
  transform: translateY(0);
}

.product-preview {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--primary-color);
  font-weight: 500;
}

.product-icon {
  font-size: 14px;
  line-height: 1;
}

.last-message.product-preview {
  color: var(--primary-color);
  max-width: 160px;
}

@media (min-width: 769px) {
  .conversations-container.rail-collapsed,
  .conversations-container.rail-collapsed.with-chat-info {
    grid-template-columns: 72px 1fr;
  }

  .rail-collapsed .frozen-rail-heading {
    justify-content: center;
    padding: 8px 4px;
  }

  .rail-collapsed .conversation-item {
    min-height: 58px;
    padding: 10px 8px;
  }

  .rail-collapsed .conversation-item-header {
    justify-content: center;
    margin: 0;
  }

  .rail-collapsed .conversation-item-header h3,
  .rail-collapsed .conversation-item-header :deep(.channel-badge),
  .rail-collapsed .timestamp,
  .rail-collapsed .contact-context-menu,
  .rail-collapsed .conversation-preview,
  .rail-collapsed .message-count,
  .rail-collapsed .conversation-footer,
  .rail-collapsed .load-more-hint,
  .rail-collapsed .load-more-button {
    display: none;
  }
}

/* Mobile: single stacked pane — the list by default, the chat when a session
   is selected (?session= in the URL, via the mobilePane prop) */
@media (max-width: 768px) {
  .conversations-container,
  .conversations-container.with-chat-info {
    grid-template-columns: 1fr;
  }

  .conversations-container .chat-view {
    display: none;
  }

  .conversations-container.mobile-show-chat .conversations-sidebar {
    display: none;
  }

  .conversations-container.mobile-show-chat .chat-view {
    display: flex;
  }

  .conversations-sidebar {
    border-right: none;
  }

  .conversation-item {
    padding: 14px 16px;
  }

  .conversation-item.active {
    background: transparent;
    border-left: none;
  }

  .conversation-item-header h3 {
    max-width: none;
    font-size: 15px;
  }

  .last-message {
    max-width: none;
    flex: 1;
  }
}
</style> 