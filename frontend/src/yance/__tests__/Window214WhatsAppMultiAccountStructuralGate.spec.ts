import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = (relative: string) =>
  readFileSync(resolve(process.cwd(), relative), 'utf8')

describe('Window214 WhatsApp multi-account structural gate', () => {
  it('keeps lifecycle operations exact-account in the native channel service', () => {
    const channels = source('src/services/channels.ts')
    expect(channels).toContain('/channels/meta/whatsapp/${accountId}/reconnect')
    expect(channels).toContain('/channels/meta/whatsapp/${accountId}/rotate-credentials')
    expect(channels).toContain('/channels/meta/whatsapp/${accountId}`')
  })

  it('renders and mutates WhatsApp settings per ChannelAccount', () => {
    const settings = source('src/views/settings/IntegrationsSettings.vue')
    expect(settings).toContain('v-for="account in accountsFor(\'whatsapp\')"')
    expect(settings).toContain('@click="reconnectWhatsAppAccount(account)"')
    expect(settings).toContain('@click="openWhatsAppRotation(account)"')
    expect(settings).toContain('@click="requestWhatsAppDisconnect(account)"')
    expect(settings).toContain('await channelsService.disconnectWhatsApp(account.id)')
    expect(settings).toContain('@click="connectAnotherWhatsApp"')
    expect(settings).toContain("if (channelType === 'whatsapp') {")
    expect(settings).toContain('disconnect: undefined')
  })

  it('preserves exact account identity in native webhook, send and template paths', () => {
    const webhook = source('../backend/app/api/webhooks/meta.py')
    const delivery = source('../backend/app/services/message_delivery.py')
    const conversationRepo = source('../backend/app/repositories/channels/conversations.py')
    const templateApi = source('../backend/app/api/channels/whatsapp_messaging.py')
    expect(webhook).toContain('account_repo.get_by_external_id(channel_type, inbound.external_account_id)')
    expect(webhook).toContain('process_channel_message, account.id, inbound')
    expect(delivery).toContain('get_by_id(conversation.channel_account_id)')
    expect(conversationRepo).toContain('ChannelConversation.channel_account_id == channel_account_id')
    expect(templateApi).toContain('conversation.channel_account_id != account.id')
  })

  it('keeps outbound selectors and notifications on exact account/session identity', () => {
    const compose = source('src/components/conversations/NewWhatsAppConversation.vue')
    const templates = source('src/components/integrations/WhatsAppTemplateManager.vue')
    const push = source('src/pwa/pushContract.ts')
    expect(compose).toContain('channelsService.startWhatsAppConversation(accountId.value')
    expect(templates).toContain('channelsService.listWhatsAppTemplates(accountId.value)')
    expect(push).toContain('?session=${encodeURIComponent(sessionId)}')
  })
})
