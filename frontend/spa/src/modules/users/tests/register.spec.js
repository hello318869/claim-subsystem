import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { ApiError } from '../../../shared/http.js'
import { register } from '../api.js'
import RegisterPage from '../pages/RegisterPage.vue'

vi.mock('../api.js', () => ({ register: vi.fn() }))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/login', component: { template: '<div />' } },
      { path: '/register', component: RegisterPage },
    ],
  })
}

async function mountRegister() {
  const router = makeRouter()
  await router.push('/register')
  await router.isReady()
  const wrapper = mount(RegisterPage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

async function fill(wrapper, { username = 'student1', nickname = '小明', password = 'secret-123', confirm = 'secret-123' } = {}) {
  await wrapper.get('#register-username').setValue(username)
  await wrapper.get('#register-nickname').setValue(nickname)
  await wrapper.get('#register-password').setValue(password)
  await wrapper.get('#register-confirm').setValue(confirm)
}

beforeEach(() => { vi.resetAllMocks() })

describe('注册页', () => {
  it('渲染四个字段且账号不合规时不发送请求', async () => {
    const { wrapper } = await mountRegister()
    expect(wrapper.text()).toContain('注册新账号')
    await fill(wrapper, { username: 'ab' })
    await wrapper.get('form').trigger('submit')
    expect(register).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('账号需为 4～32 位字母、数字或下划线')
  })

  it('密码不一致与过短密码都在前端拦截', async () => {
    const { wrapper } = await mountRegister()
    await fill(wrapper, { password: '12345678', confirm: '87654321' })
    await wrapper.get('form').trigger('submit')
    expect(register).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('两次输入的密码不一致')
    await fill(wrapper, { password: 'short', confirm: 'short' })
    await wrapper.get('form').trigger('submit')
    expect(wrapper.text()).toContain('密码长度需为 8～64 个字符')
  })

  it('注册成功后不自动登录，跳登录页并带入账号', async () => {
    register.mockResolvedValue({ id: 'u9', username: 'student1', nickname: '小明', is_campus_verified: false })
    const { wrapper, router } = await mountRegister()
    await fill(wrapper, { username: '  student1  ', nickname: '  小明  ' })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(register).toHaveBeenCalledWith({ username: 'student1', nickname: '小明', password: 'secret-123' })
    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query).toMatchObject({ registered: '1', username: 'student1' })
  })

  it('服务端字段错误展示在对应输入下方', async () => {
    register.mockRejectedValue(new ApiError('参数错误', 400, 'VALIDATION_ERROR', { username: ['该账号已存在'] }))
    const { wrapper } = await mountRegister()
    await fill(wrapper)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('.field-error').text()).toContain('该账号已存在')
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
  })

  it('重复注册 409 给出明确提示', async () => {
    register.mockRejectedValue(new ApiError('该账号已被注册', 409, 'DUPLICATE_RESOURCE'))
    const { wrapper } = await mountRegister()
    await fill(wrapper)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('该账号已被注册')
  })

  it('提交期间禁用全部输入与按钮', async () => {
    let finish
    register.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const { wrapper } = await mountRegister()
    await fill(wrapper)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('button[type=submit]').element.disabled).toBe(true)
    expect(wrapper.get('#register-username').element.disabled).toBe(true)
    expect(wrapper.get('#register-password').element.disabled).toBe(true)
    finish({ id: 'u9' })
    await flushPromises()
    expect(wrapper.get('button[type=submit]').element.disabled).toBe(false)
  })
})
