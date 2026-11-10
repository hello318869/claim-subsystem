import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { clearSession, session } from '../../../shared/session.js'
import { ApiError } from '../../../shared/http.js'
import { me, updateMe } from '../api.js'
import ProfilePage from '../pages/ProfilePage.vue'

vi.mock('../api.js', () => ({ me: vi.fn(), updateMe: vi.fn() }))

const profile = {
  id: 'u1',
  username: 'student1',
  nickname: '小明',
  bio: '喜欢在图书馆看书',
  is_campus_verified: true,
  verification_mode: 'demo',
  created_at: '2026-11-01T10:00:00Z',
  updated_at: '2026-11-02T10:00:00Z',
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/demo', component: { template: '<div />' } },
      { path: '/me/profile', component: ProfilePage },
      { path: '/me/posts', component: { template: '<div />' } },
      { path: '/me/campus-binding', component: { template: '<div />' } },
    ],
  })
}

async function mountProfile() {
  const router = makeRouter()
  await router.push('/me/profile')
  await router.isReady()
  const wrapper = mount(ProfilePage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.resetAllMocks()
  clearSession()
  me.mockResolvedValue(profile)
})

describe('个人资料页', () => {
  it('加载本人资料并展示账号、注册时间与认证状态', async () => {
    const { wrapper } = await mountProfile()
    expect(me).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('个人中心')
    expect(wrapper.text()).toContain('student1')
    expect(wrapper.text()).toContain('演示认证')
    expect(wrapper.get('#profile-nickname').element.value).toBe('小明')
    expect(wrapper.get('#profile-bio').element.value).toBe('喜欢在图书馆看书')
    expect(wrapper.text()).toContain('2026')
  })

  it('未认证时显示未认证并提供校园身份绑定入口', async () => {
    me.mockResolvedValue({ ...profile, is_campus_verified: false, verification_mode: null })
    const { wrapper } = await mountProfile()
    expect(wrapper.text()).toContain('未认证')
    const link = wrapper.get('a[href="/me/campus-binding"]')
    expect(link.text()).toContain('校园身份绑定')
  })

  it('保存资料调用 updateMe 并同步内存会话', async () => {
    updateMe.mockResolvedValue({ ...profile, nickname: '小明同学', bio: '新的简介', updated_at: '2026-11-02T11:00:00Z' })
    const { wrapper } = await mountProfile()
    await wrapper.get('#profile-nickname').setValue('  小明同学  ')
    await wrapper.get('#profile-bio').setValue('  新的简介  ')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(updateMe).toHaveBeenCalledWith({ nickname: '小明同学', bio: '新的简介' })
    expect(wrapper.get('[role=status]').text()).toContain('资料已保存')
    expect(wrapper.get('#profile-nickname').element.value).toBe('小明同学')
    expect(session.user.nickname).toBe('小明同学')
    expect(session.user.bio).toBe('新的简介')
  })

  it('空昵称不发请求并提示字段错误', async () => {
    const { wrapper } = await mountProfile()
    await wrapper.get('#profile-nickname').setValue('   ')
    await wrapper.get('form').trigger('submit')
    expect(updateMe).not.toHaveBeenCalled()
    expect(wrapper.get('.field-error').text()).toContain('昵称需为 1～30 个字符')
  })

  it('服务端字段错误展示在输入下方', async () => {
    updateMe.mockRejectedValue(new ApiError('参数错误', 400, 'VALIDATION_ERROR', { nickname: ['昵称不能超过 30 个字符'] }))
    const { wrapper } = await mountProfile()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('.field-error').text()).toContain('昵称不能超过 30 个字符')
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
  })

  it('加载失败展示错误并可重试', async () => {
    me.mockRejectedValueOnce(new ApiError('服务暂不可用', 500, 'INTERNAL_ERROR'))
    const { wrapper } = await mountProfile()
    expect(wrapper.get('[role=alert]').text()).toContain('服务暂不可用')
    me.mockResolvedValue(profile)
    await wrapper.get('[role=alert] button').trigger('click')
    await flushPromises()
    expect(wrapper.get('#profile-nickname').element.value).toBe('小明')
  })
})
