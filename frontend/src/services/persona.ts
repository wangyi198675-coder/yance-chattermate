import api from './api'

export type PersonaScope = 'global' | 'contact' | 'conversation' | 'turn'

export type PersonaSeed = {
  seed_id: string
  name: string
  format: 'character-card-v2' | 'character-card-v3'
  compatibility: string
  identity_facts: Record<string, string>
  style_traits: Record<string, string>
  relationship_rules: Record<string, string>
  examples: string[]
  provenance: string
  consent: true
}

export type PersonaProjection = {
  agent_id: string
  base_persona: string[]
  effective_persona: string[]
  effective_scope: PersonaScope | 'global'
  contact_override?: Record<string, unknown> | null
  conversation_override?: Record<string, unknown> | null
  matched_guidelines: Array<Record<string, unknown>>
  identity_facts: Record<string, unknown>
  style_traits: Record<string, unknown>
  relationship_rules: Record<string, unknown>
  owner_contract: Record<string, string>
}

export type StyleFeature = {
  feature: string
  value: string
  confidence: number
  evidence_ids: string[]
  provenance: string[]
  review_status: 'proposed'
}

export type PersonaHistoryVersion = {
  transaction_id: number
  instructions: string[]
}

const personaAgentPath = (agentId: string) => '/yance/persona/agents/' + agentId

export const personaService = {
  async projection(agentId: string, customerId?: string, sessionId?: string) {
    const { data } = await api.get<PersonaProjection>(personaAgentPath(agentId), {
      params: {
        customer_id: customerId || undefined,
        session_id: sessionId || undefined,
      },
    })
    return data
  },

  async updateBase(agentId: string, instructions: string[]) {
    const { data } = await api.put(personaAgentPath(agentId) + '/base', { instructions })
    return data as { updated: true; owner: 'Agent.instructions'; instructions: string[] }
  },

  async importSeed(agentId: string, card: Record<string, unknown>, provenance: string, consent: boolean) {
    const { data } = await api.post<PersonaSeed>(personaAgentPath(agentId) + '/seeds/import', {
      card,
      provenance,
      consent,
    })
    return data
  },

  async seeds(agentId: string) {
    const { data } = await api.get<{ seeds: PersonaSeed[] }>(personaAgentPath(agentId) + '/seeds')
    return data.seeds
  },

  async compare(agentId: string, seedIds: string[]) {
    const { data } = await api.post<{ seeds: PersonaSeed[]; dimensions: string[] }>(
      personaAgentPath(agentId) + '/seeds/compare',
      { seed_ids: seedIds },
    )
    return data
  },

  async select(
    agentId: string,
    payload: {
      seed_id: string
      scope: PersonaScope
      customer_id?: string
      session_id?: string
    },
  ) {
    const { data } = await api.post(personaAgentPath(agentId) + '/seeds/select', payload)
    return data as {
      scope: PersonaScope
      persisted: boolean
      seed_id: string
      seed_name: string
      instructions: string[]
      identity_facts: Record<string, unknown>
      style_traits: Record<string, unknown>
      relationship_rules: Record<string, unknown>
      provenance: string
      format: string
    }
  },

  async clearScope(
    agentId: string,
    payload: { scope: 'contact' | 'conversation'; customer_id?: string; session_id?: string },
  ) {
    const { data } = await api.post(personaAgentPath(agentId) + '/scope/clear', payload)
    return data
  },

  async addStyleText(
    agentId: string,
    payload: {
      title: string
      content: string
      provenance: string
      consent: boolean
      source_kind: string
    },
  ) {
    const { data } = await api.post(personaAgentPath(agentId) + '/style-text', payload)
    return data
  },

  async markStyleSource(
    agentId: string,
    knowledgeId: number,
    payload: { provenance: string; consent: boolean; source_kind: string },
  ) {
    const { data } = await api.post(
      personaAgentPath(agentId) + '/style-sources/' + knowledgeId,
      payload,
    )
    return data
  },

  async extractStyle(agentId: string) {
    const { data } = await api.post<{ features: StyleFeature[]; evidence_count: number; persisted: false }>(
      personaAgentPath(agentId) + '/style-extract',
    )
    return data
  },

  async guidelines(agentId: string) {
    const { data } = await api.get<{ guidelines: Array<Record<string, unknown>> }>(
      personaAgentPath(agentId) + '/guidelines',
    )
    return data.guidelines
  },

  async reviewGuideline(
    agentId: string,
    payload: {
      decision: 'adopt' | 'edit' | 'reject'
      condition: string
      action: string
      description?: string
      confidence: number
      evidence_ids: string[]
      provenance: string
    },
  ) {
    const { data } = await api.post(personaAgentPath(agentId) + '/guidelines/review', payload)
    return data
  },

  async history(agentId: string) {
    const { data } = await api.get<{ versions: PersonaHistoryVersion[] }>(
      personaAgentPath(agentId) + '/history',
    )
    return data.versions
  },

  async rollback(agentId: string, transactionId: number) {
    const { data } = await api.post(
      personaAgentPath(agentId) + '/history/' + transactionId + '/rollback',
    )
    return data
  },
}
