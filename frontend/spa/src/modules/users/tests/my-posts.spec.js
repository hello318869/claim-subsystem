import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { myPosts } from '../api.js'
import MyPostsPage from '../pages/MyPostsPage.vue'

vi.mock('../api.js', () => ({ myPosts: vi.fn() }))

const post = {
  id: '1',
  post_type: 'found',
  title: '图书馆拾到蓝色钥匙',
  category: { id: 'cat_keys', name: '钥匙' },
  campus: { id: 'campus_main', name: '主校区' },
  location: { id: 'loc_library', name: '图书馆' },
  occurred_at: '2026-11-02T09:41:00Z',
  status: 'open',
  cover_image: null,
  publisher: { id: 'u1', nickname: '小林', is_campus_verified: true, verification_mode: 'demo' },
  created_at: '2026-11-02T09:41:00Z',
  updated_at: '2026-11-02T09:41:00Z',
}

function page(items = [post], extra = {}) {
  return { items, page: 1, page_size: 20, total: items.length, total_pages: items.length ? 1 : 0, ...extra }
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/me/posts', component: MyPostsPage },
      { path: '/me/profile', component: { template: '<div />' } },
      { path: '/posts/:id', name: 'post-detail', component: { template: '<div />' } },
      { path: '/posts/:id/matches', component: { template: '<div />' } },
    ],
  })
}

async function mountPage() {
  const router = makeRouter()
  await router.push('/me/posts')
  await router.isReady()
  const wrapper = mount(MyPostsPage, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.resetAllMocks()
  myPosts.mockResolvedValue(page())
})

describe('我的发布页', () => {
  it('加载并展示本人发布的信息与类型/状态中文文案', async () => {
    const { wrapper } = await mountPage()
    expect(myPosts).toHaveBeenCalledWith({ post_type: undefined, status: undefined, page: 1, page_size: 20 })
    expect(wrapper.text()).toContain('我的发布')
    expect(wrapper.text()).toContain('图书馆拾到蓝色钥匙')
    expect(wrapper.text()).toContain('招领')
    expect(wrapper.text()).toContain('进行中')
    expect(wrapper.get('a[href="/posts/1"]').text()).toBe('查看详情')
    expect(wrapper.get('a[href="/posts/1/matches"]').text()).toBe('查看匹配线索')
  })

  it('按类型/状态筛选时重新查询并回到第 1 页', async () => {
    const { wrapper } = await mountPage()
    await wrapper.get('#my-post-type').setValue('lost')
    await flushPromises()
    expect(myPosts).toHaveBeenLastCalledWith({ post_type: 'lost', status: undefined, page: 1, page_size: 20 })

    await wrapper.get('#my-post-status').setValue('completed')
    await flushPromises()
    expect(myPosts).toHaveBeenLastCalledWith({ post_type: 'lost', status: 'completed', page: 1, page_size: 20 })
  })

  it('分页切换会按新页码查询', async () => {
    myPosts.mockResolvedValueOnce(page([post], { total: 21, total_pages: 2 }))
    myPosts.mockResolvedValueOnce(page([post], { page: 2, total: 21, total_pages: 2 }))
    const { wrapper } = await mountPage()
    const next = wrapper.findAll('button').find(button => button.text() === '下一页')
    await next.trigger('click')
    await flushPromises()
    expect(myPosts).toHaveBeenLastCalledWith({ post_type: undefined, status: undefined, page: 2, page_size: 20 })
  })

  it('没有发布记录时展示空状态', async () => {
    myPosts.mockResolvedValue(page([]))
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('还没有发布记录')
    expect(wrapper.find('.my-posts').exists()).toBe(false)
  })

  it('接口失败时展示错误并可重试', async () => {
    myPosts.mockRejectedValueOnce({ status: 500, code: 'INTERNAL_ERROR', errors: {}, message: '服务暂时不可用' })
    myPosts.mockResolvedValue(page())
    const { wrapper } = await mountPage()
    expect(wrapper.get('[role=alert]').text()).toContain('服务暂时不可用')
    await wrapper.get('[role=alert] button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('图书馆拾到蓝色钥匙')
  })
})
