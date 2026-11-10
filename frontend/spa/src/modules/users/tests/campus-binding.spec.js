import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { clearSession, session } from '../../../shared/session.js'
import { ApiError } from '../../../shared/http.js'
import { bindCampus, campuses, getBinding, me } from '../api.js'
import CampusBindingPage from '../pages/CampusBindingPage.vue'

vi.mock('../api.js', () => ({
  getBinding: vi.fn(),
  bindCampus: vi.fn(),
  campuses: vi.fn(),
  me: vi.fn(),
}))

const user = { id: 'u1', username: 'student1', nickname: '小明', is_campus_verified: false, verification_mode: null }
const bindingView = {
  campus_id: 'campus_main',
  student_no_masked: '****0004',
  verification_mode: 'demo',
  verified_at: '2026-11-02T08:00:00Z',
}
const campusList = [{ id: 'campus_main', name: '主校区' }]

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/demo', component: { template: '<div />' } },
      { path: '/me/profile', component: { template: '<div />' } },
      { path: '/claims/new', component: { template: '<div />' } },
      { path: '/me/campus-binding', component: CampusBindingPage },
    ],
  })
}

async function mountPage(query = '') {
  const router = makeRouter()
  await router.push(`/me/campus-binding${query}`)
  await router.isReady()
  const wrapper = mount(CampusBindingPage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

async function fillForm(wrapper, { studentNo = '20260004', bindingCode = 'e2e-binding-0001' } = {}) {
  await wrapper.get('#binding-student-no').setValue(studentNo)
  await wrapper.get('#binding-code').setValue(bindingCode)
}

beforeEach(() => {
  vi.resetAllMocks()
  clearSession()
  getBinding.mockResolvedValue(null)
  campuses.mockResolvedValue(campusList)
  me.mockResolvedValue(user)
})

describe('校园身份绑定页', () => {
  it('未绑定时展示校区下拉与表单', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('绑定校园身份')
    expect(wrapper.find('select#binding-campus').exists()).toBe(true)
    expect(wrapper.get('#binding-campus').element.value).toBe('campus_main')
    expect(wrapper.find('input#binding-campus').exists()).toBe(false)
    expect(wrapper.get('select#binding-campus').findAll('option')).toHaveLength(2)
  })

  it('校区字典不可用时降级为文本输入并默认 main', async () => {
    campuses.mockRejectedValue(new ApiError('服务返回了无法解析的响应', 404))
    const { wrapper } = await mountPage()
    expect(wrapper.find('select#binding-campus').exists()).toBe(false)
    expect(wrapper.get('input#binding-campus').element.value).toBe('main')
    expect(wrapper.text()).toContain('暂时无法读取校区选项')
  })

  it('已绑定时展示校区、脱敏学号、认证方式与绑定时间', async () => {
    getBinding.mockResolvedValue(bindingView)
    const { wrapper } = await mountPage()
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).toContain('已绑定校园身份')
    expect(wrapper.text()).toContain('主校区（campus_main）')
    expect(wrapper.text()).toContain('****0004')
    expect(wrapper.text()).toContain('演示认证')
    expect(wrapper.text()).toContain('不是真实学校认证')
    expect(wrapper.text()).toContain('2026')
  })

  it('绑定成功后重新读取绑定、刷新会话并展示结果', async () => {
    getBinding.mockResolvedValueOnce(null).mockResolvedValue(bindingView)
    bindCampus.mockResolvedValue(bindingView)
    me.mockResolvedValue({ ...user, is_campus_verified: true, verification_mode: 'demo' })
    const { wrapper } = await mountPage()
    await fillForm(wrapper)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(bindCampus).toHaveBeenCalledWith({ campus_id: 'campus_main', student_no: '20260004', binding_code: 'e2e-binding-0001' })
    expect(getBinding).toHaveBeenCalledTimes(2)
    expect(me).toHaveBeenCalledTimes(1)
    expect(session.user.is_campus_verified).toBe(true)
    expect(wrapper.get('[role=status]').text()).toContain('校园身份绑定成功')
    expect(wrapper.text()).toContain('****0004')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('绑定码错误展示在绑定码输入下方', async () => {
    bindCampus.mockRejectedValue(new ApiError('参数错误', 400, 'VALIDATION_ERROR', { binding_code: ['绑定码无效或已被使用'] }))
    const { wrapper } = await mountPage()
    await fillForm(wrapper)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(bindCampus).toHaveBeenCalledTimes(1)
    expect(wrapper.get('.field-error').text()).toContain('绑定码无效或已被使用')
    expect(wrapper.find('form').exists()).toBe(true)
  })

  it('身份已被占用时给出冲突提示', async () => {
    bindCampus.mockRejectedValue(new ApiError('该校园身份已被绑定', 409, 'DUPLICATE_RESOURCE'))
    const { wrapper } = await mountPage()
    await fillForm(wrapper)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('已被绑定')
  })

  it('学号格式不合规时不发送请求', async () => {
    const { wrapper } = await mountPage()
    await fillForm(wrapper, { studentNo: '12' })
    await wrapper.get('form').trigger('submit')
    expect(bindCampus).not.toHaveBeenCalled()
    expect(wrapper.get('.field-error').text()).toContain('学号需为 6～20 位字母或数字')
  })

  it('提交期间禁用输入与按钮，防止重复提交', async () => {
    let finish
    bindCampus.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    getBinding.mockResolvedValueOnce(null).mockResolvedValue(bindingView)
    const { wrapper } = await mountPage()
    await fillForm(wrapper)
    await wrapper.get('form').trigger('submit')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(bindCampus).toHaveBeenCalledTimes(1)
    expect(wrapper.get('button[type=submit]').element.disabled).toBe(true)
    expect(wrapper.get('#binding-student-no').element.disabled).toBe(true)
    finish(bindingView)
    await flushPromises()
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('认证完成后提供返回原操作页面的入口（next）', async () => {
    getBinding.mockResolvedValueOnce(null).mockResolvedValue(bindingView)
    bindCampus.mockResolvedValue(bindingView)
    me.mockResolvedValue({ ...user, is_campus_verified: true, verification_mode: 'demo' })
    const { wrapper } = await mountPage('?next=/claims/new?post_id=9')
    await fillForm(wrapper)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('认证完成，继续刚才的操作')
    const link = wrapper.findAll('a').find(item => item.text().includes('认证完成'))
    expect(link.attributes('href')).toContain('/claims/new?post_id=9')
  })
})
