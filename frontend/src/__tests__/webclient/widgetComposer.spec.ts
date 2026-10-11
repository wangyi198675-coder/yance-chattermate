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

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

/**
 * The composer while the assistant is answering.
 *
 * Disabling an input blurs it, and nothing hands the focus back — so gating the
 * field on "no reply in flight" cost the visitor their cursor after every single
 * message, and they had to click the box again to keep typing (#316).
 */

const sendMessage = vi.fn()

const socket = {
    messages: ref<any[]>([]),
    loading: ref(false),
    errorMessage: ref(''),
    showError: ref(false),
    loadingHistory: ref(false),
    hasStartedChat: ref(true),
    connectionStatus: ref('connected'),
    humanAgent: ref({}),
    currentForm: ref(null),
    currentSessionId: ref('session-1')
}

vi.mock('@/composables/useWidgetSocket', () => ({
    useWidgetSocket: () => ({
        ...socket,
        sendMessage,
        sendFileAttachments: vi.fn(),
        endChat: vi.fn(),
        loadChatHistory: vi.fn(),
        connect: vi.fn().mockResolvedValue(true),
        reconnect: vi.fn(),
        cleanup: vi.fn(),
        onTakeover: vi.fn(),
        onSessionState: vi.fn(),
        submitRating: vi.fn(),
        submitForm: vi.fn(),
        getWorkflowState: vi.fn(),
        proceedWorkflow: vi.fn(),
        onWorkflowState: vi.fn(),
        onWorkflowProceeded: vi.fn(),
        setToken: vi.fn(),
        setWidgetId: vi.fn()
    })
}))

describe('the composer while a reply is in flight', () => {
    let WidgetBuilder: any

    beforeEach(async () => {
        sendMessage.mockClear()
        socket.loading.value = false
        socket.hasStartedChat.value = true
        socket.connectionStatus.value = 'connected'
        socket.messages.value = []

        ;(window as any).__INITIAL_DATA__ = {
            widgetId: 'w-1',
            agentName: 'Ada',
            customization: {},
            customerId: 'c-1',
            customer: {},
            initialToken: 'tok-1'
        }
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: async () => ({ agent: { name: 'Ada' } })
        }))

        vi.resetModules()
        WidgetBuilder = (await import('@/webclient/WidgetBuilder.vue')).default
    })

    afterEach(() => {
        vi.unstubAllGlobals()
    })

    const composer = (wrapper: any) =>
        wrapper.find('input.welcome-message-field, .message-input input')

    it('keeps the field typable while the assistant is answering', async () => {
        const wrapper = mount(WidgetBuilder, { props: { widgetId: 'w-1', token: 'tok-1' } })

        expect(composer(wrapper).attributes('disabled')).toBeUndefined()

        socket.loading.value = true
        await wrapper.vm.$nextTick()

        // The moment this becomes `disabled`, the browser drops the cursor.
        expect(composer(wrapper).attributes('disabled')).toBeUndefined()

        wrapper.unmount()
    })

    it('still refuses typing when the socket is not connected', async () => {
        const wrapper = mount(WidgetBuilder, { props: { widgetId: 'w-1', token: 'tok-1' } })

        socket.connectionStatus.value = 'connecting'
        await wrapper.vm.$nextTick()

        expect(composer(wrapper).attributes('disabled')).toBeDefined()

        wrapper.unmount()
    })

    it('holds a message typed mid-reply and sends it when the reply lands', async () => {
        const wrapper = mount(WidgetBuilder, { props: { widgetId: 'w-1', token: 'tok-1' } })

        socket.loading.value = true
        await wrapper.vm.$nextTick()

        const field = composer(wrapper)
        await field.setValue('and one more thing')
        await field.trigger('keypress', { key: 'Enter' })

        // Sending now would start a second agent run on the same conversation.
        expect(sendMessage).not.toHaveBeenCalled()

        socket.loading.value = false
        await wrapper.vm.$nextTick()
        await wrapper.vm.$nextTick()

        // ...and it must not be lost either.
        expect(sendMessage).toHaveBeenCalledWith(
            'and one more thing', expect.anything(), expect.anything()
        )

        wrapper.unmount()
    })

    it('does not carry a queued message into the next conversation', async () => {
        const wrapper = mount(WidgetBuilder, { props: { widgetId: 'w-1', token: 'tok-1' } })

        socket.loading.value = true
        await wrapper.vm.$nextTick()

        const field = composer(wrapper)
        await field.setValue('meant for the chat I just closed')
        await field.trigger('keypress', { key: 'Enter' })

        // Ending the chat clears the transcript and stops the typing indicator,
        // which lands on the same `loading` change the queue waits for.
        socket.hasStartedChat.value = false
        socket.messages.value = []
        socket.loading.value = false
        await wrapper.vm.$nextTick()
        await wrapper.vm.$nextTick()

        expect(sendMessage).not.toHaveBeenCalled()

        wrapper.unmount()
    })

    it('does not accept a second message while one is being answered', async () => {
        const wrapper = mount(WidgetBuilder, { props: { widgetId: 'w-1', token: 'tok-1' } })

        socket.loading.value = true
        await wrapper.vm.$nextTick()

        // Typing carries on, but sending waits its turn.
        const send = wrapper.find('.welcome-send-button, .send-button')
        expect(send.attributes('disabled')).toBeDefined()

        wrapper.unmount()
    })

    it('keeps native composer listeners while mounted and cancels DOM work on unmount', async () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
        const queryAll = vi.spyOn(document, 'querySelectorAll')
        const wrapper = mount(WidgetBuilder, {
            props: { widgetId: 'w-1', token: 'tok-1' },
            attachTo: document.body,
        })
        try {
            await flushPromises()
            const input = composer(wrapper).element as HTMLInputElement
            const addListener = vi.spyOn(input, 'addEventListener')
            const removeListener = vi.spyOn(input, 'removeEventListener')

            await vi.advanceTimersByTimeAsync(150)
            expect(queryAll).toHaveBeenCalled()
            expect(addListener).toHaveBeenCalledWith('input', expect.any(Function), true)
            expect(composer(wrapper).attributes('disabled')).toBeUndefined()

            // Queue native observer work while the widget is still mounted.
            input.parentElement?.appendChild(document.createElement('input'))
            await Promise.resolve()
            wrapper.unmount()
            expect(removeListener).toHaveBeenCalledWith('input', expect.any(Function), true)
            queryAll.mockClear()
            await vi.advanceTimersByTimeAsync(750)
            expect(queryAll).not.toHaveBeenCalled()
        } finally {
            wrapper.unmount()
            queryAll.mockRestore()
            vi.useRealTimers()
        }
    })

    it('does not install listeners after authorization resolves beyond unmount', async () => {
        let completeFetch!: (response: unknown) => void
        vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { completeFetch = resolve })))
        const addListener = vi.spyOn(document, 'addEventListener')
        const query = vi.spyOn(document, 'querySelector')
        const wrapper = mount(WidgetBuilder, { props: { widgetId: 'w-1', token: 'tok-1' } })
        try {
            await wrapper.vm.$nextTick()
            expect(fetch).toHaveBeenCalled()
            wrapper.unmount()
            completeFetch({
                ok: true, status: 200,
                json: async () => ({ agent: { name: 'Ada' } }),
            })
            await flushPromises()
            expect(addListener).not.toHaveBeenCalledWith('click', expect.any(Function))

            query.mockClear()
            window.dispatchEvent(new MessageEvent('message', {
                source: window.parent,
                data: { type: 'PREFILL_MESSAGE', text: 'stale host event' },
            }))
            await flushPromises()
            expect(query).not.toHaveBeenCalled()
        } finally {
            wrapper.unmount()
            addListener.mockRestore()
            query.mockRestore()
        }
    })

    it('ignores queued PREFILL_MESSAGE callback after unmount', async () => {
        const wrapper = mount(WidgetBuilder, { props: { widgetId: 'w-1', token: 'tok-1' } })
        await flushPromises()
        const query = vi.spyOn(document, 'querySelector')
        try {
            window.dispatchEvent(new MessageEvent('message', {
                source: window.parent,
                data: { type: 'PREFILL_MESSAGE', text: 'queued-before-unmount' },
            }))
            wrapper.unmount()
            query.mockClear()
            await flushPromises()
            expect(query).not.toHaveBeenCalled()
        } finally {
            wrapper.unmount()
            query.mockRestore()
        }
    })

    it('cancels initialization polling when unmounted without widgetId', async () => {
        const saved = (window as any).__INITIAL_DATA__
        delete (window as any).__INITIAL_DATA__
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
        // Vitest runs other suites concurrently: global timer count can include
        // unrelated jsdom/component timers. Assert cleanup of this widget's
        // own 100ms widgetId poll handle, not every timer in the process.
        const schedule = vi.spyOn(globalThis, 'setTimeout')
        const cancel = vi.spyOn(globalThis, 'clearTimeout')
        const wrapper = mount(WidgetBuilder, { props: { widgetId: 'w-1', token: 'tok-1' } })
        try {
            await vi.advanceTimersByTimeAsync(0)
            const polls = schedule.mock.calls
                .map((args, i) => ({ delay: args[1], handle: schedule.mock.results[i]?.value }))
                .filter(poll => poll.delay === 100 && poll.handle != null)
            expect(polls.length).toBeGreaterThan(0)
            wrapper.unmount()
            // Removing cancelPendingWidgetIdPolls() from WidgetBuilder must
            // break this test even if an unrelated timer remains pending.
            for (const poll of polls) {
                expect(cancel.mock.calls.some(args => args[0] === poll.handle)).toBe(true)
            }
            const pollCountAfterUnmount = schedule.mock.calls.filter(args => args[1] === 100).length
            await vi.advanceTimersByTimeAsync(500)
            expect(schedule.mock.calls.filter(args => args[1] === 100).length).toBe(pollCountAfterUnmount)
        } finally {
            wrapper.unmount()
            schedule.mockRestore()
            cancel.mockRestore()
            vi.clearAllTimers()
            vi.useRealTimers()
            ;(window as any).__INITIAL_DATA__ = saved
        }
    })

    it('resumes initialization when widgetId arrives while still mounted', async () => {
        const saved = (window as any).__INITIAL_DATA__
        delete (window as any).__INITIAL_DATA__
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
        const wrapper = mount(WidgetBuilder, { props: { widgetId: 'w-1', token: 'tok-1' } })
        try {
            await vi.advanceTimersByTimeAsync(0)
            expect(fetch).not.toHaveBeenCalled()
            ;(window as any).__INITIAL_DATA__ = { ...saved, widgetId: 'w-late' }
            await vi.advanceTimersByTimeAsync(100)
            expect(fetch).toHaveBeenCalled()
        } finally {
            wrapper.unmount()
            vi.clearAllTimers()
            vi.useRealTimers()
            ;(window as any).__INITIAL_DATA__ = saved
        }
    })
})
