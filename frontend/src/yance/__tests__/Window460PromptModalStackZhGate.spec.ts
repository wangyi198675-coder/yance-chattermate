import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8')
const tokens = read('src/assets/styles/design-tokens.css')
const prompt = read('src/components/notifications/EnablePushPrompt.vue')
const ticket = read('src/components/tickets/TicketCreateModal.vue')

describe('W460 native ticket modal and push-prompt z-order and Chinese', () => {
  it('uses the existing higher modal layer so notification onboarding cannot intercept ticket creation', () => {
    const value = (name: string) => Number(tokens.match(new RegExp(`--z-${name}:\\s*(\\d+)`))?.[1])
    expect(value('modal')).toBeGreaterThan(value('prompt'))
    expect(ticket).toContain('z-index: var(--z-modal);')
    expect(prompt).toContain('z-index: var(--z-prompt);')
    expect(ticket).not.toContain('z-index: 100;')
  })
  it('localizes notification onboarding while preserving snooze and real user-gesture permission request', () => {
    for (const label of ['开启通知','安装后接收通知','将 ChatterMate 添加到主屏幕','客户需要你时及时收到通知','暂不','知道了'])
      expect(prompt).toContain(label)
    for (const english of ['Get notified when a customer needs you','Enable notifications','Not now','Install to get notifications'])
      expect(prompt).not.toContain(english)
    expect(prompt).toContain("localStorage.setItem(SNOOZE_KEY, String(Date.now()))")
    expect(prompt).toContain("emit('enable')")
    expect(prompt).toContain("Notification.permission === 'default'")
  })
})
