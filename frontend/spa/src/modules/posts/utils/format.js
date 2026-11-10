import { BEIJING_OFFSET_MINUTES } from '../config.js'

/*
 * 契约 §2.1：响应时间为 UTC ISO 8601，页面按北京时间显示。
 * 这里不依赖浏览器本地时区，固定按 UTC+8 换算，避免同学在不同时区看到不同时间。
 */

const OFFSET_MS = BEIJING_OFFSET_MINUTES * 60 * 1000

function pad(value) {
  return String(value).padStart(2, '0')
}

function toBeijingDate(iso) {
  if (!iso) return null
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return null
  return new Date(parsed.getTime() + OFFSET_MS)
}

export function formatBeijingDateTime(iso) {
  const date = toBeijingDate(iso)
  if (!date) return '—'
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ` +
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
  )
}

export function formatBeijingDate(iso) {
  const date = toBeijingDate(iso)
  if (!date) return '—'
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
}

/** UTC ISO -> <input type="datetime-local"> 的值（北京时间） */
export function toBeijingInputValue(iso) {
  const date = toBeijingDate(iso)
  if (!date) return ''
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}T` +
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
  )
}

export function nowBeijingInputValue() {
  return toBeijingInputValue(new Date().toISOString())
}

/** <input type="datetime-local"> 的值（按北京时间理解）-> UTC ISO */
export function beijingInputToUtc(value) {
  if (!value) return ''
  const text = String(value).trim()
  const withSeconds = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text) ? `${text}:00` : text
  const parsed = new Date(`${withSeconds}+08:00`)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toISOString().replace('.000Z', 'Z')
}

/** 日期选择器（yyyy-MM-dd，北京时间当天 00:00）-> UTC ISO 下界 */
export function dateInputToUtcStart(value) {
  if (!value) return ''
  const parsed = new Date(`${value}T00:00:00+08:00`)
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString().replace('.000Z', 'Z')
}

/** 日期选择器（yyyy-MM-dd，北京时间当天 23:59:59）-> UTC ISO 上界 */
export function dateInputToUtcEnd(value) {
  if (!value) return ''
  const parsed = new Date(`${value}T23:59:59+08:00`)
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString().replace('.000Z', 'Z')
}

/** UTC ISO -> yyyy-MM-dd（北京时间），用于回填日期筛选 */
export function toBeijingDateInputValue(iso) {
  return formatBeijingDate(iso) === '—' ? '' : formatBeijingDate(iso)
}

export function formatFileSize(bytes) {
  const size = Number(bytes)
  if (!Number.isFinite(size) || size <= 0) return '—'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(2)} MiB`
}

/** 字符数（按 Unicode 码点计，和服务端“按字符数计算”一致） */
export function charLength(text) {
  return Array.from(String(text ?? '')).length
}
