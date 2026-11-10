import { afterEach, describe, expect, it, vi } from 'vitest'
import { request } from './http.js'
import { clearSession, session, setSession } from './session.js'
afterEach(() => { clearSession(); vi.unstubAllGlobals() })

describe('HTTP 会话边界', () => {
  it('有效令牌从内存加入请求头', async () => {
    setSession({ access_token: 'test-token', user: { id: '1' } })
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ code: 'OK', data: [] }) })
    vi.stubGlobal('fetch', fetcher)
    expect(await request('/claims/1/messages')).toEqual([])
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBe('Bearer test-token')
  })
  it('401 清除当前会话', async () => {
    setSession({ access_token: 'expired', user: { id: '1' } })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ code: 'UNAUTHENTICATED', message: '已过期' }) }))
    await expect(request('/claims/1')).rejects.toMatchObject({ status: 401 })
    expect(session.token).toBeNull()
  })
  it('旧请求的 401 不清除新登录会话', async () => {
    setSession({ access_token: 'old', user: { id: '1' } })
    let finish
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise(resolve => { finish = resolve })))
    const pending = request('/claims/1')
    setSession({ access_token: 'new', user: { id: '2' } })
    finish({ ok: false, status: 401, json: async () => ({ code: 'UNAUTHENTICATED', message: '已过期' }) })
    await expect(pending).rejects.toMatchObject({ status: 401 })
    expect(session.token).toBe('new')
  })
  it('退出时立即中止本会话的请求', async () => {
    setSession({ access_token: 'active', user: { id: '1' } })
    const fetcher = vi.fn((url, { signal }) => new Promise((_, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true })
    }))
    vi.stubGlobal('fetch', fetcher)
    const pending = request('/claims/1')
    clearSession()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
  })
})
