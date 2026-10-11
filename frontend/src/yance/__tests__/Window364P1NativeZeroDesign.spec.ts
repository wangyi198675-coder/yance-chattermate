import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const push=vi.hoisted(()=>vi.fn())
vi.mock('vue-router',()=>({
  useRouter:()=>({ push }),
}))
vi.mock('../components/YanceWebShell.vue',()=>({
  default:{ template:'<div data-native-yance-shell><slot /></div>' },
}))
import YanceFirstRunHome from '../components/YanceFirstRunHome.vue'
import YanceEmptyConversation from '../components/YanceEmptyConversation.vue'

describe('W364 first independent P1 fixes are live native zero states',()=>{
  it('exposes W371 02 first-run welcome, attention and native platform status instead of stale recent list',async()=>{
    const w=mount(YanceFirstRunHome,{props:{supportedPlatforms:8,connectedPlatforms:0}})
    expect(w.get('.w371-first-run__welcome').text()).toContain('欢迎使用言策')
    expect(w.get('.w371-first-run__attention').text()).toContain('今日值得关注')
    expect(w.get('.w371-first-run__runtime').text()).toContain('0/8')
    expect(w.findAll('textarea')).toHaveLength(0)
    await w.get('[data-w371-connect-platform]').trigger('click')
    expect(push).toHaveBeenCalledWith('/yance/platform-accounts')
    w.unmount()
  })
  it('exposes W371 21 empty conversation, real account CTA and native refresh without fake contact or Composer',async()=>{
    push.mockReset()
    const w=mount(YanceEmptyConversation)
    expect(w.get('[data-w371-native-empty-conversation]').text()).toContain('目前没有真实对话')
    expect(w.text()).toContain('不会为了展示旧设计而创建虚构联系人')
    expect(w.find('textarea').exists()).toBe(false)
    await w.get('[data-w371-empty-connect]').trigger('click')
    expect(push).toHaveBeenCalledWith('/yance/platform-accounts')
    await w.find('.w371-empty-conversation__refresh').trigger('click')
    expect(w.emitted('refresh')?.length).toBe(1)
    w.unmount()
  })
})
