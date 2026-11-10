import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { clearSession, session } from '../../../shared/session.js'
import { ApiError } from '../../../shared/http.js'
import { login } from '../api.js'
import LoginPage from '../pages/LoginPage.vue'

vi.mock('../api.js', () => ({ login: vi.fn() }))

const demoUser = { id: 'u1', username: 'student1', nickname: '新同学', is_campus_verified: false }

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/login', component: LoginPage },
      { path: '/register', component: { template: '<div />' } },
      { path: '/demo', component: { template: '<div />' } },
      { path: '/me/profile', component: { template: '<div />' } },
    ],
  })
}

async function mountLogin(path = '/login') {
  const router = makeRouter()
  await router.push(path)
  await router.isReady()
  const wrapper = mount(LoginPage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.resetAllMocks()
  clearSession()
})
afterEach(() => { clearSession() })

describe('登录页', () => {
  it('渲染账号、密码与登录入口，注册成功时提示并带入账号', async () => {
    const { wrapper } = await mountLogin('/login?registered=1&username=student1')
    expect(wrapper.text()).toContain('注册成功')
    expect(wrapper.text()).toContain('student1')
    expect(wrapper.get('#login-username').element.value).toBe('student1')
    expect(wrapper.get('#login-password').element.type).toBe('password')
    expect(wrapper.get('button[type=submit]').text()).toBe('登录')
    expect(wrapper.get('a[href="/register"]').exists()).toBe(true)
    expect(wrapper.get('a[href="/demo"]').exists()).toBe(true)
  })

  it('空表单不发送请求并分别提示字段', async () => {
    const { wrapper } = await mountLogin()
    await wrapper.get('form').trigger('submit')
    expect(login).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请输入账号')
    expect(wrapper.text()).toContain('请输入密码')
  })

  it('登录成功后写入会话并回跳 next', async () => {
    login.mockResolvedValue({ access_token: 'token-1', token_type: 'Bearer', expires_at: '2026-11-03T00:00:00Z', user: demoUser })
    const { wrapper, router } = await mountLogin('/login?next=/me/profile')
    await wrapper.get('#login-username').setValue('  student1  ')
    await wrapper.get('#login-password').setValue('secret-123')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(login).toHaveBeenCalledWith({ username: 'student1', password: 'secret-123' })
    expect(session.token).toBe('token-1')
    expect(session.user.nickname).toBe('新同学')
    expect(router.currentRoute.value.path).toBe('/me/profile')
  })

  it('拒绝非站内 next，回退到演示工作台', async () => {
    login.mockResolvedValue({ access_token: 'token-2', user: demoUser })
    const { wrapper, router } = await mountLogin('/login?next=//evil.example')
    await wrapper.get('#login-username').setValue('student1')
    await wrapper.get('#login-password').setValue('secret-123')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/demo')
  })

  it('服务端错误统一提示且不写入会话', async () => {
    login.mockRejectedValue(new ApiError('账号或密码错误', 401, 'UNAUTHENTICATED'))
    const { wrapper, router } = await mountLogin()
    await wrapper.get('#login-username').setValue('student1')
    await wrapper.get('#login-password').setValue('wrong-password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('账号或密码错误')
    expect(session.token).toBeNull()
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('提交期间禁用按钮，完成后恢复', async () => {
    let finish
    login.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const { wrapper } = await mountLogin()
    await wrapper.get('#login-username').setValue('student1')
    await wrapper.get('#login-password').setValue('secret-123')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('button[type=submit]').element.disabled).toBe(true)
    expect(wrapper.get('button[type=submit]').text()).toBe('登录中…')
    finish({ access_token: 'token-3', user: demoUser })
    await flushPromises()
    expect(wrapper.get('button[type=submit]').element.disabled).toBe(false)
  })
})
