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

import { ref, type Ref } from 'vue'
import type { ChatDetail } from '@/types/chat'
import FileUpload from '@/components/common/FileUpload.vue'
import { apiPath, resolveUploadUrl } from '@/config/api'
import { socketService } from '@/services/socket'

type SendCompositionOptions = {
  translationPairing?: Record<string, unknown>
}

export function useConversationFiles(
  currentChat: Ref<ChatDetail>,
  newMessage: Ref<string>,
  canSendMessage: Ref<boolean>,
  followLatestIfPinned: () => void
) {
  // File upload refs
  const fileUploadRef = ref<InstanceType<typeof FileUpload> | null>(null)
  const uploadedFiles = ref<Array<{content: string, filename: string, content_type: string, size: number}>>([])
  // Generated media already lives in canonical FileAttachment rows. The
  // composer adopts those IDs instead of uploading/copying the bytes again.
  const existingAttachmentIds = ref<number[]>([])

  const adoptExistingAttachment = (attachmentId: number) => {
    if (!existingAttachmentIds.value.includes(attachmentId)) {
      existingAttachmentIds.value.push(attachmentId)
    }
  }

  // Handle file uploads
  const handleFilesUploaded = (files: Array<{content: string, filename: string, content_type: string, size: number}>) => {
    uploadedFiles.value = files
  }

  const handleFileUploadError = (error: string) => {
    console.error('File upload error:', error)
  }

  // Handle paste events for screenshots
  const handleChatPaste = (event: ClipboardEvent) => {
    if (fileUploadRef.value) {
      fileUploadRef.value.handlePaste(event)
    }
  }

  // Wrapper to send message with attachments. One explicit user action owns
  // one stable intent ID retained until persistence ACK, including reconnect replay.
  const handleSendMessageWithAttachments = async (options?: SendCompositionOptions) => {
    if (!newMessage.value.trim() && uploadedFiles.value.length === 0 && existingAttachmentIds.value.length === 0) return
    if (!canSendMessage.value) return

    const clientSendIntentId = crypto.randomUUID()
    const sessionId = currentChat.value.session_id
    const messageText = newMessage.value
    const timestamp = new Date().toISOString()
    const files = uploadedFiles.value.map(f => ({
      content: f.content,
      filename: f.filename,
      content_type: f.content_type,
      size: f.size
    }))
    const localMessage: any = {
      client_send_intent_id: clientSendIntentId,
      message: messageText,
      message_type: 'agent',
      created_at: timestamp,
      session_id: sessionId
    }

    // Add temporary attachments for immediate display.
    if (files.length > 0) {
      localMessage.attachments = files.map((file, idx) => {
        let tempUrl = ''
        if (file.content_type.startsWith('image/') ||
            file.content_type.startsWith('audio/') ||
            file.content_type.startsWith('video/')) {
          const byteCharacters = atob(file.content)
          const byteNumbers = new Array(byteCharacters.length)
          for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i)
          }
          const byteArray = new Uint8Array(byteNumbers)
          const blob = new Blob([byteArray], { type: file.content_type })
          tempUrl = URL.createObjectURL(blob)
        }

        return {
          id: Date.now() * 1000 + idx,
          filename: file.filename,
          file_url: tempUrl,
          content_type: file.content_type,
          file_size: file.size,
          _isTemporary: true
        }
      })
    }

    currentChat.value.messages.push(localMessage)
    currentChat.value.updated_at = timestamp
    newMessage.value = ''

    // The payload is captured before UI cleanup. Every inline/reconnect replay in
    // emitWithPersistenceAck reuses this exact logical envelope and intent ID.
    const payload: Record<string, unknown> = {
      client_send_intent_id: clientSendIntentId,
      message: messageText,
      session_id: sessionId,
      message_type: 'agent',
      created_at: timestamp,
      files,
      attachment_ids: [...existingAttachmentIds.value],
    }
    if (options?.translationPairing) {
      payload.translation_pairing = options.translationPairing
    }

    if (uploadedFiles.value.length > 0) {
      fileUploadRef.value?.clearFiles()
      uploadedFiles.value = []
    }
    existingAttachmentIds.value = []
    followLatestIfPinned()

    try {
      const ack = await socketService.emitWithPersistenceAck<{
        status?: string
        client_send_intent_id?: string
        message_id?: number
        reason?: string
      }>('agent_message', payload)

      if (!ack || ack.client_send_intent_id !== clientSendIntentId) {
        throw new Error('Mismatched client send acknowledgement')
      }
      if (ack.status !== 'accepted' || ack.message_id == null) {
        localMessage.attributes = {
          ...(localMessage.attributes || {}),
          delivery_status: 'failed',
          client_send_error: ack.reason || 'send_rejected',
        }
        throw new Error(ack.reason || 'Send rejected')
      }

      // Reconcile the optimistic row by stable intent identity, never content,
      // timestamp or position guessing.
      localMessage.id = ack.message_id
    } catch (err) {
      console.error('Failed to send message:', err)
    }
  }

  // Format file size for display
  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  // Check if attachment is an image
  const isImageAttachment = (contentType: string): boolean => {
    return contentType.startsWith('image/')
  }

  const isAudioAttachment = (contentType: string): boolean => {
    return contentType.startsWith('audio/')
  }

  const isVideoAttachment = (contentType: string): boolean => {
    return contentType.startsWith('video/')
  }

  // Generate download URL for attachments
  const getDownloadUrl = (fileUrl: string | undefined | null): string => {
    if (!fileUrl) return ''
    
    // If it's a blob URL (temporary), return as-is
    if (fileUrl.startsWith('blob:')) {
      return fileUrl
    }
    
    // If it's already a full URL (AWS S3), return as-is
    if (fileUrl.startsWith('http://') || fileUrl.startsWith('https://')) {
      return fileUrl
    }
    
    // Already a full download path (carries its own /api/v1) — resolve against
    // the API origin so the prefix isn't emitted twice.
    if (fileUrl.startsWith('/api/v1/files/download/')) {
      return resolveUploadUrl(fileUrl)
    }

    // For local storage, construct the download URL
    // fileUrl format: "/uploads/chat_attachments/org-id/filename.jpg"
    const cleanUrl = fileUrl.startsWith('/uploads/')
                     ? fileUrl.replace('/uploads/', '')
                     : fileUrl.replace('/', '')
    return apiPath(`/files/download/${cleanUrl}`)
  }

  // Inline media uses the same authenticated download owner as explicit
  // downloads. Blob previews and absolute S3 URLs still pass through unchanged.
  const getImageUrl = (fileUrl: string | undefined | null): string => {
    return getDownloadUrl(fileUrl)
  }

  return {
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
  }
}
