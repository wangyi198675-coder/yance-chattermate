import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const read=(file:string)=>readFileSync(resolve(process.cwd(),'src/components/faq',file),'utf8')
describe('W462 native FAQ authoring Chinese preserving CRUD and Markdown',()=>{
 it('localizes edit fields and preserves native FAQ save, status and selection events',()=>{
  const s=read('FaqCard.vue')
  for(const text of ['新增常见问题','编辑常见问题','请输入常见问题','支持 Markdown','主题','正在保存…','保存','取消','已发布','草稿','选择：','编辑','删除'])
   expect(s).toContain(text)
  for(const old of ['NEW FAQ','EDITING','placeholder="Question"',"saving ? 'Saving…' : 'Save'", "'Published' : 'Draft'"])
   expect(s).not.toContain(old)
  for(const api of ["$emit('save')","$emit('cancel')","$emit('toggle-status')","$emit('delete')","$emit('update:draftAnswer'"])
   expect(s).toContain(api)
 })
 it('uses original SEO values and native optional field events with localized labels',()=>{
  const s=read('FaqSeoFields.vue')
  for(const value of ['已自定义','URL 短链接标识','自定义 URL 路径','SEO 标题','SEO 描述','默认使用答案开头'])
   expect(s).toContain(value)
  for(const native of ["emit('update:slug'", "emit('update:urlPath'", "emit('update:metaTitle'", "emit('update:metaDescription'"])
   expect(s).toContain(native)
 })
 it('keeps Markdown sandbox/no-scripts rendering and original toolbar/preview events',()=>{
  const s=read('MarkdownEditor.vue')
  for(const text of ['请输入答案','暂无可预览内容','编辑','预览','答案预览','插入图片','插入链接','图片上传失败'])
   expect(s).toContain(text)
  for(const native of ['sandbox=""','marked.parse(','mode = \'write\'','mode = \'preview\'',"faqService.uploadImage(file)", "emit('update:modelValue'"])
   expect(s).toContain(native)
 })
})
