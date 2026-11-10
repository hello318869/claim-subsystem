/*
 * 前端文案与配置常量。
 * 枚举值、字段名、长度限制全部来自《共同字段与接口约定-03.md》§3.5 / §3.6 / §5.3，
 * 只在这里做中文映射，不在页面里散落硬编码。
 */

export const POST_TYPE_TEXT = {
  lost: '失物',
  found: '招领',
}

export const POST_TYPE_HINT = {
  lost: '寻物启事：我丢了东西',
  found: '招领启事：我捡到了东西',
}

/** 契约 §3.5 信息状态：open / in_handover / completed / withdrawn */
export const STATUS_TEXT = {
  open: '进行中',
  in_handover: '交接中',
  completed: '已完成',
  withdrawn: '已撤回',
}

export const STATUS_HINT = {
  open: '仍可被申请认领，发布者可编辑、撤回或办结',
  in_handover: '认领已同意，等待双方确认交接；不可编辑',
  completed: '已完成，仍可公开查看，但不再参与默认匹配',
  withdrawn: '已撤回，公开列表与详情不可见；仅发布者可查看',
}

/** 公开列表允许的 status 筛选值（契约 §5.3：不允许 withdrawn） */
export const STATUS_FILTER_OPTIONS = [
  { value: '', label: '全部（进行中 + 交接中）' },
  { value: 'open', label: '进行中' },
  { value: 'in_handover', label: '交接中' },
  { value: 'completed', label: '已完成' },
]

export const SORT_OPTIONS = [
  { value: 'latest', label: '最新发布' },
  { value: 'occurred_latest', label: '发生时间' },
]

export const TYPE_TABS = [
  { value: '', label: '全部' },
  { value: 'lost', label: '失物' },
  { value: 'found', label: '招领' },
]

export const PAGE_SIZE_OPTIONS = [10, 20, 50]
export const DEFAULT_PAGE_SIZE = 20

/* 契约 §3.6 图片约束 */
export const MAX_IMAGES = 6
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
export const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
export const ALLOWED_IMAGE_EXT_TEXT = 'JPEG / PNG / WebP，单张不超过 5 MiB，最多 6 张'
export const ALT_TEXT_MIN = 5
export const ALT_TEXT_MAX = 100

/* 契约 §3.5 文本长度 */
export const LIMITS = {
  title: { min: 2, max: 60 },
  description: { min: 10, max: 2000 },
  location_detail: { min: 0, max: 100 },
  handover_note: { min: 1, max: 200 },
  resolve_note: { min: 5, max: 200 },
  keyword: { min: 0, max: 50 },
}

export const BEIJING_OFFSET_MINUTES = 480 // UTC+8

/*
 * 失物招领处信息：契约要求前端在 403 IDENTITY_REQUIRED 时给出地址与联系方式，
 * 但契约未定义取该信息的接口。这里先放占位文案，联调时由学校 / A 提供正式内容替换。
 */
export const LOST_AND_FOUND_OFFICE = {
  address: '主校区 学生活动中心一层 102 室',
  phone: '021-0000-0000（待学校确认）',
  hours: '工作日 09:00–17:00',
  note: '非校园用户不能发布招领，请将物品送至失物招领处。',
}

/** 图片内容责任提示（契约 §1：由 B 在发布页提供固定文案） */
export const IMAGE_RESPONSIBILITY_NOTE =
  '请勿在图片中公开完整证件号码、家庭住址、银行卡号等隐私信息；' +
  '图片一旦被他人保存无法收回。是否允许未登录用户查看由你逐张选择。'

export const IMAGE_ALT_TEXT_HINT =
  '每张图必须填写 5～100 字的替代文字，描述图中物品的可辨识特征（颜色、品牌、损坏痕迹、特殊标记等），不要只写“图片”“照片”。'
