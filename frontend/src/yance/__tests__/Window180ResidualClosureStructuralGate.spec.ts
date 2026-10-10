import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')

describe('Window180 residual model/system/export/companion structural gate', () => {
  it('keeps fallback and reasoning inside AIConfig -> Agno native owners', () => {
    const catalog = read('../../../../backend/app/core/model_catalog.py')
    const aiSetup = read('../../../../backend/app/api/ai_setup.py')
    const agent = read('../../../../backend/app/agents/chat_agent.py')
    const agno = read('../../../../backend/app/utils/agno_utils.py')
    expect(catalog).toContain('_m("o4-mini", "o4-mini", ["low", "medium", "high"])')
    expect(aiSetup).toContain('fallback_model_name')
    expect(aiSetup).toContain('reasoning_strength')
    expect(agent).toContain('fallback_models=fallback_models')
    expect(agno).toContain('kwargs["reasoning_effort"] = reasoning_strength')
  })

  it('exports only canonical ChatHistory and FileAttachment projection', () => {
    const chat = read('../../../../backend/app/api/chat.py')
    expect(chat).toContain('@router.get("/{session_id}/export")')
    expect(chat).toContain('history = await chat_repo.get_session_history(session_id_uuid)')
    expect(chat).toContain('"attachments": [')
    expect(chat).not.toMatch(/ExportRecord|export_db|shadow export/i)
  })

  it('projects mature runtime owners without adding a second monitor or updater', () => {
    const settings = read('../YanceSettingsNativeComposition.vue')
    expect(settings).toContain('PostgreSQL pg_dump + restic 0.19.1')
    expect(settings).toContain('data-native-owner="Velopack"')
    expect(settings).toContain('data-native-owner="browser_profile_enrichment"')
    expect(settings).toContain('data-native-owner="backend /health"')
    expect(settings).toContain('PACKAGE_UAT_HOLD')
  })

  it('allows the Window205 descendant to close follow/archive on the canonical session owner', () => {
    const list = read('../../components/conversations/ConversationsList.vue')
    expect(list).toContain('data-yance-follow-action')
    expect(list).toContain('data-yance-archive-action')
    expect(list).toContain('SessionToAgent.is_followed')
    expect(list).toContain('SessionToAgent.is_archived')
    expect(list).not.toMatch(/localStorage[^\n]*(?:follow|archive)/i)
  })
})
