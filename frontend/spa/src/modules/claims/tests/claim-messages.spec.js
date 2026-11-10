import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { session, setSession, clearSession } from '../../../shared/session.js'
import { useClaimMessages } from '../composables/useClaimMessages.js'
import { getMessages, sendMessage } from '../api.js'
import ClaimChat from '../components/ClaimChat.vue'

vi.mock('../api.js', () => ({ getMessages: vi.fn(), sendMessage: vi.fn() }))
let scope
const row = id => ({ id, sender_id: '1', sender: { nickname: '失主' }, content: `消息${id}`, created_at: '2026-10-10T00:00:00Z' })
const empty = () => ({ items: [], next_after_id: null, has_more: false })
function start(id = ref('10')) {
  scope = effectScope()
  return scope.run(() => useClaimMessages(id))
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.resetAllMocks()
  setSession({ access_token: 'test', user: { id: '1' } })
  getMessages.mockResolvedValue(empty())
})
afterEach(() => { scope?.stop(); clearSession(); vi.useRealTimers() })

describe('消息游标、轮询和错误恢复', () => {
  it('先取全部历史，再按 ID 去重', async () => {
    getMessages.mockResolvedValueOnce({ items: [row('msg-z'), row('msg-a')], next_after_id: 'msg-a', has_more: true })
      .mockResolvedValueOnce({ items: [row('msg-a'), row('msg-q')], next_after_id: 'msg-q', has_more: false })
    const chat = start()
    await flushPromises()
    expect(chat.messages.value.map(message => message.id)).toEqual(['msg-z', 'msg-a', 'msg-q'])
    expect(getMessages.mock.calls[1][1]).toEqual({ after_id: 'msg-a', limit: 50 })
    expect(getMessages).toHaveBeenCalledTimes(2)
  })
  it('每五秒增量读取，卸载后停止', async () => {
    getMessages.mockResolvedValueOnce({ items: [row('1')], next_after_id: '1', has_more: false })
      .mockResolvedValue({ items: [], next_after_id: '1', has_more: false })
    start()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(5000)
    expect(getMessages.mock.calls[1][1].after_id).toBe('1')
    scope.stop()
    await vi.advanceTimersByTimeAsync(15000)
    expect(getMessages).toHaveBeenCalledTimes(2)
  })
  it('退出登录后停止轮询并清除会话消息', async () => {
    const chat = start()
    await flushPromises()
    clearSession()
    await nextTick()
    await vi.advanceTimersByTimeAsync(15000)
    expect(getMessages).toHaveBeenCalledTimes(1)
    expect(chat.messages.value).toEqual([])
  })
  it('切换申请中止旧读取，旧响应不会污染新会话', async () => {
    let resolveOld
    getMessages.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
      .mockResolvedValue({ items: [row('9')], next_after_id: '9', has_more: false })
    const id = ref('10')
    const chat = start(id)
    const signal = getMessages.mock.calls[0][2]
    id.value = '11'
    await nextTick()
    await flushPromises()
    expect(signal.aborted).toBe(true)
    resolveOld({ items: [row('1')], next_after_id: '1', has_more: false })
    await flushPromises()
    expect(chat.messages.value.map(message => message.id)).toEqual(['9'])
  })
  it('发送期间防止重复，成功后按会话顺序刷新', async () => {
    const chat = start()
    await flushPromises()
    let resolveSend
    sendMessage.mockImplementation(() => new Promise(resolve => { resolveSend = resolve }))
    const first = chat.send('你好')
    expect(await chat.send('重复')).toBe(false)
    getMessages.mockResolvedValueOnce({ items: [row('1')], next_after_id: '1', has_more: false })
    resolveSend(row('1'))
    expect(await first).toBe(true)
    expect(sendMessage).toHaveBeenCalledTimes(1)
    expect(chat.messages.value).toHaveLength(1)
  })
  it('发送结果不明时先刷新，不自动重发', async () => {
    const chat = start()
    await flushPromises()
    sendMessage.mockRejectedValue(new Error('network'))
    expect(await chat.send('你好')).toBe(false)
    expect(sendMessage).toHaveBeenCalledTimes(1)
    expect(getMessages).toHaveBeenCalledTimes(2)
    expect(chat.error.value).toContain('结果未确认')
  })
  it('消息中的 HTML 作为文本展示，终态没有发送表单', async () => {
    getMessages.mockResolvedValue({ items: [{ ...row('1'), content: '<img src=x onerror=alert(1)>' }], next_after_id: '1', has_more: false })
    const wrapper = mount(ClaimChat, { props: { claim: { id: '10', status: 'completed' } } })
    await flushPromises()
    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('form').exists()).toBe(false)
    wrapper.unmount()
  })
})
