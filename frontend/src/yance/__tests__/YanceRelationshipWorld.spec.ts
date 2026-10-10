import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const {
  getPerson,
  getRelationshipContext,
  putRelationshipMemory,
  patchRelationshipTemporal,
  push,
  routeParams,
} = vi.hoisted(() => ({
  getPerson: vi.fn(),
  getRelationshipContext: vi.fn(),
  putRelationshipMemory: vi.fn(),
  patchRelationshipTemporal: vi.fn(),
  push: vi.fn(),
  routeParams: { customerId: 'customer-1' as string },
}))

vi.mock('@/services/people', () => ({
  peopleService: {
    getPerson,
    getRelationshipContext,
    putRelationshipMemory,
    patchRelationshipTemporal,
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: routeParams }),
  useRouter: () => ({ push }),
}))

vi.mock('@/layouts/DashboardLayout.vue', () => ({
  default: { template: '<div class="dashboard-stub"><slot /></div>' },
}))

vi.mock('@/components/people/CustomerAvatar.vue', () => ({
  default: {
    props: ['displayName'],
    template: '<div class="avatar-stub">{{ displayName }}</div>',
  },
}))

import YanceRelationshipWorld from '../YanceRelationshipWorld.vue'

function personFixture() {
  return {
    id: 'customer-1',
    name: 'Hans Müller',
    email: 'hans@example.test',
    phone: '+491234',
    identified: true,
    is_anonymous: false,
    lead_stage: 'customer',
    qualified: true,
    source: { type: 'messenger' },
    created_at: '2026-10-01T08:00:00Z',
    lead_qualified_at: null,
    meta_data: {},
    profile: {
      city: 'Berlin',
      country: 'Germany',
      age: 44,
      age_precision: 'exact',
      occupation: 'Engineer',
      age_observation: {
        value: 44,
        observed_at: '2026-10-03T08:00:00Z',
        source_ref: 'message-42',
      },
      avatar: {
        url: 'https://example.test/hans.jpg',
        source_channel: 'messenger',
        observed_at: '2026-10-04T08:00:00Z',
        source_ref: 'psid-1',
      },
    },
    summary: null,
    captured_attributes: {},
    timeline: [
      { stage: 'customer', at: '2026-10-02T08:00:00Z' },
    ],
    conversations: [
      {
        session_id: 'session-1',
        agent_name: 'Agent',
        status: 'open',
        last_message: 'Bis später',
        created_at: '2026-10-05T08:00:00Z',
      },
    ],
  }
}

function relationshipFixture() {
  return {
    customer_id: 'customer-1',
    generated_at: '2026-10-07T12:00:00Z',
    confirmed_facts: [],
    notes: [{
      id: 'note-1',
      kind: 'note',
      text: 'Prefers concise messages',
      confirmed: true,
      active: true,
      effect: 'context',
      occurred_at: null,
      created_at: '2026-10-06T12:00:00Z',
      updated_at: '2026-10-06T12:00:00Z',
      evidence: [{
        source_type: 'chat_history',
        source_ref: 'chat_history:42',
        observed_at: '2026-10-06T12:00:00Z',
        label: 'user',
        session_id: 'session-1',
      }],
    }],
    dated_events: [],
    interests: [],
    shared_moments: [],
    open_loops: [],
    promises: [],
    boundaries: [],
    sensitive_topics: [],
    relationship: {
      stage: 'developing',
      momentum: 'steady',
      temperature: 'neutral',
      risk: 'low',
      message_count: 8,
      session_count: 1,
      active_days: 3,
      last_interaction_at: '2026-10-07T11:00:00Z',
      last_inbound_at: '2026-10-07T11:00:00Z',
      last_outbound_at: '2026-10-07T10:00:00Z',
      basis: ['chat_history_messages:8'],
    },
    temporal: {
      operator_timezone: 'Europe/Berlin',
      contact_timezone: 'Europe/Berlin',
      contact_timezone_known: true,
      effective_timezone: 'Europe/Berlin',
      precision: 'contact',
      local_time: '2026-10-07T14:00:00+02:00',
      daypart: 'afternoon',
      preferred_contact_start: '08:00',
      preferred_contact_end: '22:00',
      defer_recommended: false,
      defer_until: null,
      defer_reason: null,
    },
    goals: { current: null, long_term: null, source_refs: [] },
    decision: {
      action: 'reply',
      next_best_action: 'Reply to the latest inbound message.',
      why_now: ['latest_canonical_message_is_inbound'],
      defer_until: null,
    },
    evidence_review: [],
    journey: [],
    graph_owner_status: 'optional_held',
    graph_owner_reason: 'Graph memory is optional.',
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  routeParams.customerId = 'customer-1'
  getPerson.mockResolvedValue(personFixture())
  getRelationshipContext.mockResolvedValue(relationshipFixture())
})

describe('YanceRelationshipWorld', () => {
  it('reads the canonical Person projection and exposes only its confirmed facts', async () => {
    const wrapper = mount(YanceRelationshipWorld)
    await flushPromises()

    expect(getPerson).toHaveBeenCalledTimes(1)
    expect(getPerson).toHaveBeenCalledWith('customer-1')

    const facts = wrapper.get('[data-relationship-facts]')
    expect(facts.text()).toContain('Hans Müller')
    expect(facts.text()).toContain('Berlin · Germany')
    expect(facts.text()).toContain('44岁')
    expect(facts.text()).toContain('Engineer')
    expect(facts.attributes('data-truth-kind')).toBe('fact')
  })

  it('projects evidence-governed relationship context without inventing inference', async () => {
    const wrapper = mount(YanceRelationshipWorld)
    await flushPromises()

    expect(getRelationshipContext).toHaveBeenCalledWith('customer-1')
    const memory = wrapper.get('[data-relationship-memory]')
    const insight = wrapper.get('[data-relationship-derived-insight]')
    const runtime = wrapper.get('[data-relationship-runtime-state="ready"]')

    expect(memory.text()).toContain('Prefers concise messages')
    expect(memory.text()).toContain('chat_history:42')
    expect(insight.text()).toContain('发展中')
    expect(insight.text()).toContain('Reply to the latest inbound message.')
    expect(runtime.exists()).toBe(true)
    expect(wrapper.text()).toContain('没有证据的 AI 推测不会自动写成人物事实')
    expect(wrapper.text()).not.toContain('58/100')
    expect(wrapper.text()).not.toContain('朋友 · 专业交流为主')
  })

  it('projects existing provenance and conversation evidence without inventing a relationship store', async () => {
    const wrapper = mount(YanceRelationshipWorld)
    await flushPromises()

    const evidence = wrapper.get('[data-relationship-evidence]')
    expect(evidence.attributes('data-truth-kind')).toBe('evidence')
    expect(evidence.text()).toContain('年龄资料来源')
    expect(evidence.text()).toContain('message-42')
    expect(evidence.text()).toContain('人物状态记录')
    expect(evidence.text()).toContain('对话记录')
    expect(evidence.text()).toContain('Bis später')

    const openConversation = evidence.findAll('button').find((button) => button.text() === '查看对话')
    expect(openConversation).toBeTruthy()
    await openConversation!.trigger('click')
    expect(push).toHaveBeenCalledWith({ path: '/yance', query: { session: 'session-1' } })
  })

  it('does not create a shadow directory when no person is selected', async () => {
    routeParams.customerId = ''
    const wrapper = mount(YanceRelationshipWorld)
    await flushPromises()

    expect(getPerson).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('选择一个人物')
    expect(wrapper.text()).toContain('打开人物目录')
  })
})
