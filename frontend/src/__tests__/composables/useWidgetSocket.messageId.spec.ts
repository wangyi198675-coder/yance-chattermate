import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

describe('W302 canonical Widget receiver replay', () => {
  type Handler = (...args: any[]) => void
  const handlers = new Map<string, Handler[]>()
  const fire = (event: string, ...args: any[]) =>
    (handlers.get(event) || []).forEach(handler => handler(...args))

  vi.mock('socket.io-client', () => ({
    io: (...args: any[]) => (globalThis as any).__w302SocketFactory(...args)
  }))

  beforeEach(() => {
    handlers.clear()
    localStorage.clear()
    ;(globalThis as any).__w302SocketFactory = () => ({
      active: true,
      connected: true,
      connect: vi.fn(),
      disconnect: vi.fn(),
      emit: vi.fn(),
      removeAllListeners: vi.fn(),
      on: vi.fn((name: string, handler: Handler) => {
        handlers.set(name, [...(handlers.get(name) || []), handler])
      })
    })
  })

  afterEach(() => {
    vi.resetModules()
  })

  async function receiver() {
    const { useWidgetSocket } = await import('@/composables/useWidgetSocket')
    const widget = useWidgetSocket()
    void widget.connect()
    return widget
  }

  const bot = (message_id: number, message = 'Hello') => ({
    message_id, message, type: 'chat_response', session_id: 'session-a',
    shopify_output: null, transfer_to_human: false
  })

  it('ACKs the same canonical ID on replay but keeps exactly one visible message', async () => {
    const widget = await receiver()
    const receipt = vi.fn()
    fire('chat_response', bot(100), receipt)
    fire('chat_response', bot(100), receipt)
    expect(widget.messages.value).toHaveLength(1)
    expect(widget.messages.value[0].id).toBe(100)
    expect(receipt).toHaveBeenCalledTimes(2)
    expect(receipt).toHaveBeenNthCalledWith(2, { message_id: 100, accepted: true })
  })

  it('preserves two equal texts when canonical IDs differ', async () => {
    const widget = await receiver()
    fire('chat_response', bot(100, 'Hello'), vi.fn())
    fire('chat_response', bot(101, 'Hello'), vi.fn())
    expect(widget.messages.value.map(m => m.id)).toEqual([100, 101])
  })

  it('dedupes against persisted chat_history by ID after reconnect', async () => {
    const widget = await receiver()
    fire('chat_history', { type: 'chat_history', messages: [
      { id: 100, message: 'Hello', message_type: 'bot', created_at: '2026-10-08T10:00:00Z' }
    ] })
    const receipt = vi.fn()
    fire('chat_response', bot(100), receipt)
    expect(widget.messages.value).toHaveLength(1)
    expect(receipt).toHaveBeenCalledWith({ message_id: 100, accepted: true })
  })

  it('does not text-dedupe two different canonical IDs loaded from history', async () => {
    const widget = await receiver()
    fire('chat_history', { type: 'chat_history', messages: [
      { id: 100, message: 'Hello', message_type: 'bot', created_at: '2026-10-08T10:00:00Z' },
      { id: 101, message: 'Hello', message_type: 'bot', created_at: '2026-10-08T10:00:00Z' }
    ] })
    expect(widget.messages.value.map(m => m.id)).toEqual([100, 101])
  })

  it('ACKs structured Shopify data once without dropping products', async () => {
    const widget = await receiver()
    const receipt = vi.fn()
    const product = { ...bot(200, 'Products'), shopify_output: { products: [{ id: 'P1' }] } }
    fire('chat_response', product, receipt)
    fire('chat_response', product, receipt)
    expect(widget.messages.value).toHaveLength(1)
    expect(widget.messages.value[0].message_type).toBe('product')
    expect((widget.messages.value[0] as any).shopify_output.products).toHaveLength(1)
    expect(receipt).toHaveBeenCalledTimes(2)
  })

  it('does not change human attachments or legacy no-ID behavior', async () => {
    const widget = await receiver()
    fire('chat_response', {
      type: 'agent_message', message_id: 202, message: 'Attached',
      attachments: [{ filename: 'photo.png', file_url: '/photo.png' }]
    })
    fire('chat_response', { message: 'Legacy reply', type: 'chat_response' })
    expect(widget.messages.value).toHaveLength(2)
    expect(widget.messages.value[0].message_type).toBe('agent')
    expect(widget.messages.value[0].attachments).toHaveLength(1)
    expect(widget.messages.value[1].message_type).toBe('bot')
  })
})
