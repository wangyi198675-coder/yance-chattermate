import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(HERE, '../..')

const SURFACES = [
  'views/PeopleView.vue',
  'components/people/PersonDetailDrawer.vue',
  'yance/YanceHomeNativeComposition.vue',
  'components/conversations/ConversationsList.vue',
  'components/conversations/ConversationChat.vue',
  'components/conversations/ChatInfoPanel.vue',
] as const

function source(rel: string): string {
  return readFileSync(resolve(SRC, rel), 'utf8')
}

describe('Window 34 canonical avatar owner gate', () => {
  it('routes every frozen contact surface through the same CustomerAvatar primitive', () => {
    for (const rel of SURFACES) {
      expect(source(rel), rel).toContain('CustomerAvatar')
      expect(source(rel), rel).toContain('@/components/people/CustomerAvatar.vue')
    }
  })

  it('keeps avatar URL parsing and load-failure ownership out of page components', () => {
    for (const rel of SURFACES) {
      const text = source(rel)
      expect(text, rel).not.toContain('personProfileAvatarUrl')
      expect(text, rel).not.toContain('failedAvatarIds')
      expect(text, rel).not.toContain('avatarFailed')
    }
  })

  it('binds list, header and info hero to the projected customer.profile field', () => {
    const files = [
      'components/conversations/ConversationsList.vue',
      'components/conversations/ConversationChat.vue',
      'components/conversations/ChatInfoPanel.vue',
    ]
    for (const rel of files) {
      expect(source(rel), rel).toMatch(/:profile="(?:conv|currentChat|chatInfo)\.customer\.profile"/)
    }
  })

  it('does not reactivate the dormant standalone Yance contact rail owner', () => {
    const activeHost = source('yance/YanceNativeHostView.vue')
    expect(activeHost).not.toContain('YanceShellView')
  })
})
