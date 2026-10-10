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

import type { PersonProfileProjection } from './people'

export interface CustomerInfo {
  id: string
  email: string
  full_name?: string
  // Integrator-supplied fields (e.g. student_name, center_name) set via
  // POST /generate-token's `custom_data`.
  meta_data?: Record<string, unknown>
  profile?: PersonProfileProjection | null
}

export interface Message {
  id?: number
  client_send_intent_id?: string
  message?: string
  message_type: string
  created_at: string
  session_id: string
  // Live replies are revealed client-side with a typewriter effect.
  stream?: boolean
  attributes?: Record<string, any>
  user_name?: string
  agent_name?: string
  end_chat?: boolean
  end_chat_reason?: string
  end_chat_description?: string
  attachments?: Array<{
    id: number
    filename: string
    file_url: string
    content_type: string
    file_size: number
  }>
  
  // Updated shopify_output to match Conversation structure
  shopify_output?: {
    products: Array<{
      id: string
      title: string
      price: string
      image?: ShopifyProductImage // Reuse existing ShopifyProductImage type
    }>
  }

  // Knowledge-base citations used to ground this message (rendered as source chips)
  sources?: Array<{ name: string; type: string }>
}

export interface ShopifyProductImage {
    src?: string
    alt?: string
}

export interface ConversationState {
  followed: boolean
  favourite: boolean
  archived: boolean
  last_read_message_id: number | null
}

export interface ConversationStatePatch {
  followed?: boolean
  favourite?: boolean
  archived?: boolean
  mark_read?: boolean
}

export interface Conversation {
  customer: CustomerInfo
  agent: {
    id: string
    name: string
    display_name: string | null
    /** False when this agent never answers with AI — its chats wait for a person. */
    ai_replies_enabled?: boolean
  }
  last_message: string | null
  /** Canonical ChatHistory identity for the rail preview when supplied by an admitted projection source. */
  last_message_id?: number | string | null
  updated_at: string
  message_count: number
  session_id: string
  user_id: string | null
  /** Human agent holding the chat; absent while the AI still has it. */
  user_name?: string | null
  group_id?: string | null
  status: 'open' | 'closed' | 'transferred'
  channel?: string
  followed?: boolean
  favourite?: boolean
  archived?: boolean
  last_read_message_id?: number | null
  unread_count?: number
  attributes?: {
    message_type?: string
    shopify_output?: {
      products: Array<{
        id: string
        title: string
        price: string
        image?: {
          src: string
          alt?: string
        }
      }>
    }
  }
}

export interface ChatHistoryCursor {
  created_at: string
  id: number
}

export interface ChatMessagePage {
  messages: Message[]
  has_more: boolean
  next_cursor: ChatHistoryCursor | null
}

export interface ChatDetail {
  customer: CustomerInfo
  agent: {
    id: string
    name: string
    display_name: string | null
    /** False when this agent never answers with AI — its chats wait for a person. */
    ai_replies_enabled?: boolean
  }
  session_id: string
  messages: Message[]
  has_older?: boolean
  older_cursor?: ChatHistoryCursor | null
  created_at: string
  updated_at: string
  user_id: string | null
  user_name?: string | null
  group_id: string | null
  status: 'open' | 'transferred' | 'closed'
  channel?: string
  /** The connected account this conversation arrived on; absent for web chats. */
  channel_account_id?: string | null
  followed?: boolean
  favourite?: boolean
  archived?: boolean
  last_read_message_id?: number | null
}
