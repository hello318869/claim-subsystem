import { API_BASE, ApiError } from '../../../shared/http.js'
import { clearSession, session } from '../../../shared/session.js'

export { ApiError, request, errorText as describeError } from '../../../shared/http.js'

export function imageContentUrl(imageId) {
  return `${API_BASE}/post-images/${encodeURIComponent(imageId)}/content`
}

export async function fetchImageBlob(imageId, signal) {
  const { token, revision } = session
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  let response
  try {
    response = await fetch(imageContentUrl(imageId), { headers, cache: 'no-store', credentials: 'omit', signal })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new ApiError('图片加载失败，请检查网络或后端服务')
  }
  if (!response.ok) {
    if (response.status === 401 && token && session.revision === revision) clearSession()
    const error = await response.json().catch(() => null)
    throw new ApiError(error?.message || '图片不可查看', response.status, error?.code)
  }
  const blob = await response.blob()
  if (session.revision !== revision || signal?.aborted) throw new DOMException('请求已失效', 'AbortError')
  return URL.createObjectURL(blob)
}
