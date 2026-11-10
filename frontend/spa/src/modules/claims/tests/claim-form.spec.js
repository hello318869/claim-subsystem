import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ClaimForm from '../components/ClaimForm.vue'

describe('认领证明表单', () => {
  it('空白和过短证明不能提交，并说明还差几个字', async () => {
    const wrapper = mount(ClaimForm)
    expect(wrapper.get('button').element.disabled).toBe(true)
    await wrapper.get('textarea').setValue('  很短  ')
    expect(wrapper.get('button').element.disabled).toBe(true)
    expect(wrapper.text()).toContain('认领证明至少需要 10 个字')
    expect(wrapper.text()).toContain('还差')
    expect(wrapper.text()).toContain('至少 10 字')
  })
  it('提交时去除前后空白', async () => {
    const wrapper = mount(ClaimForm)
    await wrapper.get('textarea').setValue('  我的钥匙有三把和一个蓝色挂件。  ')
    expect(wrapper.get('button').element.disabled).toBe(false)
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')).toEqual([['我的钥匙有三把和一个蓝色挂件。']])
  })
  it('请求期间禁用编辑和重复提交', () => {
    const wrapper = mount(ClaimForm, { props: { busy: true } })
    expect(wrapper.get('textarea').element.disabled).toBe(true)
    expect(wrapper.get('button').element.disabled).toBe(true)
  })
})
