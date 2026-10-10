import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const src = path.resolve(__dirname, '..')
const appSrc = path.resolve(src, '..')

function read(file: string) {
  return fs.readFileSync(file, 'utf8')
}

describe('Window177 Relationship + Memory + Temporal closure', () => {
  it('composes Relationship World instead of creating a second CRM surface', () => {
    const world = read(path.join(src, 'YanceRelationshipWorld.vue'))
    const panel = read(path.join(src, 'components', 'YanceRelationshipContextPanel.vue'))
    expect(world).toContain('<YanceRelationshipContextPanel :customer-id="customerId" />')
    expect(panel).toContain('Customer / People')
    expect(panel).toContain('ChatHistory')
    expect(panel).not.toContain('YanceRelationshipDB')
    expect(panel).not.toContain('YanceMemoryDB')
  })

  it('uses real People API seams for projection, confirmed memory and temporal settings', () => {
    const service = read(path.join(appSrc, 'services', 'people.ts'))
    expect(service).toContain('/relationship-context')
    expect(service).toContain('/relationship-memory')
    expect(service).toContain('/relationship-temporal')
    expect(service).toContain('api.put')
    expect(service).toContain('api.patch')
  })

  it('does not fake contact local time when timezone is unknown', () => {
    const panel = read(path.join(src, 'components', 'YanceRelationshipContextPanel.vue'))
    expect(panel).toContain('联系人时区未知')
    expect(panel).toContain('不当作联系人当地时间')
    expect(panel).toContain('Europe/Berlin')
  })

  it('exposes relationship, continuity, evidence and action projections', () => {
    const panel = read(path.join(src, 'components', 'YanceRelationshipContextPanel.vue'))
    for (const text of [
      '记忆与连续性',
      '关系洞察',
      '当前关系投影',
      '下一步',
      '时间上下文',
      '关系旅程与重要时刻',
      '图谱增强：可选，当前保持关闭',
    ]) {
      expect(panel).toContain(text)
    }
  })
})
