import { session, clearSession, sessionSignal } from './session.js'

export const API_BASE = '/api/v1'

export class ApiError extends Error {
  constructor(message, status = 0, code = 'NETWORK_ERROR', errors = {}) {
    super(message)
    this.name = 'ApiError'
    Object.assign(this, { status, code, errors })
  }

  get hasFieldErrors() {
    return this.status === 400 && Object.keys(this.errors).length > 0
  }
}

export async function request(path, {
  method = 'GET', body, formData, query, signal, withAuth = true, anonymousRetry = false,
  authToken = session.token, sessionScoped = true,
} = {}) {
  const params = new URLSearchParams(Object.entries(query || {}).filter(([, value]) => value !== undefined && value !== null && value !== ''))
  const url = `${API_BASE}${path}${params.size ? `?${params}` : ''}`
  const send = async (token) => {
    const headers = { Accept: 'application/json' }
    if (token) headers.Authorization = `Bearer ${token}`
    if (!formData && body !== undefined) headers['Content-Type'] = 'application/json'
    const lifetime = withAuth && sessionScoped ? sessionSignal() : null
    const requestSignal = lifetime && signal ? AbortSignal.any([lifetime, signal]) : (lifetime ?? signal)
    try {
      return await fetch(url, {
        method, headers, signal: requestSignal, cache: 'no-store', credentials: 'omit',
        body: formData ?? (body === undefined ? undefined : JSON.stringify(body)),
      })
    } catch (error) {
      if (error.name === 'AbortError') throw error
      throw new ApiError('无法连接服务，请检查连接后再试')
    }
  }

  const token = withAuth ? authToken : null
  let revision = session.revision
  let response = await send(token)
  if (response.status === 401 && token && token === session.token && session.revision === revision) {
    clearSession()
    revision = session.revision
    if (anonymousRetry && method === 'GET') response = await send(null)
  }

  let result = null
  try { result = await response.json() } catch (error) {
    if (error.name === 'AbortError') throw error
  }
  if (!response.ok) {
    throw new ApiError(result?.message || '请求失败', response.status, result?.code || `HTTP_${response.status}`, result?.errors || {})
  }
  if (withAuth && sessionScoped && session.revision !== revision) throw new DOMException('会话已切换', 'AbortError')
  if (result?.code !== 'OK' || !Object.hasOwn(result, 'data')) {
    throw new ApiError('服务返回了无法识别的响应', response.status, 'INVALID_RESPONSE')
  }
  return result.data
}

export function errorText(error) {
  const fields = Object.entries(error.errors || {}).map(([key, values]) => `${key}：${Array.isArray(values) ? values.join('；') : values}`)
  return fields.length ? fields.join('；') : error.message || '请求失败'
}
