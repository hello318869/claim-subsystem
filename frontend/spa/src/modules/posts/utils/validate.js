import {
  ALLOWED_IMAGE_TYPES,
  ALT_TEXT_MAX,
  ALT_TEXT_MIN,
  LIMITS,
  MAX_IMAGE_BYTES,
  MAX_IMAGES,
} from '../config.js'
import { charLength } from './format.js'

/*
 * 前端预校验：只做契约里写明的长度/必填/时间约束，用来提前给出提示。
 * 返回结构与后端 400 的 errors 一致：{ field: ['提示'] }，页面用同一套渲染逻辑。
 * 服务端始终是最终裁判，前端校验通过不代表接口一定 200/201。
 */

function push(errors, field, message) {
  if (!errors[field]) errors[field] = []
  errors[field].push(message)
}

function checkLength(errors, field, value, { min, max }, label) {
  const length = charLength(value)
  if (min > 0 && length === 0) {
    push(errors, field, `${label}不能为空`)
    return
  }
  if (length > 0 && length < min) {
    push(errors, field, `${label}至少 ${min} 字（当前 ${length} 字）`)
  }
  if (length > max) {
    push(errors, field, `${label}不能超过 ${max} 字（当前 ${length} 字）`)
  }
}

export function validatePostDraft(draft, { mode = 'create' } = {}) {
  const errors = {}

  if (mode === 'create' && !['lost', 'found'].includes(draft.post_type)) {
    push(errors, 'post_type', '请选择信息类型（失物 / 招领）')
  }

  checkLength(errors, 'title', draft.title, LIMITS.title, '标题')

  if (!draft.category_id) push(errors, 'category_id', '请选择物品类别')
  if (!draft.location_id) push(errors, 'location_id', '请选择发生地点')

  checkLength(errors, 'description', draft.description, LIMITS.description, '描述')
  checkLength(errors, 'location_detail', draft.location_detail, LIMITS.location_detail, '详细地点')

  if (!draft.occurred_at) {
    push(errors, 'occurred_at', '请选择丢失或拾获时间')
  } else {
    const time = new Date(draft.occurred_at).getTime()
    if (Number.isNaN(time)) {
      push(errors, 'occurred_at', '时间格式不正确')
    } else if (time > Date.now() + 60 * 1000) {
      push(errors, 'occurred_at', '时间不能晚于当前时间（按北京时间填写）')
    }
  }

  if (draft.post_type === 'found') {
    checkLength(errors, 'handover_note', draft.handover_note, LIMITS.handover_note, '保管 / 交接说明')
  }

  if (Array.isArray(draft.image_ids) && draft.image_ids.length > MAX_IMAGES) {
    push(errors, 'image_ids', `最多 ${MAX_IMAGES} 张图片`)
  }

  return errors
}

export function validateResolveNote(note) {
  const errors = {}
  checkLength(errors, 'resolve_note', note, LIMITS.resolve_note, '办结说明')
  return errors
}

/** 上传前的本地预检（类型 + 大小），真正的格式校验以服务端为准 */
export function validateImageFile(file) {
  if (!file) return '请选择图片文件'
  if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
    return `不支持的格式：${file.type || '未知类型'}，只允许 ${ALLOWED_IMAGE_TYPES.join(' / ')}`
  }
  if (file.size > MAX_IMAGE_BYTES) {
    return `图片 ${(file.size / (1024 * 1024)).toFixed(2)} MiB，超过单张 5 MiB 限制`
  }
  if (file.size === 0) return '图片为空文件'
  return ''
}

/**
 * 把后端 errors 归一化成 { field: [字符串] }：
 * 兼容 [{ field, message }] 这类数组形式，避免页面因结构差异白屏。
 */
export function normalizeFieldErrors(raw) {
  const result = {}
  if (!raw) return result
  if (Array.isArray(raw)) {
    for (const item of raw) {
      if (!item) continue
      const field = item.field || item.name || 'non_field'
      const message = item.message || item.msg || String(item)
      if (!result[field]) result[field] = []
      result[field].push(message)
    }
    return result
  }
  if (typeof raw !== 'object') return result
  for (const [field, value] of Object.entries(raw)) {
    if (Array.isArray(value)) result[field] = value.map((item) => String(item))
    else if (value === undefined || value === null || value === '') continue
    else result[field] = [String(value)]
  }
  return result
}

export function firstFieldError(errors) {
  for (const [field, messages] of Object.entries(errors || {})) {
    if (messages && messages.length) return { field, message: messages[0] }
  }
  return null
}

export { ALT_TEXT_MIN, ALT_TEXT_MAX }
