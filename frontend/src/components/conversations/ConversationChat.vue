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
import { onMounted, watch, nextTick, ref, computed, onBeforeUnmount } from 'vue'
import type { ChatDetail, Message } from '@/types/chat'
import userAvatar from '@/assets/user.svg'
import { myAvatarUrl } from '@/config/api'
import { useConversationChat } from '@/composables/useConversationChat'
import { useConversationFiles } from '@/composables/useConversationFiles'
import { useVisualViewport } from '@/composables/useVisualViewport'
import { useJiraTicket } from '@/composables/useJiraTicket'
import JiraTicketModal from '@/components/jira/JiraTicketModal.vue'
import TicketCreateModal from '@/components/tickets/TicketCreateModal.vue'
import { ticketService } from '@/services/tickets'
import { permissionChecks } from '@/utils/permissions'
import FileUpload from '@/components/common/FileUpload.vue'
import { userService } from '@/services/user'
import { voiceService, type VoiceAttachment } from '@/services/voice'
import ChannelBadge from '@/components/common/ChannelBadge.vue'
import CustomerAvatar from '@/components/people/CustomerAvatar.vue'
import WhatsAppTemplatePicker from '@/components/conversations/WhatsAppTemplatePicker.vue'
import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/sanitize'
import type { Renderer } from 'marked'
import { Menu, MenuButton, MenuItems, MenuItem } from '@headlessui/vue'
import { observeElementRect, useVirtualizer } from '@tanstack/vue-virtual'
import { messageStableKey } from '@/services/chat'
import { translationService, type TranslationPreview } from '@/services/translation'
import YanceBilingualMessageProjection from '@/yance/components/YanceBilingualMessageProjection.vue'
import type { YanceTranslationProjection } from '@/yance/semanticTypes'

const props = defineProps<{
  chat: ChatDetail
  frozenYance?: boolean
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'chatUpdated', data: ChatDetail): void
  (e: 'clearUnread', sessionId: string): void
  (e: 'view-product', productId: string): void
  (e: 'back'): void
  (e: 'info'): void
}>()

// Create a local ref to track the current chat state
const currentChat = ref(props.chat)

type AdoptedMediaIntent = {
  type: 'voice' | 'photo' | 'image' | 'video' | 'file'
  label: string
  prompt: string
  runtimeState: 'ready' | 'runtime-pending'
}

const adoptedMediaIntent = ref<AdoptedMediaIntent | null>(null)

const readPreferredLanguage = (chat: ChatDetail): string => {
  const value = chat.customer.meta_data?.yance_translation
  if (!value || typeof value !== 'object') return 'auto'
  const preferred = (value as Record<string, unknown>).preferredLanguage
  return typeof preferred === 'string' && preferred ? preferred : 'auto'
}

const translationProjections = ref<Record<string, YanceTranslationProjection>>({})
const translationRequestedIds = new Set<number>()
let translationGeneration = 0
const contactLanguageSelection = ref(readPreferredLanguage(props.chat))
const contactLanguageSaving = ref(false)
const translationPreview = ref<TranslationPreview | null>(null)
const translationPreviewLoading = ref(false)
const translationPreviewError = ref('')
const translationPreviewSource = ref('')
let translationPreviewGeneration = 0
type AdoptedTranslationPairing = {
  sourceText: string
  translatedText: string
  sourceSha256: string
  sourceLanguage?: string
  targetLanguage?: string
  integrity: 'passed'
  provider?: string
  providerModel?: string
  stylePolicy: string
  humanLikeness?: 'preserved'
}
const adoptedTranslationPairing = ref<AdoptedTranslationPairing | null>(null)
const translationLanguageOptions = [
  { value: 'auto', label: '自动（跟随联系人）' },
  { value: 'de', label: 'Deutsch' },
  { value: 'en', label: 'English' },
  { value: 'it', label: 'Italiano' },
  { value: 'ro', label: 'Română' },
  { value: 'tr', label: 'Türkçe' },
  { value: 'ko', label: '한국어' },
  { value: 'zh', label: '中文' },
  { value: 'fr', label: 'Français' },
  { value: 'es', label: 'Español' },
]

// Reuse the same current-user avatar authority as DashboardLayout. There is no
// message-local avatar store and no unrelated fallback image.
const currentUserProfile = userService.getCurrentUser()
const currentUserAvatarVersion = Date.now()
const currentUserAvatarSrc = computed(() => {
  if (!currentUserProfile?.profile_pic) return userAvatar
  return myAvatarUrl(currentUserAvatarVersion)
})
const currentUserAvatarLabel = computed(
  () => currentUserProfile?.full_name || currentChat.value.user_name || '我',
)

const {
  newMessage,
  messagesContainer,
  formattedMessages,
  isLoading,
  isLoadingOlder,
  loadOlderMessages,
  showTakeoverButton,
  showTakenOverStatus,
  isChatClosed,
  canSendMessage,
  handleTakeover,
  handleRouteToHuman,
  isWaitingForHuman,
  handlerCaption,
  updateChat,
  replaceChatFromProps,
  handledByAI,
  endChat,
  templateCanReopen,
  clearTemplateSuggestion
} = useConversationChat(props.chat, emit)

const getVirtualMessageKey = (index: number) =>
  messageStableKey(formattedMessages.value[index])

const rowVirtualizer = useVirtualizer<HTMLElement, HTMLElement>(computed(() => ({
  count: formattedMessages.value.length,
  getScrollElement: () => messagesContainer.value,
  estimateSize: () => 96,
  // TanStack-native bootstrap rect keeps SSR/jsdom deterministic before the
  // real scroll element reports its ResizeObserver geometry. Live geometry
  // replaces this as soon as the mounted container is measured.
  initialRect: { width: 920, height: 620 },
  observeElementRect: (instance, callback) =>
    observeElementRect(instance, (rect) => {
      // Ignore transient hidden/zero-layout frames. Keeping the last valid rect
      // prevents the virtual range from disappearing between UI state updates;
      // the next non-zero ResizeObserver frame becomes authoritative.
      if (rect.width > 0 && rect.height > 0) callback(rect)
    }),
  overscan: 8,
  gap: 16,
  anchorTo: 'end' as const,
  followOnAppend: true,
  scrollEndThreshold: 96,
  getItemKey: getVirtualMessageKey,
})))

const virtualMessages = computed(() =>
  rowVirtualizer.value.getVirtualItems().map(row => ({
    row,
    message: formattedMessages.value[row.index],
  })).filter(item => !!item.message),
)

const virtualTotalSize = computed(() => rowVirtualizer.value.getTotalSize())

const measureMessageElement = (element: unknown) => {
  if (element instanceof HTMLElement) {
    rowVirtualizer.value.measureElement(element)
  }
}

const scrollToLatest = async () => {
  await nextTick()
  rowVirtualizer.value.scrollToEnd({ behavior: 'auto' })
}

const followLatestIfPinned = () => {
  if (rowVirtualizer.value.isAtEnd(160)) {
    void scrollToLatest()
  }
}

const handleMessagesScroll = () => {
  const container = messagesContainer.value
  if (!container || container.scrollTop > 160) return
  if (!currentChat.value.has_older || isLoadingOlder.value) return
  void loadOlderMessages()
}

// Thin composition seam: Yance candidates adopt into the existing native composer.
const adoptDraft = (draft: string) => {
  adoptedMediaIntent.value = null
  newMessage.value = draft
}

const projectionForMessage = (message: Message): YanceTranslationProjection | undefined => {
  if (message.id == null) return undefined
  const local = translationProjections.value[String(message.id)]
  if (local) return local
  const stored = message.attributes?.yance_translation
  if (!stored || typeof stored !== 'object') return undefined
  if (String(stored.messageId) !== String(message.id)) return undefined
  return stored as YanceTranslationProjection
}

const mergeTranslationProjections = (items: YanceTranslationProjection[]) => {
  if (!items.length) return
  const next = { ...translationProjections.value }
  for (const item of items) {
    if (item?.messageId == null) continue
    next[String(item.messageId)] = item
  }
  translationProjections.value = next
}

const ensureInboundTranslations = async () => {
  if (!props.frozenYance) return
  const generation = translationGeneration
  const sessionId = currentChat.value.session_id
  const requested: number[] = []

  for (const message of formattedMessages.value) {
    if (message.message_type !== 'user' || message.id == null) continue
    const stored = message.attributes?.yance_translation
    if (
      stored &&
      typeof stored === 'object' &&
      'messageId' in stored &&
      String((stored as Record<string, unknown>).messageId) === String(message.id)
    ) {
      mergeTranslationProjections([stored as YanceTranslationProjection])
    }
    if (!translationRequestedIds.has(message.id)) {
      translationRequestedIds.add(message.id)
      requested.push(message.id)
    }
  }

  if (!requested.length) return
  try {
    const projections = await translationService.ensureMessages(requested)
    if (generation !== translationGeneration || currentChat.value.session_id !== sessionId) return
    mergeTranslationProjections(projections)
  } catch {
    // Fail closed: original remains primary and no synthetic translated text is shown.
    // Release the request claim so a transient API failure can be retried.
    for (const messageId of requested) translationRequestedIds.delete(messageId)
  }
}

const recomputeMessageTranslation = async (message: Message) => {
  if (message.id == null) return
  const generation = translationGeneration
  const sessionId = currentChat.value.session_id
  try {
    const projections = await translationService.recomputeMessage(message.id)
    if (generation !== translationGeneration || currentChat.value.session_id !== sessionId) return
    mergeTranslationProjections(projections)
  } catch {
    // Existing failed/stale projection remains visible; source truth is untouched.
  }
}

const saveContactLanguage = async () => {
  if (!props.frozenYance || contactLanguageSaving.value) return
  contactLanguageSaving.value = true
  translationPreviewError.value = ''
  try {
    await translationService.setContactLanguage(
      currentChat.value.customer.id,
      contactLanguageSelection.value,
    )
    translationPreview.value = null
    translationPreviewSource.value = ''
    adoptedTranslationPairing.value = null
  } catch {
    translationPreviewError.value = '联系人语言保存失败。'
  } finally {
    contactLanguageSaving.value = false
  }
}

const requestTranslationPreview = async () => {
  const source = newMessage.value
  if (!props.frozenYance || !source.trim() || translationPreviewLoading.value) return
  const generation = ++translationPreviewGeneration
  const sessionId = currentChat.value.session_id
  translationPreviewLoading.value = true
  translationPreviewError.value = ''
  translationPreview.value = null
  translationPreviewSource.value = source
  adoptedTranslationPairing.value = null
  try {
    const preview = await translationService.preview(
      currentChat.value.customer.id,
      currentChat.value.session_id,
      source,
    )
    if (
      generation !== translationPreviewGeneration ||
      currentChat.value.session_id !== sessionId ||
      newMessage.value !== source
    ) {
      return
    }
    translationPreview.value = preview
  } catch (error: any) {
    if (generation !== translationPreviewGeneration || currentChat.value.session_id !== sessionId) return
    const detail = error?.response?.data?.detail
    translationPreviewError.value =
      detail === 'contact_language_unknown'
        ? '请先选择联系人语言，或先让系统从收到的消息确认语言。'
        : detail === 'translation_owner_not_configured'
          ? '翻译服务尚未配置。'
          : '翻译预览失败；原文不会被替换。'
  } finally {
    if (generation === translationPreviewGeneration) translationPreviewLoading.value = false
  }
}

const adoptTranslatedPreview = () => {
  const preview = translationPreview.value
  if (
    preview?.status !== 'success' ||
    !preview.text ||
    !preview.sourceSha256 ||
    !preview.targetLanguage ||
    translationPreviewSource.value !== newMessage.value
  ) return
  adoptedTranslationPairing.value = {
    sourceText: translationPreviewSource.value,
    translatedText: preview.text,
    sourceSha256: preview.sourceSha256,
    sourceLanguage: preview.sourceLanguage,
    targetLanguage: preview.targetLanguage,
    integrity: 'passed',
    provider: preview.provider,
    providerModel: preview.providerModel,
    stylePolicy: preview.stylePolicy,
    humanLikeness: preview.humanLikeness === 'preserved' ? 'preserved' : undefined,
  }
  newMessage.value = preview.text
  translationPreview.value = null
  translationPreviewSource.value = ''
}

watch(newMessage, (value) => {
  if (
    translationPreview.value &&
    translationPreview.value.status !== 'stale' &&
    translationPreviewSource.value !== value
  ) {
    translationPreview.value = { ...translationPreview.value, status: 'stale' }
  }
  if (
    adoptedTranslationPairing.value &&
    adoptedTranslationPairing.value.translatedText !== value
  ) {
    adoptedTranslationPairing.value = null
  }
})

// Templates are a WhatsApp-only way back into a conversation whose 24h window
// closed, and they need the account the conversation arrived on.
const showTemplatePicker = ref(false)
const canUseTemplates = computed(
  () => currentChat.value.channel === 'whatsapp' && !!currentChat.value.channel_account_id
)

const handleTemplateSent = () => {
  showTemplatePicker.value = false
  clearTemplateSuggestion()
  emit('refresh')
}

// Add file handling functionality
const {
  fileUploadRef,
  uploadedFiles,
  existingAttachmentIds,
  adoptExistingAttachment,
  handleFilesUploaded,
  handleFileUploadError,
  handleChatPaste,
  handleSendMessageWithAttachments,
  formatFileSize,
  isImageAttachment,
  isAudioAttachment,
  isVideoAttachment,
  getDownloadUrl,
  getImageUrl
} = useConversationFiles(currentChat, newMessage, canSendMessage, followLatestIfPinned)

const adoptComposerAttachment = (attachmentId: number) => {
  adoptExistingAttachment(attachmentId)
  adoptedMediaIntent.value = null
}

const adoptMediaIntent = (intent: AdoptedMediaIntent) => {
  adoptedMediaIntent.value = intent
}

// TTS generates one canonical FileAttachment, previews it with the browser's
// native audio element, then the existing composer adopts it on final send.
const ttsGenerating = ref(false)
const ttsPreview = ref<VoiceAttachment | null>(null)
const ttsError = ref('')
const composerIsComposing = ref(false)

const composerTtsErrorId = computed(
  () => `composer-tts-error-${currentChat.value.session_id}`,
)
const composerUnavailableId = computed(
  () => `composer-unavailable-${currentChat.value.session_id}`,
)
const composerDescriptionIds = computed(() => {
  const ids: string[] = []
  if (ttsError.value) ids.push(composerTtsErrorId.value)
  if (!canSendMessage.value && handlerCaption.value) ids.push(composerUnavailableId.value)
  return ids.length > 0 ? ids.join(' ') : undefined
})

const openRowMenuFromContext = (event: MouseEvent, triggerSelector: string) => {
  const row = event.currentTarget as HTMLElement | null
  const trigger = row?.querySelector<HTMLButtonElement>(triggerSelector)
  trigger?.click()
}

const copyMessageText = async (text?: string | null) => {
  if (!text || !navigator.clipboard?.writeText) return
  try {
    await navigator.clipboard.writeText(text)
  } catch (error) {
    console.warn('Unable to copy message text', error)
  }
}

const handleGenerateTts = async () => {
  const sourceText = newMessage.value.trim()
  if (!sourceText || !canSendMessage.value || ttsGenerating.value) return
  if (uploadedFiles.value.length > 0 || existingAttachmentIds.value.length > 0) return

  ttsGenerating.value = true
  ttsError.value = ''
  try {
    const generated = await voiceService.generateSpeech(sourceText)
    adoptExistingAttachment(generated.attachment.id)
    ttsPreview.value = generated.attachment
    // The final send is the generated audio asset, not a duplicate text+audio send.
    newMessage.value = ''
    followLatestIfPinned()
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    ttsError.value = detail === 'elevenlabs_credential_unavailable' ||
      detail === 'elevenlabs_default_voice_unavailable'
      ? 'Voice provider is not configured'
      : 'Voice generation failed'
  } finally {
    ttsGenerating.value = false
  }
}

const handleComposerSend = async () => {
  const hadPayload = !!newMessage.value.trim() ||
    uploadedFiles.value.length > 0 || existingAttachmentIds.value.length > 0
  if (adoptedTranslationPairing.value) {
    await handleSendMessageWithAttachments({
      translationPairing: adoptedTranslationPairing.value,
    })
  } else {
    await handleSendMessageWithAttachments()
  }
  if (hadPayload) {
    ttsPreview.value = null
    ttsError.value = ''
    adoptedMediaIntent.value = null
    translationPreview.value = null
    translationPreviewSource.value = ''
    translationPreviewError.value = ''
    adoptedTranslationPairing.value = null
  }
}

const handleComposerKeydown = (event: KeyboardEvent) => {
  if (event.key !== 'Enter') return
  if (event.shiftKey || composerIsComposing.value || event.isComposing) return
  event.preventDefault()
  if (!canSendMessage.value) return
  void handleComposerSend()
}

// Add Jira ticket functionality
const {
  jiraConnected,
  checkJiraStatus
} = useJiraTicket()

// State for Jira ticket modal
const showJiraTicketModal = ref(false)
const ticketSummary = ref('')

// Native ticketing: preferred over Jira when the user can manage tickets.
// One native ticket per session — the button flips to "View ticket".
const showTicketModal = ref(false)
const canUseNativeTickets = permissionChecks.canManageTickets()
const linkedTicketId = ref<string | null>(null)
const showTicketMenu = ref(false)

async function refreshLinkedTicket() {
  if (!canUseNativeTickets || !currentChat.value?.session_id) return
  const ticket = await ticketService.getTicketBySession(currentChat.value.session_id)
  linkedTicketId.value = ticket?.id || null
}


// Add marked configuration
marked.setOptions({
  renderer: new marked.Renderer(),
  gfm: true,
  breaks: true
})

// Configure marked renderer to add target="_blank" to links
const renderer = new marked.Renderer() as Renderer
renderer.link = function({ href, title, text }) {
  if (!href) return text || ''
  const link = `<a href="${href}"${title ? ` title="${title}"` : ''}>${text}</a>`
  return link.replace(/^<a /, '<a target="_blank" rel="nofollow" ')
}
marked.use({ renderer })

// Create helper function to render and sanitize markdown
const renderMarkdown = (text: string) => {
  return sanitizeHtml(marked.parse(text, { async: false }) as string)
}





// Computed property to determine if the current user can create a ticket
const canCreateTicket = computed(() => {
  // Can only create ticket if:
  // 1. User can send messages (already handled by canSendMessage)
  // 2. Chat is not closed
  // 3. Current user is the one who took over the chat
  return canSendMessage.value && 
         !isChatClosed.value && 
         currentChat.value.user_id === userService.getUserId();
})



// Function to handle create ticket
const handleCreateTicket = async () => {
  // Get a summary from the last few messages
  const lastMessages = formattedMessages.value.slice(-3)
  const summary = lastMessages.map(m => m.message).join(' ').substring(0, 100) + '...'
  
  ticketSummary.value = summary
  showJiraTicketModal.value = true
}

// Function to handle ticket created
const handleTicketCreated = (ticketKey: string) => {
  // Add ticket key to message input
  newMessage.value = `Jira ticket created: ${ticketKey}`
  // Close the modal
  showJiraTicketModal.value = false
}



// Keep the composer above the on-screen keyboard on installed iOS PWAs, where
// the keyboard overlays the viewport instead of resizing it
useVisualViewport(() => {
  if (rowVirtualizer.value.isAtEnd(160)) {
    void scrollToLatest()
  }
})

// Watch for chat changes and update the internal state
watch(() => props.chat, (newChat) => {
  if (newChat) {
    // Only sync local state to avoid emitting events back to parent.
    currentChat.value = newChat
    replaceChatFromProps(newChat)
    contactLanguageSelection.value = readPreferredLanguage(newChat)
  }
}, { immediate: true })

watch(
  () => formattedMessages.value
    .map(message => `${message.id ?? 'optimistic'}:${message.attributes?.yance_translation?.status ?? ''}`)
    .join('|'),
  () => { void ensureInboundTranslations() },
  { immediate: true },
)

// Check Jira status on mount
onMounted(async () => {
  await scrollToLatest()
  await checkJiraStatus()
  await refreshLinkedTicket()
})

watch(() => currentChat.value?.session_id, (sessionId, previousSessionId) => {
  void refreshLinkedTicket()
  if (sessionId && sessionId !== previousSessionId) {
    translationGeneration++
    translationPreviewGeneration++
    translationRequestedIds.clear()
    translationProjections.value = {}
    translationPreview.value = null
    translationPreviewSource.value = ''
    translationPreviewError.value = ''
    adoptedTranslationPairing.value = null
    contactLanguageSelection.value = readPreferredLanguage(currentChat.value)
    void scrollToLatest()
    void ensureInboundTranslations()
  }
})
</script>

<template>
  <div class="chat-layout">
    <header
      class="chat-header"
      :data-yance-frozen-conversation-chrome="frozenYance ? 'native' : undefined"
    >
      <button class="back-btn" aria-label="Back to conversations" @click="emit('back')">
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg>
      </button>
      <div
        class="chat-contact-identity"
        :data-yance-current-contact="frozenYance ? 'native' : undefined"
      >
        <CustomerAvatar
          :profile="currentChat.customer.profile"
          :display-name="currentChat.customer.full_name || currentChat.customer.email"
          :size="40"
        />
        <div class="user-info">
          <div class="user-info-top">
          <h2>{{ chat.customer.full_name || chat.customer.email }}</h2>
          <ChannelBadge :channel="chat.channel" />
        </div>
        <div v-if="handledByAI" class="chat-closed-status">
          <font-awesome-icon icon="fa-solid fa-lock" />
          Handled by AI
        </div>
        <div v-if="isWaitingForHuman" class="chat-closed-status">
          <font-awesome-icon icon="fa-solid fa-user-clock" />
          Waiting for a human
        </div>
        <div v-if="showTakenOverStatus" class="taken-over-status">
          <font-awesome-icon icon="fa-solid fa-user-clock" />
          <span class="status-text" :title="`Taken over by ${chat.user_name || 'another agent'}`">
            Taken over by {{ chat.user_name || 'another agent' }}
          </span>
        </div>
          <div v-if="isChatClosed" class="chat-closed-status">
            <font-awesome-icon icon="fa-solid fa-lock" />
            Chat closed
          </div>
        </div>
      </div>
      <div class="header-actions">
        <template v-if="!frozenYance">
        <!-- The thread only streams once a human takes the chat over; while the
             AI is answering this is how you pull the latest turns. -->
        <button class="refresh-chat-btn" title="Refresh conversation" @click="emit('refresh')">
          <!-- font-awesome-icon, not <i class="fas">: the FA CSS isn't loaded
               and dom.watch() isn't on, so bare <i> tags render nothing. -->
          <font-awesome-icon icon="fa-solid fa-rotate-right" />
        </button>
        <button
          v-if="canUseTemplates && !isChatClosed"
          class="create-ticket-btn"
          title="Send template"
          aria-label="Send template"
          @click="showTemplatePicker = true"
        >
          <font-awesome-icon icon="fa-solid fa-comment-dots" />
          <span class="btn-label">Send template</span>
        </button>
        <template v-if="canCreateTicket">
          <!-- A native ticket already exists for this conversation -->
          <button
            v-if="linkedTicketId"
            class="create-ticket-btn"
            @click="$router.push(`/tickets/${linkedTicketId}`)"
          >
            <font-awesome-icon icon="fa-solid fa-ticket-alt" />
            <span class="btn-label">View ticket</span>
          </button>
          <!-- Jira connected: keep the familiar Jira flow primary, native in
               the dropdown (orgs that configured Jira keep their board). -->
          <div v-else-if="jiraConnected" class="ticket-btn-group">
            <button class="create-ticket-btn" @click="handleCreateTicket">
              <font-awesome-icon icon="fa-solid fa-ticket-alt" />
              <span class="btn-label">Create Ticket</span>
            </button>
            <button
              v-if="canUseNativeTickets"
              class="ticket-menu-toggle"
              title="More ticket options"
              @click="showTicketMenu = !showTicketMenu"
            >
              ▾
            </button>
            <div v-if="showTicketMenu" class="ticket-menu">
              <button
                class="ticket-menu-item"
                @click="showTicketMenu = false; showTicketModal = true"
              >
                Create ChatterMate ticket
              </button>
            </div>
          </div>
          <!-- No Jira: native ticketing is the flow -->
          <button
            v-else-if="canUseNativeTickets"
            class="create-ticket-btn"
            @click="showTicketModal = true"
          >
            <font-awesome-icon icon="fa-solid fa-ticket-alt" />
            <span class="btn-label">Create Ticket</span>
          </button>
        </template>
        </template>
        <slot name="conversation-header-actions" :chat="currentChat" />
        <button class="info-btn" aria-label="Conversation details" @click="emit('info')">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="7.8" r="1.1" fill="currentColor" stroke="none"/></svg>
        </button>
      </div>
    </header>

    <main class="chat-content">
      <div class="messages" ref="messagesContainer" @scroll.passive="handleMessagesScroll">
        <div
          class="messages-virtual-spacer"
          :style="{ height: `${virtualTotalSize}px` }"
        >
          <div
            v-for="{ row, message } in virtualMessages"
            :key="String(row.key)"
            :data-index="row.index"
            :ref="measureMessageElement"
            class="message-virtual-row"
            :style="{ transform: `translateY(${row.start}px)` }"
          >
            <div
              class="message"
              :class="message.message_type === 'agent' ? 'agent' : ((message.message_type === 'bot' || message.message_type === 'product') ? 'bot' : 'user')"
              @contextmenu.prevent="openRowMenuFromContext($event, '[data-yance-message-menu-button]')"
            >
          <CustomerAvatar
            v-if="
              frozenYance &&
              message.message_type !== 'agent' &&
              message.message_type !== 'bot' &&
              message.message_type !== 'product'
            "
            class="message-avatar"
            data-yance-message-avatar="contact"
            :profile="currentChat.customer.profile"
            :display-name="currentChat.customer.full_name || currentChat.customer.email"
            :size="28"
          />
          <img
            v-else-if="frozenYance"
            class="message-avatar message-avatar--self"
            data-yance-message-avatar="self"
            :src="currentUserAvatarSrc"
            :alt="currentUserAvatarLabel"
            width="28"
            height="28"
          >
          <div class="message-content">
            <Menu
              as="div"
              class="message-action-menu"
              data-yance-message-action-menu
              @click.stop
              @keydown.stop
              @contextmenu.stop
            >
              <MenuButton
                type="button"
                class="message-action-menu__button"
                data-yance-message-menu-button
                aria-label="Message actions"
              >
                ⋯
              </MenuButton>
              <MenuItems
                class="message-action-menu__items"
                data-yance-message-menu-items
              >
                <MenuItem v-if="message.message" v-slot="{ active }">
                  <button
                    type="button"
                    :class="['message-action-menu__item', { active }]"
                    data-yance-message-action="copy"
                    @click="copyMessageText(message.message)"
                  >
                    Copy
                  </button>
                </MenuItem>
                <template v-for="attachment in message.attachments || []" :key="attachment.id">
                  <MenuItem v-slot="{ active }">
                    <a
                      :class="['message-action-menu__item', { active }]"
                      data-yance-message-action="open"
                      :href="getDownloadUrl(attachment.file_url)"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Open {{ attachment.filename }}
                    </a>
                  </MenuItem>
                  <MenuItem v-slot="{ active }">
                    <a
                      :class="['message-action-menu__item', { active }]"
                      data-yance-message-action="download"
                      :href="getDownloadUrl(attachment.file_url)"
                      :download="attachment.filename"
                    >
                      Download {{ attachment.filename }}
                    </a>
                  </MenuItem>
                </template>
                <MenuItem
                  v-if="!message.message && (!message.attachments || message.attachments.length === 0)"
                  disabled
                >
                  <span class="message-action-menu__item message-action-menu__item--disabled">
                    No actions available
                  </span>
                </MenuItem>
              </MenuItems>
            </Menu>
            <div class="message-bubble">
              <!-- Product message -->
              <template v-if="message.message_type === 'product' && message.attributes?.shopify_output?.products?.length">
                <div class="products-carousel">
                  <div v-html="renderMarkdown(message.message || '')" class="product-message-text"></div>
                  <div class="carousel-items">
                    <div 
                      v-for="product in message.attributes.shopify_output.products" 
                      :key="product.id" 
                      class="product-card-compact"
                    >
                      <div class="product-image-compact" v-if="product.image?.src">
                        <img :src="product.image.src" :alt="product.title || ''" class="product-thumbnail">
                      </div>
                      <div class="product-info-compact">
                        <div class="product-text-area">
                          <div class="product-title-compact">{{ product.title }}</div>
                          <div class="product-variant-compact" v-if="product.variant_title">{{ product.variant_title }}</div>
                          <div class="product-price-compact">{{ product.price }}</div>
                        </div>
                        <div class="product-actions-compact">
                          <button 
                            class="view-details-button-compact"
                            @click="$emit('view-product', String(product?.id || 'unknown'))"
                          >
                            View product <span class="external-link-icon">↗</span>
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
              <!-- Regular message with markdown -->
              <template v-else>
                <div v-html="renderMarkdown(message.message || '')"></div>
                
                <!-- Display attachments if present -->
                <div v-if="message.attachments && message.attachments.length > 0" class="message-attachments">
                  <div 
                    v-for="attachment in message.attachments" 
                    :key="attachment.id"
                    class="attachment-item"
                  >
                    <!-- Image attachment - render as image -->
                    <template v-if="isImageAttachment(attachment.content_type)">
                      <div class="attachment-image-container">
                        <img 
                          :src="getImageUrl(attachment.file_url)" 
                          :alt="attachment.filename"
                          class="attachment-image"
                        />
                        <div class="attachment-image-info">
                          <a 
                            :href="getDownloadUrl(attachment.file_url)" 
                            target="_blank"
                            class="attachment-link"
                          >
                            <font-awesome-icon icon="fa-solid fa-download" />
                            {{ attachment.filename }}
                            <span class="attachment-size">({{ formatFileSize(attachment.file_size) }})</span>
                          </a>
                        </div>
                      </div>
                    </template>
                    <!-- Audio/video stay browser-native: no second media player/runtime. -->
                    <template v-else-if="isAudioAttachment(attachment.content_type)">
                      <audio
                        :src="getDownloadUrl(attachment.file_url)"
                        controls
                        preload="metadata"
                        class="attachment-audio"
                      ></audio>
                    </template>
                    <template v-else-if="isVideoAttachment(attachment.content_type)">
                      <video
                        :src="getDownloadUrl(attachment.file_url)"
                        controls
                        preload="metadata"
                        class="attachment-video"
                      ></video>
                    </template>
                    <!-- Other file types - render as download link -->
                    <template v-else>
                      <a 
                        :href="getDownloadUrl(attachment.file_url)" 
                        target="_blank"
                        class="attachment-link"
                      >
                        <font-awesome-icon icon="fa-solid fa-paperclip" />
                        {{ attachment.filename }}
                        <span class="attachment-size">({{ formatFileSize(attachment.file_size) }})</span>
                      </a>
                    </template>
                  </div>
                </div>
                <div
                  v-if="message.attributes?.voice_transcriptions?.length"
                  class="voice-transcriptions"
                >
                  <div
                    v-for="transcription in message.attributes.voice_transcriptions"
                    :key="transcription.attachment_id || transcription.attachment_index"
                    class="voice-transcription"
                  >
                    <template v-if="transcription.status === 'succeeded'">
                      <span class="voice-transcription-label">Transcript</span>
                      <span>{{ transcription.text }}</span>
                    </template>
                    <span v-else class="voice-transcription-unavailable">Transcription unavailable</span>
                  </div>
                </div>
              </template>
              <YanceBilingualMessageProjection
                v-if="frozenYance && message.message_type === 'user' && projectionForMessage(message)"
                :canonical-message-id="message.id!"
                :translation="projectionForMessage(message)!"
                :source-text="message.message"
              />
              <button
                v-if="frozenYance && message.message_type === 'user' && ['failed', 'stale'].includes(projectionForMessage(message)?.status || '')"
                type="button"
                class="translation-recompute-button"
                data-yance-translation-recompute
                @click="recomputeMessageTranslation(message)"
              >
                重新翻译
              </button>
              <slot name="message-secondary" :message="message" :chat="currentChat" />
              <span class="message-time">{{ message.timeAgo }}</span>
              <span v-if="message.attributes?.delivery_status" class="delivery-failed">
                <font-awesome-icon icon="fa-solid fa-circle-exclamation" /> Not delivered
              </span>
            </div>
            <span v-if="message.message_type === 'bot' || message.message_type === 'agent'" class="agent-name">
              {{ message.message_type === 'bot' ? (message.agent_name || chat.agent.name || 'AI Agent') : (message.user_name || 'Agent') }}
            </span>
          </div>
            </div>
          </div>
        </div>
      </div>
    </main>


    <slot
      name="conversation-extension"
      :chat="currentChat"
      :adopt-draft="adoptDraft"
      :adopt-attachment="adoptComposerAttachment"
      :adopt-media-intent="adoptMediaIntent"
    />

    <!-- Jira Ticket Modal -->
    <JiraTicketModal
      v-if="showJiraTicketModal"
      :chat-id="currentChat.session_id"
      :initial-summary="ticketSummary"
      @close="showJiraTicketModal = false"
      @ticket-created="handleTicketCreated"
    />

    <!-- Native ticket modal (AI-drafted from this conversation) -->
    <TicketCreateModal
      :open="showTicketModal"
      :session-id="currentChat.session_id"
      :session-label="chat.customer.full_name || chat.customer.email || 'this conversation'"
      @close="showTicketModal = false"
      @created="refreshLinkedTicket"
    />

    <!-- Unclaimed: the composer is replaced by the primary "Take over chat"
         action. Covers both an AI-handled chat and one the AI has queued for a
         human, so claiming never requires opening the details panel. -->
    <footer v-if="showTakeoverButton" class="chat-input takeover-footer">
      <div class="takeover-caption">
        {{ handlerCaption }}
      </div>
      <button class="takeover-button" :disabled="isLoading" @click="handleTakeover">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 12h11m0 0l-4-4m4 4l-4 4"/><path d="M5 5v14"/></svg>
        Take over chat
      </button>
      <!-- Claiming it yourself was the only way to silence the AI. This queues
           it for whoever is free instead. -->
      <button
        v-if="handledByAI"
        class="hand-over-button"
        :disabled="isLoading"
        @click="handleRouteToHuman"
      >
        <font-awesome-icon icon="fa-solid fa-user-group" />
        Hand to my team
      </button>
    </footer>

    <footer
      class="chat-input"
      :class="{ 'frozen-yance-composer': frozenYance }"
      v-else-if="!isChatClosed && !handledByAI"
      :data-yance-frozen-composer="frozenYance ? 'native' : undefined"
    >
      <!-- The agent has just been told a reply couldn't be delivered; offer the
           one action that gets the conversation back rather than leaving them
           to retype into a composer that will fail again. -->
      <div v-if="templateCanReopen && canUseTemplates" class="window-closed-notice">
        <div class="window-closed-text">
          <font-awesome-icon icon="fa-solid fa-clock" />
          <span>This customer's 24-hour window has closed. Send an approved template to reopen it.</span>
        </div>
        <button class="window-closed-btn" @click="showTemplatePicker = true">
          Send template
        </button>
      </div>
      <div
        v-if="adoptedMediaIntent"
        class="adopted-media-intent"
        data-yance-adopted-media-intent
        :data-modality="adoptedMediaIntent.type"
        :data-runtime-state="adoptedMediaIntent.runtimeState"
      >
        <strong>{{ adoptedMediaIntent.label }}</strong>
        <span v-if="adoptedMediaIntent.runtimeState === 'runtime-pending'">
          已采用生成意图；当前 provider 未就绪，尚未生成附件。
        </span>
        <span v-else>已采用生成意图；等待成熟 owner 物化为 FileAttachment 后才可发送。</span>
      </div>
      <div v-if="ttsPreview" class="tts-preview">
        <audio
          :src="getDownloadUrl(ttsPreview.file_url)"
          controls
          preload="metadata"
          class="attachment-audio"
        ></audio>
        <span>Generated voice ready to send</span>
      </div>
      <div
        v-if="ttsError"
        :id="composerTtsErrorId"
        class="tts-error"
        role="status"
        aria-live="polite"
      >
        {{ ttsError }}
      </div>
      <div
        class="input-container"
        :class="{ disabled: !canSendMessage }"
        role="group"
        :aria-disabled="!canSendMessage"
        :aria-describedby="composerDescriptionIds"
        @paste="handleChatPaste"
      >
        <FileUpload
          ref="fileUploadRef"
          :max-files="3"
          @filesUploaded="handleFilesUploaded"
          @error="handleFileUploadError"
        />
        <div class="message-input-wrapper">
          <textarea
            v-model="newMessage"
            rows="1"
            :placeholder="frozenYance ? '发送消息…' : 'Type a message or paste a screenshot'"
            class="message-input"
            :disabled="!canSendMessage"
            :aria-describedby="composerDescriptionIds"
            @compositionstart="composerIsComposing = true"
            @compositionend="composerIsComposing = false"
            @keydown="handleComposerKeydown"
          ></textarea>
          <button
            class="tts-button"
            @click="handleGenerateTts"
            :disabled="!newMessage.trim() || !canSendMessage || ttsGenerating || uploadedFiles.length > 0 || existingAttachmentIds.length > 0"
            :aria-label="ttsGenerating ? 'Generating voice' : 'Generate voice'"
            :title="ttsGenerating ? 'Generating voice…' : 'Generate voice with ElevenLabs'"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H2v6h4l5 4V5z"></path><path d="M15.5 8.5a5 5 0 0 1 0 7"></path><path d="M18.5 5.5a9 9 0 0 1 0 13"></path></svg>
          </button>
          <button
            class="send-button"
            :class="{ 'send-button--frozen': frozenYance }"
            @click="handleComposerSend"
            :disabled="(!newMessage.trim() && uploadedFiles.length === 0 && existingAttachmentIds.length === 0) || !canSendMessage"
            :aria-label="frozenYance ? '发送并学习' : 'Send'"
            :title="frozenYance ? '发送使用原生路径；学习策略当前不可用' : 'Send'"
            :data-yance-final-send="frozenYance ? 'native' : undefined"
            :data-yance-send-policy="frozenYance ? 'carrier' : undefined"
            :data-physical-send-owner="frozenYance ? 'native' : undefined"
            :data-learning-owner-state="frozenYance ? 'unavailable' : undefined"
          >
            <span v-if="frozenYance" class="send-button__frozen-label">
              发送并学习 ▾ <small>学习暂不可用</small>
            </span>
            <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"></path><path d="M22 2l-7 20-4-9-9-4 20-7z"></path></svg>
          </button>
        </div>
      </div>
      <div
        v-if="frozenYance"
        class="frozen-composer-policy-row"
        data-yance-composer-policy-carriers
      >
        <span
          data-yance-typing-policy
          data-owner-state="unavailable"
          aria-disabled="true"
          title="当前暂不可调整真人打字策略"
        >
          真人打字·自然 ▾ <small>暂不可调</small>
        </span>
        <label class="translation-language-control" data-yance-contact-language>
          <span>联系人语言</span>
          <select
            v-model="contactLanguageSelection"
            :disabled="contactLanguageSaving"
            aria-label="联系人目标语言"
            @change="saveContactLanguage"
          >
            <option
              v-for="option in translationLanguageOptions"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </option>
          </select>
        </label>
      </div>
      <div
        v-if="frozenYance"
        class="frozen-translation-carrier"
        data-yance-translation-preview
        data-integrity-state="fail-closed"
        :data-current-integrity="translationPreview?.integrity || 'fail-closed'"
        :data-preview-state="translationPreview?.status || (translationPreviewLoading ? 'loading' : 'idle')"
      >
        <div class="translation-preview-heading">
          <span>发送前翻译预览 · 保留人格/聊天语气</span>
          <button
            type="button"
            :disabled="!newMessage.trim() || translationPreviewLoading"
            @click="requestTranslationPreview"
          >
            {{ translationPreviewLoading ? '翻译中…' : '生成预览' }}
          </button>
        </div>
        <p v-if="translationPreview?.status === 'success'" class="translation-preview-text">
          {{ translationPreview.text }}
        </p>
        <p v-else-if="translationPreview?.status === 'same_language'">
          当前文本已经是联系人语言，无需翻译。
        </p>
        <p v-else-if="translationPreview?.status === 'failed'">
          完整性检查未通过；译文不会进入 Composer。
        </p>
        <p v-else-if="translationPreview?.status === 'stale'">
          原文已变化，这份预览已过期，请重新生成。
        </p>
        <p v-else-if="translationPreviewError" role="status">{{ translationPreviewError }}</p>
        <p v-else class="translation-preview-hint">
          原文始终是编辑来源；只有通过完整性检查的译文才能由你采用到同一个 Composer。
        </p>
        <button
          v-if="translationPreview?.status === 'success'"
          type="button"
          class="translation-adopt-button"
          @click="adoptTranslatedPreview"
        >
          采用译文
        </button>
      </div>
      <div
        v-if="!canSendMessage"
        :id="composerUnavailableId"
        class="input-message"
        role="status"
        aria-live="polite"
      >
        {{ handlerCaption }}
      </div>
    </footer>

    <footer v-else-if="handledByAI" class="chat-closed-footer">
      <div class="chat-closed-message">
        <font-awesome-icon icon="fa-solid fa-lock" />
        This chat is being handled by AI
      </div>
    </footer>
    <footer v-else class="chat-closed-footer">
      <div class="chat-closed-message">
        <font-awesome-icon icon="fa-solid fa-lock" />
        This chat has been closed
      </div>
    </footer>

    <WhatsAppTemplatePicker
      v-if="showTemplatePicker && currentChat.channel_account_id"
      :account-id="currentChat.channel_account_id"
      :session-id="currentChat.session_id"
      @close="showTemplatePicker = false"
      @sent="handleTemplateSent"
    />
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  flex-direction: column;
  /* Fill .chat-view rather than a fixed viewport fraction — the pane is already
     sized by the grid, and 70vh left a dead strip below the message input. */
  height: 100%;
  flex: 1;
  min-height: 0;
  width: 100%;
  background: var(--bg);
  position: relative;
  overflow: hidden;
}

.chat-header {
  flex: 0 0 auto;
  padding: 14px 20px;
  border-bottom: 1px solid var(--o08);
  background: var(--bg2);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  width: 100%;
}

/* Mobile-only affordances (back chevron, info button) */
.back-btn,
.info-btn {
  display: none;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  color: var(--text);
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
  -webkit-tap-highlight-color: transparent;
}

.chat-header[data-yance-frozen-conversation-chrome] .info-btn {
  display: inline-flex;
}

.info-btn {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  background: var(--o05);
  border: 1px solid var(--o10);
  color: var(--text3);
}

.takeover-footer {
  display: flex;
  flex-direction: column;
  gap: 11px;
}

.takeover-caption {
  text-align: center;
  font-size: 12.5px;
  color: var(--muted);
}

.takeover-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  height: 50px;
  border: none;
  border-radius: 13px;
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  font-family: var(--font-sans);
  font-size: 15px;
  font-weight: var(--font-weight-bold);
  cursor: pointer;
  transition: filter var(--transition-fast), opacity var(--transition-fast);
}

.takeover-button:hover:not(:disabled) {
  filter: brightness(1.05);
}

.takeover-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Secondary to "Take over chat": same shape, no fill. */
.hand-over-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  height: 44px;
  border: 1px solid var(--border-color);
  border-radius: 13px;
  background: transparent;
  color: var(--text-color);
  font-family: var(--font-sans);
  font-size: 14px;
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: background var(--transition-fast), opacity var(--transition-fast);
}

.hand-over-button:hover:not(:disabled) {
  background: var(--o06);
}

.hand-over-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.chat-content {
  flex: 1 1 auto;
  min-height: 0;
  position: relative;
  width: 100%;
  overflow: hidden;
}

.messages {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  overflow-y: auto;
  padding: 16px;
  scroll-behavior: auto;
}

.messages-virtual-spacer {
  position: relative;
  width: 100%;
}

.message-virtual-row {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  will-change: transform;
}

.message-virtual-row > .message {
  margin-bottom: 0;
}

.chat-input {
  flex: 0 0 auto;
  padding: 14px 20px;
  border-top: 1px solid var(--o08);
  background: var(--bg2);
  width: 100%;
}

.frozen-yance-composer {
  display: grid;
  min-width: 0;
  gap: 7px;
  padding-top: 8px;
  padding-bottom: 8px;
}

/* Keep the existing composer within the 920×620 Yance frame. */
.chat-layout:has([data-yance-frozen-composer]) .chat-header {
  min-width: 0;
  padding: 8px 12px;
}
.chat-layout:has([data-yance-frozen-composer]) .chat-input {
  padding-left: 12px;
  padding-right: 12px;
}
.chat-layout:has([data-yance-frozen-composer]) .input-container,
.chat-layout:has([data-yance-frozen-composer]) .message-input-wrapper {
  min-width: 0;
  max-width: 100%;
}

.frozen-composer-policy-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.frozen-composer-policy-row > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  padding: 5px 8px;
  border: 1px solid var(--o08);
  border-radius: 8px;
  background: var(--o03);
  color: var(--muted);
  font-size: 11px;
  line-height: 1.2;
  opacity: .78;
}

.frozen-composer-policy-row small {
  font-size: 9px;
  color: var(--faint);
  white-space: nowrap;
}

.send-button__frozen-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.send-button__frozen-label small {
  font-size: 9px;
  font-weight: 500;
  opacity: .72;
}

.adopted-media-intent {
  display: flex;
  gap: 6px;
  align-items: baseline;
  padding: 6px 8px;
  border: 1px dashed var(--o10);
  border-radius: 8px;
  background: var(--o03);
  color: var(--muted);
  font-size: 10.5px;
  line-height: 1.35;
}

.adopted-media-intent strong {
  color: var(--text);
}

.frozen-translation-carrier {
  display: grid;
  gap: 6px;
  padding: 7px 8px;
  border: 1px dashed var(--o10);
  border-radius: 8px;
  color: var(--muted);
  background: var(--o03);
  font-size: 10.5px;
  line-height: 1.35;
}

.translation-preview-heading,
.translation-language-control {
  display: flex;
  align-items: center;
  gap: 7px;
}

.translation-preview-heading {
  justify-content: space-between;
}

.translation-preview-heading button,
.translation-adopt-button,
.translation-recompute-button,
.translation-language-control select {
  border: 1px solid var(--o10);
  border-radius: 7px;
  background: var(--o05);
  color: var(--text3);
  font: inherit;
}

.translation-preview-heading button,
.translation-adopt-button,
.translation-recompute-button {
  padding: 4px 7px;
  cursor: pointer;
}

.translation-preview-heading button:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.translation-preview-text,
.translation-preview-hint,
.frozen-translation-carrier p {
  margin: 0;
}

.translation-preview-text {
  color: var(--text);
  white-space: pre-wrap;
}

.translation-language-control {
  margin-left: auto;
  color: var(--muted);
  font-size: 10.5px;
}

.translation-language-control select {
  max-width: 150px;
  padding: 4px 6px;
}

.translation-recompute-button {
  margin-top: 5px;
  font-size: 10px;
}

/* Name + channel badge on one row, status line beneath — without this the
   block-level h2, the badge and the status each claim their own line and the
   status text wraps, making the header several rows tall. */
.chat-contact-identity {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-info-top {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.user-info h2 {
  font-size: 15px;
  font-family: var(--font-display);
  font-weight: 600;
  color: var(--text);
  margin: 0;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status {
  font-size: 12px;
  color: var(--muted);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.action-btn {
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
}

.action-btn:hover {
  background: var(--o08);
  color: var(--text);
}

.message {
  max-width: 76%;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 12px;
}

.message-avatar {
  flex: 0 0 28px;
}

.message-avatar--self {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
}

.message-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 100%;
  position: relative;
}

.message-action-menu {
  position: absolute;
  top: -4px;
  right: -30px;
  z-index: 12;
}

.message.bot .message-action-menu,
.message.agent .message-action-menu {
  right: auto;
  left: -30px;
}

.message-action-menu__button {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  opacity: .7;
}

.message-action-menu__button:hover,
.message-action-menu__button:focus-visible {
  background: var(--o08);
  color: var(--text);
  opacity: 1;
}

.message-action-menu__items {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 30;
  display: grid;
  min-width: 170px;
  padding: 5px;
  border: 1px solid var(--o12);
  border-radius: 9px;
  background: var(--bg2);
  box-shadow: var(--shadow-md);
}

.message.bot .message-action-menu__items,
.message.agent .message-action-menu__items {
  right: auto;
  left: 0;
}

.message-action-menu__item {
  display: block;
  width: 100%;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text3);
  padding: 7px 9px;
  text-align: left;
  text-decoration: none;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.message-action-menu__item.active,
.message-action-menu__item:hover:not(.message-action-menu__item--disabled) {
  background: var(--o06);
  color: var(--text);
}

.message-action-menu__item--disabled {
  color: var(--muted);
  cursor: default;
  opacity: .65;
}

/* Customer (incoming) — left */
.message.user {
  margin-right: auto;
  justify-content: flex-start;
}

/* AI + human agent (outbound) — right */
.message.bot,
.message.agent {
  margin-left: auto;
  justify-content: flex-end;
}

.message.bot:has(.message-avatar),
.message.agent:has(.message-avatar) {
  flex-direction: row-reverse;
}

.message-bubble {
  padding: 11px 15px;
  position: relative;
  max-width: 100%;
  word-wrap: break-word;
  font-size: 14px;
  line-height: 1.55;
}

/* Customer bubble — neutral, sharp top-left */
.message.user .message-bubble {
  background: var(--bubble-customer-bg);
  color: var(--bubble-customer-fg);
  border-radius: 4px 15px 15px 15px;
}

/* AI bubble — teal tint, sharp top-right */
.message.bot .message-bubble {
  background: var(--bubble-ai-bg);
  border: 1px solid var(--bubble-ai-border);
  color: var(--bubble-ai-fg);
  border-radius: 15px 15px 4px 15px;
}

/* Human agent bubble — lime, sharp top-right */
.message.agent .message-bubble {
  background: var(--bubble-agent-bg);
  color: var(--bubble-agent-fg);
  border-radius: 15px 15px 4px 15px;
}

.agent-name {
  font-size: 12px;
  color: var(--text-muted);
  padding-left: 4px;
  margin-top: 2px;
}

.message-time {
  font-size: 11px;
  color: var(--muted);
  margin-top: 4px;
  display: block;
  text-align: right;
}

.message.user .message-time,
.message.bot .message-time {
  color: var(--muted);
}

.message.agent .message-time {
  color: color-mix(in srgb, var(--on-accent) 55%, transparent);
}

.delivery-failed {
  font-size: 11px;
  color: var(--c-danger);
  margin-top: 2px;
  display: block;
  text-align: right;
}

/* The agent bubble is accent-filled: lift --c-danger toward the bubble's own
   foreground for contrast while keeping it readably red, not just a timestamp */
.message.agent .delivery-failed {
  color: color-mix(in srgb, var(--c-danger) 65%, var(--on-accent));
}

.window-closed-notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 14px;
  margin-bottom: 8px;
  border-radius: var(--radius-btn, 8px);
  background: var(--warning-light);
  border: 1px solid color-mix(in srgb, var(--warning) 35%, transparent);
}

.window-closed-text {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text);
}

.window-closed-text svg {
  color: var(--warning);
}

.window-closed-btn {
  padding: 7px 12px;
  border-radius: var(--radius-btn, 8px);
  border: none;
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.input-container {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  background: var(--surface);
  padding: 8px 16px;
  border-radius: 14px;
  border: 1px solid var(--o10);
}

.input-container.disabled {
  opacity: 0.7;
  background: var(--background-mute);
}

.message-input-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.message-input {
  flex: 1;
  min-height: 36px;
  max-height: 96px;
  background: none;
  border: none;
  color: var(--text-primary);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.45;
  padding: 8px 0;
  outline: none;
  resize: none;
  overflow-y: auto;
}

.message-input::placeholder {
  color: var(--text-placeholder);
}

.emoji-btn,
.attach-btn,
.tts-button,
.send-button {
  background: none;
  border: none;
  cursor: pointer;
  padding: 8px;
  font-size: 18px;
}

.tts-button {
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-input);
  color: var(--text3);
  transition: background 0.2s, opacity 0.2s;
}

.tts-button:hover:not(:disabled) {
  background: var(--o08);
  color: var(--text);
}

.tts-button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.send-button {
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  padding: 0;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-input);
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  transition: filter 0.2s, opacity 0.2s;
}

.send-button:hover:not(:disabled) {
  filter: brightness(1.05);
}

.send-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.send-button svg {
  display: block;
}

.send-button--frozen {
  width: auto;
  min-width: 54px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 650;
}



.taken-over-status {
  font-size: 12px;
  color: var(--primary-color);
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

/* text-overflow can't act on a flex item, so the label carries it */
.status-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.taken-over-status svg {
  font-size: 14px;
}

.input-message {
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
  margin-top: 8px;
}

.message-input:disabled {
  cursor: not-allowed;
}

.chat-closed-status {
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.chat-closed-status svg {
  font-size: 14px;
}

.chat-closed-footer {
  flex: 0 0 auto;
  padding: 14px 20px;
  border-top: 1px solid var(--o08);
  background: var(--bg2);
  width: 100%;
}

.chat-closed-message {
  text-align: center;
  color: var(--muted);
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.chat-closed-message svg {
  font-size: 16px;
}





.refresh-chat-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-btn, 8px);
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.refresh-chat-btn:hover {
  color: var(--text);
}

.create-ticket-btn {
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  border: none;
  border-radius: var(--radius-sm);
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: background-color 0.2s;
  margin-right: 16px;
}

.create-ticket-btn:hover {
  transform: translateY(-1px);
  filter: brightness(1.1);
}

.ticket-btn-group {
  position: relative;
  display: flex;
  align-items: center;
}

.ticket-btn-group .create-ticket-btn {
  margin-right: 0;
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
}

.ticket-menu-toggle {
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  border: none;
  border-left: 1px solid color-mix(in srgb, var(--on-accent-solid) 20%, transparent);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  padding: 8px 10px;
  font-size: 12px;
  cursor: pointer;
  margin-right: 16px;
}

.ticket-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 16px;
  z-index: 30;
  background: var(--bg2);
  border: 1px solid var(--o12);
  border-radius: 10px;
  overflow: hidden;
  min-width: 170px;
}

.ticket-menu-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 9px 13px;
  background: transparent;
  border: none;
  color: var(--text3);
  font-size: 12.5px;
  cursor: pointer;
}

.ticket-menu-item:hover {
  background: var(--o05);
  color: var(--text);
}

/* Add product carousel styles */
.products-carousel {
  margin: var(--space-xs) 0;
  width: 100%;
  padding: var(--space-xs);
  background: var(--o03);
  border-radius: 20px;
}

.product-message-text {
  margin-bottom: var(--space-sm);
}

.carousel-items {
  display: flex;
  flex-direction: row;
  gap: var(--space-sm);
  margin-top: var(--space-xs);
  overflow-x: auto;
  padding: var(--space-xs);
  padding-bottom: var(--space-md);
  scroll-snap-type: x mandatory;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: thin;
  scrollbar-color: var(--o25) var(--o08);
}

.product-card-compact {
  background-color: var(--surface);
  border: 1px solid var(--o10);
  border-radius: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06),
              0 1px 2px rgba(0, 0, 0, 0.04);
  overflow: hidden;
  width: 180px;
  flex-shrink: 0;
  transition: all 0.2s ease;
}

.product-card-compact:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08),
              0 2px 4px rgba(0, 0, 0, 0.06);
}

.product-image-compact {
  width: 100%;
  aspect-ratio: 1;
  overflow: hidden;
}

.product-thumbnail {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.2s;
}

.product-thumbnail:hover {
  transform: scale(1.05);
}

.product-info-compact {
  padding: var(--space-sm);
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.product-title-compact {
  font-size: var(--text-sm);
  font-weight: 500;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  min-height: 2.8em;
  color: var(--text);
}

.product-variant-compact {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.product-price-compact {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text);
}

.view-details-button-compact {
  width: 100%;
  padding: 8px 12px;
  background-color: var(--bg2);
  color: var(--text);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  font-size: var(--text-xs);
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  gap: 4px;
}

.view-details-button-compact:hover {
  background-color: var(--background-soft);
  border-color: var(--border-color-hover);
}

.external-link-icon {
  font-size: 1em;
  line-height: 1;
}

/* Add styles for markdown content */
.message-bubble :deep(img) {
  max-width: 100%;
  border-radius: 8px;
  margin: 8px 0;
}

.message-bubble :deep(p) {
  margin: 0;
}

.message-bubble :deep(a) {
  color: var(--primary-color);
  /* Always underlined: colour alone is not a reliable link affordance, and it
     keeps links findable on the accent-filled bubbles below. */
  text-decoration: underline;
}

/* The human-agent bubble is filled with --accent-ink, and --primary-color IS
   --accent-ink in both themes — so a link inherited the bubble's own
   background colour and rendered invisible. Links there take the bubble's
   foreground instead. */
.message.agent .message-bubble :deep(a) {
  color: var(--bubble-agent-fg);
  text-decoration: underline;
}

.message.agent .message-bubble :deep(a:hover) {
  opacity: 0.8;
}

.tts-preview {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  padding: 8px 10px;
  border: 1px solid var(--o10);
  border-radius: 10px;
  background: var(--surface);
  color: var(--text3);
  font-size: 12px;
}

.tts-preview .attachment-audio {
  flex: 1;
  min-width: 0;
}

.tts-error {
  margin-bottom: 8px;
  color: var(--c-danger);
  font-size: 12px;
}

.voice-transcriptions {
  margin-top: 7px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.voice-transcription {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 6px;
  border-top: 1px solid var(--o10);
  font-size: 12px;
  color: var(--text3);
}

.voice-transcription-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
}

.voice-transcription-unavailable {
  color: var(--muted);
  font-style: italic;
}

.attachment-audio {
  width: min(320px, 100%);
  max-width: 100%;
}

/* Attachment styles */
.message-attachments {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.attachment-item {
  display: flex;
  align-items: center;
}

.attachment-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--background-color);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  text-decoration: none;
  font-size: 13px;
  transition: all 0.2s;
  max-width: 100%;
  overflow: hidden;
}

.attachment-link:hover {
  background: var(--background-mute);
  border-color: var(--primary-color);
}

.attachment-link svg {
  font-size: 14px;
  color: var(--text-muted);
}

.attachment-size {
  color: var(--text-muted);
  font-size: 11px;
  margin-left: 4px;
}

.message.agent .attachment-link {
  background: color-mix(in srgb, var(--on-accent) 12%, transparent);
  border-color: color-mix(in srgb, var(--on-accent) 22%, transparent);
  color: var(--on-accent);
}

.message.agent .attachment-link:hover {
  background: color-mix(in srgb, var(--on-accent) 18%, transparent);
  border-color: color-mix(in srgb, var(--on-accent) 32%, transparent);
}

.message.agent .attachment-link svg,
.message.agent .attachment-size {
  color: var(--on-accent);
}

/* Image attachment styles */
.attachment-image-container {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: 350px;
}

.attachment-image {
  width: 100%;
  max-height: 400px;
  border-radius: 8px;
  object-fit: contain;
  border: 1px solid var(--border-color);
  cursor: pointer;
  transition: all 0.2s;
}

.attachment-image:hover {
  border-color: var(--primary-color);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.message.agent .attachment-image {
  border-color: color-mix(in srgb, var(--on-accent) 22%, transparent);
}

.message.agent .attachment-image:hover {
  border-color: color-mix(in srgb, var(--on-accent) 40%, transparent);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.attachment-image-info {
  display: flex;
  align-items: center;
  font-size: 12px;
}

.attachment-image-info .attachment-link {
  margin: 0;
  padding: 4px 8px;
  font-size: 12px;
}

/* Mobile: full-screen chat pane */
@media (max-width: 768px) {
  .back-btn,
  .info-btn {
    display: flex;
  }

  .back-btn {
    margin-left: -8px;
  }

  .chat-header {
    padding: calc(4px + var(--safe-top)) 6px 4px;
    gap: 2px;
  }

  .header-actions {
    gap: 2px;
  }

  /* Icon-only actions on phones — labels would squeeze the customer name */
  .btn-label {
    display: none;
  }

  /* 44px minimum touch target (Apple HIG / WCAG 2.5.8) — the header pads
     tightly instead of shrinking the controls */
  .create-ticket-btn {
    margin-right: 0;
    width: 44px;
    height: 44px;
    padding: 0;
    justify-content: center;
  }

  .refresh-chat-btn,
  .info-btn,
  .back-btn {
    width: 44px;
    height: 44px;
  }

  .message {
    max-width: 85%;
  }

  /* Keyboard-aware, safe-area-aware composer */
  .chat-input,
  .chat-closed-footer {
    padding: 12px 14px calc(12px + var(--safe-bottom) + var(--kb-offset, 0px));
  }
}
</style> 