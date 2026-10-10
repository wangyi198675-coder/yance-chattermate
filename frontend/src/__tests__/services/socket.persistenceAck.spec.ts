import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Handler = (...args: any[]) => void

describe('agent persistence ACK envelope replay', () => {
  const handlers = new Map<string, Handler[]>()
  const emissions: Array<{ event: string; data: any }> = []
  let socket: any
  let nextAck: (callback: (error: Error | null, response?: any) => void) => void

  vi.mock('socket.io-client', () => ({
    io: (...args: any[]) => (globalThis as any).__agentIoFactory(...args),
  }))
  vi.mock('@/config/api', () => ({ getWsUrl: () => 'ws://example.test' }))

  const fire = (event: string, ...args: any[]) =>
    (handlers.get(event) || []).forEach((handler) => handler(...args))

  beforeEach(() => {
    handlers.clear()
    emissions.length = 0
    nextAck = (callback) => callback(new Error('ack timeout'))
    socket = {
      connected: true,
      on: vi.fn((event: string, handler: Handler) => {
        handlers.set(event, [...(handlers.get(event) || []), handler])
      }),
      off: vi.fn(),
      disconnect: vi.fn(),
      emit: vi.fn(),
      timeout: vi.fn(() => ({
        emit: (event: string, data: any, callback: (error: Error | null, response?: any) => void) => {
          emissions.push({ event, data })
          nextAck(callback)
        },
      })),
    }
    ;(globalThis as any).__agentIoFactory = () => socket
  })

  afterEach(() => {
    vi.resetModules()
    delete (globalThis as any).__agentIoFactory
  })

  async function service() {
    const module = await import('@/services/socket')
    module.socketService.connect('/agent')
    return module.socketService
  }

  it('keeps one exact envelope past inline retry exhaustion and replays it on reconnect', async () => {
    const socketService = await service()
    const payload = {
      client_send_intent_id: '11111111-1111-4111-8111-111111111111',
      session_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      message: 'same payload',
      files: [{ filename: 'x.txt', content: 'eA==' }],
    }

    const pending = socketService.emitWithPersistenceAck('agent_message', payload, 1, 0)
    await Promise.resolve()
    expect(emissions).toHaveLength(1)

    nextAck = (callback) => callback(null, {
      status: 'accepted',
      client_send_intent_id: payload.client_send_intent_id,
      message_id: 42,
    })
    socket.connected = true
    fire('connect')

    await expect(pending).resolves.toMatchObject({ message_id: 42 })
    expect(emissions).toHaveLength(2)
    expect(emissions[0].data).toEqual(payload)
    expect(emissions[1].data).toEqual(payload)
  })

  it('reuses the same UUID and payload through multiple reconnects until ACK then clears it', async () => {
    const socketService = await service()
    const payload = {
      client_send_intent_id: '22222222-2222-4222-8222-222222222222',
      session_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      message: 'persist me',
    }
    const pending = socketService.emitWithPersistenceAck('agent_message', payload, 1, 0)
    await Promise.resolve()

    fire('connect')
    await Promise.resolve()
    expect(emissions).toHaveLength(2)
    expect(emissions.every((entry) => entry.data.client_send_intent_id === payload.client_send_intent_id)).toBe(true)
    expect(emissions.every((entry) => entry.data.session_id === payload.session_id)).toBe(true)

    nextAck = (callback) => callback(null, {
      status: 'accepted',
      client_send_intent_id: payload.client_send_intent_id,
      message_id: 7,
    })
    fire('connect')
    await expect(pending).resolves.toMatchObject({ message_id: 7 })
    const afterAck = emissions.length
    fire('connect')
    await Promise.resolve()
    expect(emissions).toHaveLength(afterAck)
  })

  it('never rewrites a pending session A envelope when another session is selected or sent', async () => {
    const socketService = await service()
    const payloadA = {
      client_send_intent_id: '33333333-3333-4333-8333-333333333333',
      session_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      message: 'from A',
    }
    const pendingA = socketService.emitWithPersistenceAck('agent_message', payloadA, 1, 0)
    await Promise.resolve()

    const payloadB = {
      client_send_intent_id: '44444444-4444-4444-8444-444444444444',
      session_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      message: 'from B',
    }
    nextAck = (callback) => callback(null, {
      status: 'accepted',
      client_send_intent_id: payloadB.client_send_intent_id,
      message_id: 9,
    })
    await expect(socketService.emitWithPersistenceAck('agent_message', payloadB, 1, 0)).resolves.toMatchObject({ message_id: 9 })

    nextAck = (callback) => callback(null, {
      status: 'accepted',
      client_send_intent_id: payloadA.client_send_intent_id,
      message_id: 8,
    })
    fire('connect')
    await expect(pendingA).resolves.toMatchObject({ message_id: 8 })
    expect(emissions.at(-1)?.data.session_id).toBe(payloadA.session_id)
    expect(emissions.at(-1)?.data.message).toBe('from A')
  })

  it('fails closed if the same pending UUID is reused for another session or action', async () => {
    const socketService = await service()
    const intent = '55555555-5555-4555-8555-555555555555'
    void socketService.emitWithPersistenceAck('agent_message', {
      client_send_intent_id: intent,
      session_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      message: 'original',
    }, 1, 0)
    await Promise.resolve()

    await expect(socketService.emitWithPersistenceAck('agent_message', {
      client_send_intent_id: intent,
      session_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      message: 'wrong session',
    }, 1, 0)).rejects.toThrow(/session\/action/i)

    await expect(socketService.emitWithPersistenceAck('agent_message', {
      client_send_intent_id: intent,
      session_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      message: 'wrong action',
      end_chat: true,
    }, 1, 0)).rejects.toThrow(/session\/action/i)
  })
})
