import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')

describe('Window176 Persona Seed / Style Corpus / Growth structural gate', () => {
  it('turns the Frozen Conversation Persona control into a real current-chat entry', () => {
    const host = read('../YanceNativeHostView.vue')
    expect(host).toContain('data-yance-persona-control')
    expect(host).toContain('data-owner-state="ready"')
    expect(host).toContain('@click="openPersonaStudio(chat)"')
    expect(host).toContain('YancePersonaStudio')
    expect(host).toContain('persona-turn-override')
  })

  it('separates identity facts, style traits and relationship-scoped rules', () => {
    const studio = read('../components/YancePersonaStudio.vue')
    expect(studio).toContain('data-persona-section="identity"')
    expect(studio).toContain('data-persona-section="style"')
    expect(studio).toContain('data-persona-section="relationship"')
    expect(studio).toContain('data-yance-persona-scope')
    expect(studio).toContain('<option value="global">全局</option>')
    expect(studio).toContain('<option value="contact">仅此联系人</option>')
    expect(studio).toContain('<option value="conversation">仅此会话</option>')
    expect(studio).toContain('<option value="turn">仅本轮</option>')
  })

  it('implements import, preview/select, compare, style corpus, review and rollback in one studio', () => {
    const studio = read('../components/YancePersonaStudio.vue')
    for (const marker of [
      'data-yance-character-card-json',
      'data-yance-import-seed',
      'data-yance-select-persona',
      'data-yance-compare-persona',
      'data-yance-style-corpus',
      'data-yance-style-consent',
      'data-yance-extract-style',
      'data-yance-guideline-condition',
      'data-yance-guideline-action',
      'data-yance-persona-history',
    ]) {
      expect(studio).toContain(marker)
    }
    expect(studio).toContain('compareIds.value.length >= 3')
    expect(studio).toContain('我确认有权使用该素材')
    expect(studio).toContain('明确作为风格学习素材')
  })

  it('uses the thin Persona API and no local persistence/router/runtime clone', () => {
    const service = read('../../services/persona.ts')
    expect(service).toContain('/yance/persona/agents/')
    expect(service).toContain('/seeds/import')
    expect(service).toContain('/seeds/compare')
    expect(service).toContain('/style-extract')
    expect(service).toContain('/guidelines/review')
    expect(service).toContain('/history/')
    expect(service).not.toMatch(/localStorage|sessionStorage|indexedDB|defineStore|createPinia/)
  })

  it('upgrades the existing Settings Persona entry instead of creating a second management surface', () => {
    const settings = read('../YanceSettingsNativeComposition.vue')
    expect(settings).toContain("{ id: 'persona', label: '人格与学习'")
    expect(settings).toContain("persona: 'Connected'")
    expect(settings).toContain('data-settings-runtime-state="persona-ready"')
    expect(settings).toContain('data-native-owner="YancePersonaStudio"')
    expect(settings).toContain('to="/yance"')
    expect(settings).not.toContain('data-settings-runtime-state="persona-unavailable"')
  })

  it('keeps explicit owner boundaries visible in product copy', () => {
    const settings = read('../YanceSettingsNativeComposition.vue')
    expect(settings).toContain('Agent.instructions')
    expect(settings).toContain('Knowledge / PgVector')
    expect(settings).toContain('SQLAlchemy-Continuum')
    expect(settings).toContain('SessionToAgent')
    expect(settings).toContain('长期学习按已有记录和明确授权持续完善。')
  })
})
