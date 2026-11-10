import { hasToken } from '../api/session.js'

/*
 * 图片可见性规则（契约 §3.6 / §7.2 第 13 条）：
 *   1. 信息撤回后，其全部图片一律不可读（仅发布者本人可读），不因 is_public=true 而保留；
 *   2. 已绑定且 is_public=true 的图片匿名可读；
 *   3. is_public=false 的图片需要登录（带 Bearer 令牌取 Blob 预览，不把令牌拼进 URL）；
 *   4. 未登录遇到不可读图片：显示 alt_text 占位，不请求原图（E3 US-11）。
 */
export function isImageReadable(image, { postStatus = 'open', isOwner = false } = {}) {
  if (!image) return false
  if (postStatus === 'withdrawn') return isOwner
  if (image.is_public) return true
  return hasToken()
}

export function imageVisibilityLabel(image) {
  if (!image) return '无图片'
  return image.is_public ? '未登录可见' : '需登录查看'
}

export function imageAltText(image) {
  const text = image?.alt_text ? String(image.alt_text).trim() : ''
  return text || '（这张图片没有替代文字）'
}
