/*
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

import { io, Socket } from 'socket.io-client'
import { ref } from 'vue'
import emitter from '@/utils/emitter'
import { getWsUrl } from '@/config/api'

// Utility function to set cookies
function setCookie(name: string, value: string, maxAge: number = 1800) {
  document.cookie = `${name}=${value}; path=/; max-age=${maxAge}; SameSite=Lax`
}

type ClientSendEnvelope = Record<string, unknown> & {
  client_send_intent_id: string
  session_id: string
  end_chat?: boolean
}

type PendingPersistenceAck = {
  event: string
  data: ClientSendEnvelope
  signature: string
  intentId: string
  sessionId: string
  actionKind: 'message' | 'end_chat'
  timeoutMs: number
  retries: number
  inFlight: boolean
  promise: Promise<unknown>
  resolve: (value: unknown) => void
  reject: (reason?: unknown) => void
}

function cloneClientSendEnvelope(data: unknown): ClientSendEnvelope {
  if (!data || typeof data !== 'object') {
    throw new Error('Client send persistence ACK requires an object payload')
  }
  const clone = JSON.parse(JSON.stringify(data)) as Partial<ClientSendEnvelope>
  if (!clone.client_send_intent_id || !clone.session_id) {
    throw new Error('Client send persistence ACK requires intent and session identity')
  }
  return clone as ClientSendEnvelope
}

class SocketService {
  private socket: Socket | null = null
  private _isConnected = ref(false)
  private _error = ref<string | null>(null)
  private eventEmitter = emitter
  // Client-only transport retention. ChatHistory remains the server-side
  // idempotency authority; this map merely keeps the exact unacknowledged
  // envelope alive until the server confirms persistence or rejects it.
  private pendingPersistenceAcks = new Map<string, PendingPersistenceAck>()

  get isConnected() {
    return this._isConnected
  }

  get error() {
    return this._error
  }

  connect(namespace: string = '/agent') {
    if (this.socket?.connected) return

    // Use the runtime-resolved WS URL (window.APP_CONFIG → VITE_WS_URL → localhost),
    // same as every other consumer. Reading import.meta.env directly baked the
    // published image to ws://localhost:8000 and broke self-hosted dashboards.
    const apiUrl = getWsUrl()
    this.socket = io(apiUrl + namespace, {
      transports: ['websocket', 'polling'],
      withCredentials: true,
      autoConnect: true,
    })

    this.socket.on('connect', () => {
      this._isConnected.value = true
      this._error.value = null
      console.log('Socket connected')
      // Replay only envelopes that never received a persistence ACK. Every
      // replay carries the original UUID, session and logical payload verbatim.
      this.replayPendingPersistenceAcks()
      // Emit reconnection event for components to reattach listeners
      this.eventEmitter.emit('socket:reconnected')
    })

    this.socket.on('cookie_set', (data) => {
      if (data.access_token) {
        setCookie('access_token', data.access_token)
        // Reconnect socket with new token
        this.socket?.disconnect()
        this.connect()
      }
    })

    this.socket.on('connection_success', (data) => {
      console.log('Connection success:', data)
    })

    this.socket.on('disconnect', () => {
      this._isConnected.value = false
      console.log('Socket disconnected')
    })

    this.socket.on('error', (error) => {
      this._error.value = error.error
      console.error('Socket error:', error)
    })
  }

  disconnect() {
    if (this.socket) {
      this.socket.disconnect()
      this.socket = null
    }
  }

  emit(event: string, data: unknown) {
    if (!this.socket) {
      console.error('Socket not initialized')
      return
    }
    this.socket.emit(event, data)
  }

  private emitOnceWithAck<T>(event: string, data: unknown, timeoutMs: number): Promise<T> {
    if (!this.socket) {
      return Promise.reject(new Error('Socket not initialized'))
    }
    return new Promise<T>((resolve, reject) => {
      this.socket!.timeout(timeoutMs).emit(
        event,
        data,
        (error: Error | null, response: T) => {
          if (error) {
            reject(error)
            return
          }
          resolve(response)
        },
      )
    })
  }

  async emitWithAck<T = unknown>(
    event: string,
    data: unknown,
    timeoutMs: number = 5000,
    retries: number = 2,
  ): Promise<T> {
    if (!this.socket) {
      throw new Error('Socket not initialized')
    }

    let lastError: unknown = new Error('Socket acknowledgement failed')
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        return await this.emitOnceWithAck<T>(event, data, timeoutMs)
      } catch (error) {
        lastError = error
      }
    }
    throw lastError
  }

  emitWithPersistenceAck<T = unknown>(
    event: string,
    data: unknown,
    timeoutMs: number = 5000,
    retries: number = 2,
  ): Promise<T> {
    let envelope: ClientSendEnvelope
    try {
      envelope = cloneClientSendEnvelope(data)
    } catch (error) {
      return Promise.reject(error)
    }

    const intentId = envelope.client_send_intent_id
    const sessionId = envelope.session_id
    const actionKind = envelope.end_chat === true ? 'end_chat' : 'message'
    const signature = JSON.stringify(envelope)
    const existing = this.pendingPersistenceAcks.get(intentId)
    if (existing) {
      if (
        existing.event !== event ||
        existing.sessionId !== sessionId ||
        existing.actionKind !== actionKind ||
        existing.signature !== signature
      ) {
        return Promise.reject(
          new Error('Pending client send intent session/action/payload conflict'),
        )
      }
      return existing.promise as Promise<T>
    }

    let resolvePending!: (value: unknown) => void
    let rejectPending!: (reason?: unknown) => void
    const promise = new Promise<unknown>((resolve, reject) => {
      resolvePending = resolve
      rejectPending = reject
    })
    const pending: PendingPersistenceAck = {
      event,
      data: envelope,
      signature,
      intentId,
      sessionId,
      actionKind,
      timeoutMs,
      retries,
      inFlight: false,
      promise,
      resolve: resolvePending,
      reject: rejectPending,
    }
    this.pendingPersistenceAcks.set(intentId, pending)
    void this.runPersistenceAckAttempts(pending)
    return promise as Promise<T>
  }

  private replayPendingPersistenceAcks() {
    for (const pending of this.pendingPersistenceAcks.values()) {
      void this.runPersistenceAckAttempts(pending)
    }
  }

  private async runPersistenceAckAttempts(pending: PendingPersistenceAck) {
    if (pending.inFlight || !this.socket) return
    pending.inFlight = true
    try {
      for (let attempt = 0; attempt <= pending.retries; attempt++) {
        try {
          const response = await this.emitOnceWithAck<any>(
            pending.event,
            pending.data,
            pending.timeoutMs,
          )
          if (response?.client_send_intent_id !== pending.intentId) {
            continue
          }

          // A canonical message id is the persistence ACK. A terminal server
          // rejection is also safe to stop replaying because no intent row was
          // accepted for this envelope; the caller will surface the rejection.
          const persisted = response?.message_id != null
          const terminalRejection = response?.status === 'rejected'
          if (!persisted && !terminalRejection) {
            continue
          }

          this.pendingPersistenceAcks.delete(pending.intentId)
          pending.resolve(response)
          return
        } catch {
          // Exhaust this inline retry window, then retain the exact envelope.
          // A later socket connect event is the next retry trigger.
        }
      }
    } finally {
      pending.inFlight = false
    }
  }

  emitPing(event: string) {
    if (!this.socket) {
      console.error('Socket not initialized')
      return
    }
    this.socket.emit(event)
  }

  on<T>(event: string, callback: (data: T) => void) {
    if (!this.socket) {
      console.error('Socket not initialized')
      return
    }
    this.socket.on(event, callback as (...args: any[]) => void)
  }

  off<T>(event: string, callback?: (data: T) => void) {
    if (!this.socket) {
      console.warn('Socket not initialized')
      return
    }
    this.socket.off(event, callback as (...args: any[]) => void)
  }

  // Add methods for reconnection event handling
  onReconnect(callback: () => void) {
    this.eventEmitter.on('socket:reconnected', callback)
  }

  offReconnect(callback: () => void) {
    this.eventEmitter.off('socket:reconnected', callback)
  }
}

// Create a singleton instance
export const socketService = new SocketService()
