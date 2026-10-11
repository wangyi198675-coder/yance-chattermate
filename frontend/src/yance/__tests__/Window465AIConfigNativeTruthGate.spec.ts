import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const read=(p:string)=>readFileSync(resolve(process.cwd(),p),'utf8')
describe('W465 AI Config real not-configured truth correction',()=>{
 it('does not claim managed ChatTermate AI runs when no active backend config exists',()=>{
  const source=read('src/components/ai/AISetup.vue')
  expect(source).toContain('当前工作区尚未配置活动 AI 模型')
  expect(source).toContain('v-if="hasExistingConfig" class="page-subtitle"')
  expect(source).toContain("hasExistingConfig && setupConfig.provider.toLowerCase() === 'chattermate'")
  expect(source).toContain('尚无活动的 ChatterMate 模型配置，不代表服务已连接。')
  expect(source).toContain('高级设置 · 使用自己的模型')
  expect(source).not.toContain('Your agents already run on ChatterMate AI')
  expect(source).not.toContain('Zero setup. Managed models, ready instantly')
  expect(source).not.toContain('<span class="active-text">ACTIVE</span>')
 })
 it('keeps native AI provider catalogs and missing-config 404 as explicit unconfigured state',()=>{
  const s=read('src/composables/useAISetup.ts')
  const route=read('../backend/app/api/ai_setup.py')
  expect(s).toContain('if (response?.status !== 404')
  expect(s).toContain('hasExistingConfig.value = false')
  expect(s).toContain('aiService.getOrganizationConfig()')
  expect(route).toContain('No active AI configuration found')
  expect(route).toContain('status_code=404')
  expect(s).toContain('loadProviders()')
 })
})
