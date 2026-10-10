import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8').replace(/\r\n/g, '\n')

describe('Window205 Window180 residual mature-owner closure', () => {
  it('closes S02 on native UserNotificationSettings through the existing FCM path', () => {
    const model = read('../../../../backend/app/models/notification_settings.py')
    const schema = read('../../../../backend/app/models/schemas/notification.py')
    const push = read('../../../../backend/app/services/user.py')
    const sw = read('../../sw.ts')
    const settings = read('../../components/user/UserSettings.vue')

    expect(model).toContain('sound_enabled = Column(Boolean')
    expect(schema).toContain('sound_enabled: bool')
    expect(push).toContain("'sound_enabled': 'true' if sound_enabled else 'false'")
    expect(sw).toContain("silent: payload.data?.sound_enabled === 'false'")
    expect(settings).toContain("key: 'sound_enabled'")
    expect([model, schema, push, sw, settings].join('\n')).not.toMatch(/localStorage[^\n]*sound/i)
  })

  it('closes S07 on canonical SessionToAgent + ChatHistory without a second state store', () => {
    const session = read('../../../../backend/app/models/session_to_agent.py')
    const repo = read('../../../../backend/app/repositories/session_to_agent.py')
    const chatApi = read('../../../../backend/app/api/chat.py')
    const chatRepo = read('../../../../backend/app/repositories/chat.py')
    const list = read('../../components/conversations/ConversationsList.vue')

    expect(session).toContain('is_followed = Column(Boolean')
    expect(session).toContain('is_favourite = Column(Boolean')
    expect(session).toContain('is_archived = Column(Boolean')
    expect(session).toContain('last_read_message_id = Column(Integer')
    expect(repo).toContain("ChatHistory.message_type == 'user'")
    expect(chatApi).toContain('@router.patch("/{session_id}/inbox-state"')
    expect(chatRepo).toContain("label('unread_count')")
    expect(list).toContain('data-native-state="SessionToAgent.is_followed"')
    expect(list).toContain('data-native-state="SessionToAgent.is_archived"')
    expect(list).not.toMatch(/localStorage[^\n]*(?:follow|favourite|favorite|archive|read)/i)
  })

  it('keeps the schema seam bounded and attached to the existing Alembic head', () => {
    const migration = read('../../../../backend/alembic/versions/window205_owner_seam_001.py')
    expect(migration).toContain('down_revision = "file_attachment_identity_metadata_001"')
    expect(migration).toContain('op.add_column(\n        "user_notification_settings"')
    expect(migration).toContain('op.add_column(\n        "session_to_agents"')
    expect(migration).not.toMatch(/create_table|YanceMediaDB|yance_settings|conversation_state/i)
  })
})
