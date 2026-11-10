import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { clearSession, session } from '../../../shared/session.js'
import { getPost } from '../api.js'
import ClaimCreatePage from '../pages/ClaimCreatePage.vue'

vi.mock('../api.js', () => ({
  getPost: vi.fn(),
  createClaim: vi.fn(),
}))

const post = {
  id: '9',
  post_type: 'found',
  status: 'open',
  title: '图书馆拾到钥匙',
  description: '在图书馆二楼拾到一串钥匙。',
  location: { id: 'loc_library', name: '图书馆' },
  occurred_at: '2026-11-02T08:00:00Z',
  publisher: { id: 'p1', nickname: '拾获者' },
  handover_note: '核实后交接',
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/team', component: { template: '<div />' } },
      { path: '/claims/new', component: ClaimCreatePage },
      { path: '/claims/:id', component: { template: '<div />' } },
      { path: '/me/campus-binding', component: { template: '<div />' } },
      { path: '/me/claims', component: { template: '<div />' } },
    ],
  })
}

async function mountClaimPage() {
  const router = makeRouter()
  await router.push('/claims/new?post_id=9')
  await router.isReady()
  const wrapper = mount(ClaimCreatePage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.resetAllMocks()
  clearSession()
  getPost.mockResolvedValue(post)
})

describe('认领页的未认证引导', () => {
  it('未认证时说明原因，并提供去校园身份认证的入口（带返回地址）', async () => {
    session.user = { id: 'u2', nickname: '新同学', is_campus_verified: false }
    const { wrapper } = await mountClaimPage()
    expect(wrapper.text()).toContain('请先完成校园身份绑定，再提交认领申请')
    expect(wrapper.find('form').exists()).toBe(false)
    const link = wrapper.get('a.button')
    expect(link.text()).toContain('去完成校园身份认证')
    expect(link.attributes('href')).toContain('/me/campus-binding')
    expect(link.attributes('href')).toContain('claims')
  })

  it('已认证时正常展示认领表单', async () => {
    session.user = { id: 'u2', nickname: '已认证', is_campus_verified: true }
    const { wrapper } = await mountClaimPage()
    expect(wrapper.find('form').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('请先完成校园身份绑定')
  })

  it('可申请认领未绑定发布者的失物，并显示交接提醒', async () => {
    session.user = { id: 'u2', nickname: '已认证', is_campus_verified: true }
    getPost.mockResolvedValue({ ...post, post_type: 'lost', publisher: { ...post.publisher, is_campus_verified: false } })
    const { wrapper } = await mountClaimPage()
    expect(wrapper.find('form').exists()).toBe(true)
    expect(wrapper.text()).toContain('对方为校外人员，建议在失物招领处交接')
  })
})
