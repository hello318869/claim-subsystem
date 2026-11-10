import { fetchImageBlob, imageContentUrl, request } from './http.js'

/*
 * B 子系统接口（契约 §5.1）：
 *   GET    /posts                 公开列表（分页 PostSummary）
 *   GET    /posts/{id}            详情（PostDetail）
 *   POST   /posts                 发布
 *   PATCH  /posts/{id}            编辑
 *   POST   /posts/{id}/withdraw   撤回
 *   POST   /posts/{id}/restore    恢复
 *   POST   /posts/{id}/resolve    失物自行办结（resolve_note 5~200 字）
 *   POST   /post-images           上传图片（multipart：file / alt_text / is_public）
 *   GET    /post-images/{id}/content  图片二进制
 */

const LIST_QUERY_KEYS = [
  'post_type',
  'keyword',
  'category_id',
  'campus_id',
  'location_id',
  'status',
  'occurred_from',
  'occurred_to',
  'sort',
  'page',
  'page_size',
]

/** 只提交契约 5.3 允许的参数，空字符串一律不传（避免 400）。 */
export function normalizeListQuery(filters = {}) {
  const query = {}
  for (const key of LIST_QUERY_KEYS) {
    const value = filters[key]
    if (value === undefined || value === null || value === '') continue
    if (key === 'page' || key === 'page_size') {
      const number = Number(value)
      if (!Number.isFinite(number) || number <= 0) continue
      query[key] = Math.trunc(number)
      continue
    }
    query[key] = value
  }
  return query
}

export function listPosts(filters, { signal } = {}) {
  return request('/posts', {
    query: normalizeListQuery(filters),
    anonymousRetry: true,
    signal,
  })
}

export function getPost(postId, { signal } = {}) {
  return request(`/posts/${encodeURIComponent(postId)}`, {
    anonymousRetry: true,
    signal,
  })
}

export function createPost(payload) {
  return request('/posts', { method: 'POST', body: payload })
}

export function updatePost(postId, payload) {
  return request(`/posts/${encodeURIComponent(postId)}`, { method: 'PATCH', body: payload })
}

export function withdrawPost(postId) {
  return request(`/posts/${encodeURIComponent(postId)}/withdraw`, { method: 'POST' })
}

export function restorePost(postId) {
  return request(`/posts/${encodeURIComponent(postId)}/restore`, { method: 'POST' })
}

export function resolvePost(postId, resolveNote) {
  return request(`/posts/${encodeURIComponent(postId)}/resolve`, {
    method: 'POST',
    body: { resolve_note: resolveNote },
  })
}

export function uploadPostImage({ file, altText, isPublic = true }) {
  const form = new FormData()
  form.append('file', file)
  form.append('alt_text', altText)
  // 契约：表单字段 is_public，布尔值用 true / false
  form.append('is_public', isPublic ? 'true' : 'false')
  return request('/post-images', { method: 'POST', formData: form })
}

export { fetchImageBlob, imageContentUrl }
