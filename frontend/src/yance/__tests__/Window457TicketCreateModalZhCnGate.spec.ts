import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(
  resolve(process.cwd(), 'src/components/tickets/TicketCreateModal.vue'),
  'utf8',
)

describe('W457 native ticket-create modal Chinese product truth', () => {
  it('translates the real modal, form fields, actions and error states', () => {
    for (const text of [
      '新建工单', '手动填写', '从对话生成', '根据对话生成草稿',
      '工单标题', '问题描述', '客户邮箱', '客户姓名',
      '优先级', '紧急', '高', '中', '低',
      '正在创建…', '创建工单', '取消', '创建工单失败',
      '关闭新建工单弹窗',
    ]) expect(source).toContain(text)
    for (const english of [
      'class="modal-title">New ticket',
      '<label class="field-label">Title</label>',
      '<label class="field-label">Description</label>',
      '<label class="field-label">Priority</label>',
      '>Cancel</button>',
      "'Create ticket'",
      'Drafting from the conversation…',
    ]) expect(source).not.toContain(english)
  })

  it('preserves native CRUD payload and 4 original priority enum values', () => {
    expect(source).toContain('ticketService.createTicket({')
    expect(source).toContain('session_id: linkSession ? props.sessionId! : undefined')
    expect(source).toContain('customer_email: !linkSession ? customerEmail.value.trim() || undefined : undefined')
    expect(source).toContain('priority: priority.value')
    for (const priority of ['urgent:', 'high:', 'medium:', 'low:']) expect(source).toContain(priority)
    expect(source).toContain('@click="submit"')
    expect(source).toContain('emit(\'created\', detail)')
  })
})
