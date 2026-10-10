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

export type LeadStage = 'visitor' | 'lead' | 'customer'

export interface PersonProfileAgeObservation {
  value: number
  observed_at?: string | null
  confidence?: number | null
  source_ref?: string | null
}

export interface PersonProfileAvatar {
  url: string
  source_channel?: string | null
  provider_user_id?: string | null
  observed_at?: string | null
  source_ref?: string | null
  confidence?: number | null
}

export interface PersonProfileProjection {
  birth_date?: string | null
  birth_year?: number | null
  age?: number | null
  age_precision?: 'exact' | 'year' | 'observed' | string | null
  age_observation?: PersonProfileAgeObservation | null
  country_code?: string | null
  country?: string | null
  region?: string | null
  city?: string | null
  raw_location?: string | null
  occupation?: string | null
  avatar?: PersonProfileAvatar | null
}

export interface PersonListItem {
  id: string
  name?: string | null
  email?: string | null
  phone?: string | null
  is_anonymous: boolean
  lead_stage: LeadStage
  qualified: boolean
  source?: Record<string, any> | null
  captured_at?: string | null
  last_activity?: string | null
  synced: boolean
  profile?: PersonProfileProjection | null
}

export interface PeopleListResponse {
  items: PersonListItem[]
  total: number
  page: number
  page_size: number
}

export interface PeopleStats {
  total_people: number
  /** Engaged-but-unidentified sessions — the count behind the Anonymous tab */
  anonymous: number
  new_leads_7d: number
  customers: number
  synced_to_crm: number
}

export interface TimelineEntry {
  stage: string
  at: string
}

export interface PersonConversation {
  session_id: string
  agent_name?: string | null
  status?: string | null
  last_message?: string | null
  created_at?: string | null
}

export interface PersonDetail {
  id: string
  name?: string | null
  email?: string | null
  phone?: string | null
  /** Real email, phone, or qualifying capture — gates person actions */
  identified: boolean
  is_anonymous: boolean
  lead_stage: LeadStage
  qualified: boolean
  source?: Record<string, any> | null
  created_at?: string | null
  lead_qualified_at?: string | null
  meta_data?: Record<string, any> | null
  profile?: PersonProfileProjection | null
  summary?: string | null
  captured_attributes: Record<string, any>
  timeline: TimelineEntry[]
  conversations: PersonConversation[]
}

export type RelationshipMemoryKind =
  | 'fact'
  | 'note'
  | 'event'
  | 'interest'
  | 'shared_moment'
  | 'open_loop'
  | 'promise'
  | 'boundary'
  | 'sensitive_topic'

export type RelationshipMemoryEffect = 'context' | 'no_reply' | 'defer'

export interface RelationshipEvidence {
  source_type: 'chat_history' | 'person_profile' | 'captured_attribute' | 'operator_confirmation'
  source_ref: string
  observed_at?: string | null
  label?: string | null
  session_id?: string | null
}

export interface RelationshipMemoryEntry {
  id: string
  kind: RelationshipMemoryKind
  text: string
  confirmed: boolean
  active: boolean
  effect: RelationshipMemoryEffect
  occurred_at?: string | null
  created_at: string
  updated_at: string
  evidence: RelationshipEvidence[]
}

export interface RelationshipMetrics {
  stage: 'unknown' | 'new' | 'developing' | 'established'
  momentum: 'unknown' | 'rising' | 'steady' | 'quiet' | 'cooling'
  temperature: 'unknown' | 'warm' | 'neutral' | 'cool'
  risk: 'unknown' | 'low' | 'watch' | 'elevated'
  message_count: number
  session_count: number
  active_days: number
  last_interaction_at?: string | null
  last_inbound_at?: string | null
  last_outbound_at?: string | null
  basis: string[]
}

export interface RelationshipTemporalProjection {
  operator_timezone: string
  contact_timezone?: string | null
  contact_timezone_known: boolean
  effective_timezone: string
  precision: 'contact' | 'operator_fallback'
  local_time: string
  daypart: 'morning' | 'afternoon' | 'evening' | 'night'
  preferred_contact_start?: string | null
  preferred_contact_end?: string | null
  defer_recommended: boolean
  defer_until?: string | null
  defer_reason?: string | null
}

export interface RelationshipGoalProjection {
  current?: string | null
  long_term?: string | null
  source_refs: string[]
}

export interface RelationshipDecision {
  action: 'reply' | 'defer' | 'no_reply' | 'next_action'
  next_best_action: string
  why_now: string[]
  defer_until?: string | null
}

export interface RelationshipContextProjection {
  customer_id: string
  generated_at: string
  confirmed_facts: RelationshipMemoryEntry[]
  notes: RelationshipMemoryEntry[]
  dated_events: RelationshipMemoryEntry[]
  interests: RelationshipMemoryEntry[]
  shared_moments: RelationshipMemoryEntry[]
  open_loops: RelationshipMemoryEntry[]
  promises: RelationshipMemoryEntry[]
  boundaries: RelationshipMemoryEntry[]
  sensitive_topics: RelationshipMemoryEntry[]
  relationship: RelationshipMetrics
  temporal: RelationshipTemporalProjection
  goals: RelationshipGoalProjection
  decision: RelationshipDecision
  evidence_review: RelationshipEvidence[]
  journey: Array<Record<string, any>>
  graph_owner_status: 'not_required' | 'optional_held'
  graph_owner_reason: string
}

export interface RelationshipMemoryUpsert {
  id?: string
  kind: RelationshipMemoryKind
  text: string
  active?: boolean
  effect?: RelationshipMemoryEffect
  occurred_at?: string | null
  source_refs?: string[]
}

export interface RelationshipTemporalSettings {
  contact_timezone?: string | null
  preferred_contact_start?: string | null
  preferred_contact_end?: string | null
}
