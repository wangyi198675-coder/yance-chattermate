import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/components/tickets/TicketFilterBar.vue'), 'utf8')

describe('W458 native Tickets filters complete Chinese text without changing filter contract', () => {
  it('localizes statuses, priorities, owners, AI states, sorting, and search', () => {
    for (const label of [
      '全部', '进行中', '待审批', 'SLA 即将超时', '已解决', '全部 AI',
      'AI 调查中', '等待人工', '人工处理', 'AI 已解决',
      '优先级 · 全部', '紧急', '高', '中', '低',
      '负责人 · 全部', '未分配 / AI', '搜索工单…',
      '排序 · 最近更新', '最新创建', '按优先级',
    ]) expect(source).toContain(label)
    for (const english of [
      '>Urgent</option>', '>Priority · All</option>',
      'Assignee · All', '>Unassigned / AI</option>',
      'label: \'SLA breaching\'', 'label: \'All AI\'',
      'placeholder="Search tickets…"',
    ]) expect(source).not.toContain(english)
  })

  it('preserves native filter model values and explicit user selection', () => {
    for (const value of [
      'open', 'awaiting', 'breaching', 'resolved',
      'investigating', 'human', 'urgent', 'high', 'medium',
      'low', 'unassigned', 'updated', 'created', 'priority',
    ]) expect(source).toContain(value)
    expect(source).toContain('v-model="filters.priority"')
    expect(source).toContain('v-model="filters.assignee"')
    expect(source).toContain('v-model="filters.search"')
    expect(source).toContain('v-model="filters.sort"')
    expect(source).toContain('filters.status = pill.value')
    expect(source).toContain('filters.ai = pill.value')
  })
})
