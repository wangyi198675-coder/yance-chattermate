import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import YanceShellView from '@/yance/YanceShellView.vue'

describe('Yance clean rebase shell', () => {
  it('preserves the frozen conversation header and composer order', () => {
    const wrapper = mount(YanceShellView)
    const header = wrapper.get('[data-yance="conversation-header"]').text()
    const expected = ['返回首页', '联系人', '人格', '回复模式', '模型/推理', '闺蜜大脑']
    let cursor = -1
    for (const label of expected) {
      const next = header.indexOf(label)
      expect(next).toBeGreaterThan(cursor)
      cursor = next
    }
    const composer = wrapper.get('[data-yance="composer"]').text()
    for (const label of ['+', '发送消息…', '真人打字·自然', '发送并学习']) {
      expect(composer).toContain(label)
    }
  })

  it('starts Reply Brain collapsed and Girlfriend Brain off without spec annotations', () => {
    const wrapper = mount(YanceShellView)
    expect(wrapper.get('[data-yance="reply-brain-toggle"]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-yance="reply-brain-panel"]').exists()).toBe(false)
    expect(wrapper.get('[data-yance="girlfriend-toggle"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.find('[data-yance="girlfriend-overlay"]').exists()).toBe(false)
    const text = wrapper.text()
    for (const forbidden of ['GLOBAL_UI_DESIGN', '152/152', 'UIE-', 'Final Accepted']) {
      expect(text).not.toContain(forbidden)
    }
  })
  it('exposes shell controls as integration events instead of dead buttons', async () => {
    const wrapper = mount(YanceShellView)
    const clickText = async (text: string) => {
      const button = wrapper.findAll('button').find((item) => item.text() === text)
      expect(button, `missing button: ${text}`).toBeTruthy()
      await button!.trigger('click')
    }

    await clickText('联系人')
    await clickText('人格')
    await clickText('回复模式')
    await clickText('模型/推理')
    expect(wrapper.emitted('open-control')?.map((args) => args[0])).toEqual([
      'contact', 'persona', 'reply-mode', 'model-reasoning',
    ])

    await wrapper.get('button[aria-label="最小化"]').trigger('click')
    expect(wrapper.emitted('window-action')?.[0]).toEqual(['minimize'])

    await clickText('+')
    await clickText('真人打字·自然 ▾')
    await clickText('发送并学习 ▾')
    expect(wrapper.emitted('composer-action')?.map((args) => args[0])).toEqual([
      'attach', 'typing-style', 'send-and-learn',
    ])

    await clickText('未读')
    const unread = wrapper.findAll('button').find((item) => item.text() === '未读')
    expect(unread?.attributes('aria-pressed')).toBe('true')
  })
  it('emits mature-owner route metadata from existing frozen controls', async () => {
    const wrapper = mount(YanceShellView)
    const clickText = async (text: string) => {
      const button = wrapper.findAll('button').find((item) => item.text() === text)
      expect(button, `missing button: ${text}`).toBeTruthy()
      await button!.trigger('click')
    }

    await clickText('联系人')
    await clickText('模型/推理')
    await wrapper.get('[data-yance="reply-brain-toggle"]').trigger('click')
    await wrapper.get('button[aria-label="添加附件"]').trigger('click')
    await clickText('发送并学习 ▾')

    expect(wrapper.emitted('capability-route')?.map((args) => args[0])).toEqual([
      { surface: 'girlfriend', action: 'find_contact' },
      { surface: 'girlfriend', action: 'model_selection' },
      { surface: 'reply', action: 'candidate_generation' },
      { surface: 'reply', action: 'file_attachment' },
      { surface: 'reply', action: 'final_send' },
    ])
  })

})
