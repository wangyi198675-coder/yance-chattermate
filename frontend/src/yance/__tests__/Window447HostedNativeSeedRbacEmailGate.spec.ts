import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'e2e/quality/hosted-native-seed.py'), 'utf8')

describe('W447 real hosted Windows native QA seed safety', () => {
  it('requires the actual hosted isolated PostgreSQL runner and does not soften provenance gates', () => {
    expect(source).toContain('GITHUB_ACTIONS')
    expect(source).toContain('RUNNER_OS')
    expect(source).toContain('NATIVE_POSTGRES_AUTH')
    expect(source).toContain('yance_hosted_qa')
    expect(source).toContain('QA_SEED_REQUIRES_GITHUB_HOSTED_ISOLATED_NATIVE_POSTGRES')
  })
  it('initializes the existing ChatterMate permission catalog instead of fabricating an unprivileged Admin', () => {
    expect(source).toContain('Permission.default_permissions()')
    expect(source).toContain('role.permissions = list(catalog.values())')
    expect(source).toContain('HOSTED_QA_NATIVE_PERMISSION_CATALOG_INCOMPLETE')
    expect(source).toContain('"super_admin" not in catalog')
    expect(source).toContain('"manage_organization" not in catalog')
  })
  it('uses schema-valid isolated fixture mailboxes and canonical ORM identity', () => {
    expect(source).toContain('@example.com')
    expect(source).not.toContain('@example.invalid')
    for (const owner of ['Organization(', 'User(', 'Customer(', 'SessionToAgent(', 'ChatHistory(']) {
      expect(source).toContain(owner)
    }
    expect(source).toContain('YANCE_QA_SYNTHETIC_PASSWORD')
  })
  it('creates joinable native Agent, two distinct Customers and ChatHistory rows in the real isolated ORM', () => {
    for (const fragment of [
      'from app.models.agent import Agent, AgentType',
      'agent = Agent(',
      'ai_replies_enabled=False',
      'agent_id=agent.id',
      'second_customer = Customer(',
      'second_session = uuid.uuid4()',
      'second_message = ChatHistory(',
      '"second_message":str(second_message.id)',
    ]) expect(source).toContain(fragment)
  })
})
