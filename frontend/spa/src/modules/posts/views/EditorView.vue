<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ImageUploader from '../components/ImageUploader.vue'
import NoticeBar from '../components/NoticeBar.vue'
import { ApiError, describeError } from '../api/http.js'
import { createPost, getPost, updatePost } from '../api/posts.js'
import { listCampuses, listCategories, listLocations } from '../api/meta.js'
import { getCurrentUser } from '../api/users.js'
import { hasToken } from '../api/session.js'
import {
  LIMITS,
  LOST_AND_FOUND_OFFICE,
  POST_TYPE_HINT,
  POST_TYPE_TEXT,
  STATUS_TEXT,
} from '../config.js'
import {
  beijingInputToUtc,
  charLength,
  nowBeijingInputValue,
  toBeijingInputValue,
} from '../utils/format.js'
import {
  normalizeFieldErrors,
  validatePostDraft,
} from '../utils/validate.js'

/*
 * 发布 / 编辑（契约 §5.1 POST /posts、PATCH /posts/{id}，字段见 §5.2）。
 * - 图片先 POST /post-images 上传，创建/修改时只提交 image_ids；
 * - 400 的 errors 落到对应输入框；
 * - 提交失败不清空任何已填内容（E2 US-06 的失败恢复验收）。
 */
const route = useRoute()
const router = useRouter()

const isEdit = computed(() => route.name === 'post-edit')
const postId = computed(() => String(route.params.id || ''))
const mode = computed(() => (isEdit.value ? 'edit' : 'create'))

const loading = ref(false)
const loadError = ref(null)
const submitting = ref(false)
const generalError = ref('')
const fieldErrors = ref({})
const identityRequired = ref(false)
const savedNotice = ref('')
const notOwner = ref(false)
const statusLocked = ref(false)

const campuses = ref([])
const categories = ref([])
const locations = ref([])
const metaError = ref('')

const form = reactive({
  post_type: 'lost',
  title: '',
  category_id: '',
  description: '',
  location_id: '',
  location_detail: '',
  occurred_at: nowBeijingInputValue(),
  handover_note: '',
})

const images = ref([])
const initialImageIds = ref([])
const requestId = ref(newRequestId())

const titleLength = computed(() => charLength(form.title))
const descriptionLength = computed(() => charLength(form.description))
const detailLength = computed(() => charLength(form.location_detail))
const handoverLength = computed(() => charLength(form.handover_note))

const err = (field) => fieldErrors.value[field]?.[0] || ''

const locationGroups = computed(() => {
  const groups = new Map()
  for (const location of locations.value) {
    const key = location.campus_id || '__none__'
    if (!groups.has(key)) {
      groups.set(key, {
        campusName: campuses.value.find((campus) => campus.id === key)?.name || '未分类校区',
        items: [],
      })
    }
    groups.get(key).items.push(location)
  }
  return [...groups.values()]
})

const loadedPost = ref(null)
const ownerId = ref('')

const canSubmit = computed(() => {
  if (!hasToken()) return false
  if (submitting.value) return false
  if (isEdit.value && (notOwner.value || statusLocked.value || !loadedPost.value)) return false
  return true
})

const editingStatusText = computed(() => {
  if (!loadedPost.value) return ''
  return STATUS_TEXT[loadedPost.value.status] || loadedPost.value.status
})

function newRequestId() {
  try {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID()
  } catch (e) {
    /* 忽略 */
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
}

async function loadMeta() {
  const [campusResult, categoryResult, locationResult] = await Promise.allSettled([
    listCampuses(),
    listCategories(),
    listLocations(),
  ])
  if (campusResult.status === 'fulfilled') campuses.value = campusResult.value || []
  if (categoryResult.status === 'fulfilled') categories.value = categoryResult.value || []
  if (locationResult.status === 'fulfilled') locations.value = locationResult.value || []
  const failed = [
    campusResult.status === 'rejected' ? '校区' : '',
    categoryResult.status === 'rejected' ? '类别' : '',
    locationResult.status === 'rejected' ? '地点' : '',
  ].filter(Boolean)
  if (failed.length) {
    metaError.value = `字典加载失败（${failed.join('、')}）：类别和地点下拉框可能为空，无法提交。请确认后端 /meta 接口可用。`
  }
}

async function loadPost() {
  if (!isEdit.value || !hasToken()) return
  loading.value = true
  loadError.value = null
  try {
    const post = await getPost(postId.value)
    loadedPost.value = post
    ownerId.value = post.publisher?.id || ''

    const me = await getCurrentUser()
    if (me && ownerId.value && me.id !== ownerId.value) {
      notOwner.value = true
    }

    if (!['open', 'withdrawn'].includes(post.status)) {
      statusLocked.value = true
    }

    form.post_type = post.post_type
    form.title = post.title || ''
    form.category_id = post.category?.id || ''
    form.description = post.description || ''
    form.location_id = post.location?.id || ''
    form.location_detail = post.location_detail || ''
    form.occurred_at = toBeijingInputValue(post.occurred_at)
    form.handover_note = post.handover_note || ''

    images.value = Array.isArray(post.images) ? post.images.map((image) => ({ ...image })) : []
    initialImageIds.value = images.value.map((image) => image.id)
  } catch (error) {
    loadError.value = error
  } finally {
    loading.value = false
  }
}

function sameIds(a, b) {
  if (a.length !== b.length) return false
  return a.every((value, index) => value === b[index])
}

function buildPayload() {
  const payload = {
    title: form.title.trim(),
    category_id: form.category_id,
    description: form.description.trim(),
    location_id: form.location_id,
    location_detail: form.location_detail.trim(),
    occurred_at: beijingInputToUtc(form.occurred_at),
  }
  if (form.post_type === 'found') {
    payload.handover_note = form.handover_note.trim()
  }
  if (mode.value === 'create') {
    payload.post_type = form.post_type
    payload.request_id = requestId.value
  }
  const ids = images.value.map((image) => image.id)
  if (mode.value === 'create') {
    payload.image_ids = ids
  } else if (!sameIds(ids, initialImageIds.value)) {
    // 编辑时 image_ids 缺省表示不改图片；只有真的变了才提交（含排序变化）
    payload.image_ids = ids
  }
  return payload
}

function focusFirstError(errors) {
  const field = Object.keys(errors)[0]
  if (!field) return
  const element = document.querySelector(`[data-field="${field}"]`)
  if (element && typeof element.focus === 'function') {
    element.focus()
    if (typeof element.scrollIntoView === 'function') {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }
}

async function submit() {
  if (!canSubmit.value) return
  generalError.value = ''
  identityRequired.value = false
  savedNotice.value = ''
  fieldErrors.value = {}

  const payload = buildPayload()
  const localErrors = validatePostDraft(
    { ...form, occurred_at: payload.occurred_at, image_ids: payload.image_ids || images.value.map((i) => i.id) },
    { mode: mode.value },
  )
  if (Object.keys(localErrors).length) {
    fieldErrors.value = localErrors
    generalError.value = '请先修正表单中标红的字段。'
    focusFirstError(localErrors)
    return
  }

  submitting.value = true
  try {
    const saved = isEdit.value
      ? await updatePost(postId.value, payload)
      : await createPost(payload)

    if (!isEdit.value) {
      // 成功后换一张 request_id，避免后续再点“发布”复用到同一条信息
      requestId.value = newRequestId()
    }
    savedNotice.value = isEdit.value ? '修改已保存。' : '发布成功。'
    const id = saved?.id || postId.value
    if (id) {
      router.replace({ name: 'post-detail', params: { id } })
    }
  } catch (error) {
    if (error instanceof ApiError && error.hasFieldErrors) {
      const normalized = normalizeFieldErrors(error.errors)
      fieldErrors.value = normalized
      generalError.value = `${describeError(error)}。请检查标红字段。`
      focusFirstError(normalized)
    } else if (error?.code === 'IDENTITY_REQUIRED') {
      identityRequired.value = true
      generalError.value = '发布招领信息需要完成校园身份绑定（演示认证）。'
    } else if (error?.status === 401) {
      generalError.value = '登录已失效：请先在 A 的登录页重新登录，再回到本页；已填写的内容仍保留在页面上。'
    } else if (error?.status === 403) {
      generalError.value = `没有操作权限（${describeError(error)}）。编辑只允许发布者本人操作。`
    } else if (error?.status === 404) {
      generalError.value = '这条信息不存在或已被撤回，无法保存修改。'
    } else if (error?.status === 409) {
      generalError.value = `当前状态不允许保存修改（${describeError(error)}）。`
    } else if (error?.status === 429) {
      generalError.value = '操作过于频繁，请稍后再试。'
    } else {
      generalError.value = describeError(error)
    }
  } finally {
    submitting.value = false
  }
}

function onImageError(message) {
  generalError.value = message
}

function goBack() {
  if (isEdit.value) router.push({ name: 'post-detail', params: { id: postId.value } })
  else router.push({ name: 'post-list' })
}

onMounted(() => {
  if (!hasToken()) return
  loadMeta()
  if (isEdit.value) loadPost()
})
</script>

<template>
  <div class="view view--narrow">
    <nav class="breadcrumb" aria-label="位置">
      <button type="button" class="linklike" @click="goBack">← 返回</button>
      <span aria-hidden="true">/</span>
      <span>{{ isEdit ? '编辑信息' : '发布信息' }}</span>
    </nav>

    <h1 class="page-title">{{ isEdit ? '编辑信息' : '发布失物 / 招领信息' }}</h1>

    <!-- 未登录：只提示，不跳转（登录页归 A） -->
    <section v-if="!hasToken()" class="card login-required" aria-labelledby="login-required-title">
      <h2 id="login-required-title" class="card__title">发布信息需要登录</h2>
      <NoticeBar
        tone="warn"
        message="登录后可以发布、编辑信息和上传图片。"
      />
      <div class="login-required__actions">
        <RouterLink class="btn btn--primary btn--sm" :to="{ path: '/login', query: { next: route.fullPath } }">去登录</RouterLink>
      </div>
    </section>

    <template v-else>
      <NoticeBar
        v-if="metaError"
        tone="warn"
        title="字典数据未就绪"
        :message="metaError"
        hint="类别与地点必须来自 GET /meta/categories、GET /meta/locations，前端不会自己造字典 ID。"
      />

      <NoticeBar
        v-if="identityRequired"
        tone="warn"
        title="非校园用户不能发布招领"
        :message="LOST_AND_FOUND_OFFICE.note"
        :details="[
          `失物招领处地址：${LOST_AND_FOUND_OFFICE.address}`,
          `联系电话：${LOST_AND_FOUND_OFFICE.phone}`,
          `服务时间：${LOST_AND_FOUND_OFFICE.hours}`,
        ]"
        hint="失物招领信息（post_type=lost）只需登录即可发布；需要发布招领时请先完成校园身份绑定（演示认证）。"
      />

      <div v-if="loading" class="editor-loading" aria-busy="true">正在读取信息…</div>

      <NoticeBar
        v-else-if="loadError"
        tone="error"
        title="无法加载要编辑的信息"
        :message="describeError(loadError)"
        :hint="loadError.status === 404 ? '这条信息可能已被撤回，或你不是发布者。' : ''"
      />

      <NoticeBar
        v-else-if="notOwner"
        tone="error"
        title="只能编辑自己发布的信息"
        message="当前登录用户不是这条信息的发布者；编辑接口会返回 403。"
      />

      <NoticeBar
        v-else-if="statusLocked"
        tone="warn"
        title="当前状态不允许编辑"
        :message="`这条信息现在是「${editingStatusText}」。只有“进行中（open）”和“已撤回（withdrawn）”的信息可以编辑。`"
        hint="交接中（in_handover）和已完成（completed）由认领业务流程控制。"
      />

      <template v-if="!loading && !loadError">
        <form class="editor" novalidate @submit.prevent="submit">
          <NoticeBar
            v-if="generalError"
            tone="error"
            title="提交失败，已填写的内容仍保留"
            :message="generalError"
            :hint="'修正后可直接重新提交；图片已上传成功的不会丢失。'"
          />

          <section class="card">
            <h2 class="card__title">基本信息</h2>

            <fieldset class="field-group">
              <legend class="field__label">信息类型（创建后不可修改）</legend>
              <div v-if="isEdit" class="type-readonly">
                <span class="type-chip" :class="`type-chip--${form.post_type}`">
                  {{ POST_TYPE_TEXT[form.post_type] || form.post_type }}
                </span>
                <span class="field__hint">编辑时不能修改类型；需要换类型请撤回后重新发布。</span>
              </div>
              <div v-else class="type-options">
                <label
                  v-for="value in ['lost', 'found']"
                  :key="value"
                  class="type-option"
                  :class="{ 'is-active': form.post_type === value }"
                >
                  <input
                    v-model="form.post_type"
                    type="radio"
                    name="post_type"
                    :value="value"
                    data-field="post_type"
                  />
                  <span class="type-option__body">
                    <strong>{{ POST_TYPE_TEXT[value] }}</strong>
                    <small>{{ POST_TYPE_HINT[value] }}</small>
                  </span>
                </label>
              </div>
              <p v-if="err('post_type')" class="field__error">{{ err('post_type') }}</p>
            </fieldset>

            <label class="field">
              <span class="field__label">
                标题（必填，{{ LIMITS.title.min }}～{{ LIMITS.title.max }} 字）
              </span>
              <input
                v-model="form.title"
                class="input"
                type="text"
                :maxlength="LIMITS.title.max"
                data-field="title"
                :aria-invalid="!!err('title')"
                placeholder="例如：图书馆二楼拾到一串钥匙"
              />
              <span class="field__counter" :class="{ 'is-over': titleLength > LIMITS.title.max }">
                {{ titleLength }} / {{ LIMITS.title.max }}
              </span>
              <p v-if="err('title')" class="field__error">{{ err('title') }}</p>
            </label>

            <div class="field-row">
              <label class="field">
                <span class="field__label">物品类别（必填）</span>
                <select
                  v-model="form.category_id"
                  class="input"
                  data-field="category_id"
                  :aria-invalid="!!err('category_id')"
                >
                  <option value="">请选择类别</option>
                  <option v-for="item in categories" :key="item.id" :value="item.id">
                    {{ item.name }}
                  </option>
                </select>
                <p v-if="err('category_id')" class="field__error">{{ err('category_id') }}</p>
              </label>

              <label class="field">
                <span class="field__label">发生地点（必填，校区由地点自动推导）</span>
                <select
                  v-model="form.location_id"
                  class="input"
                  data-field="location_id"
                  :aria-invalid="!!err('location_id')"
                >
                  <option value="">请选择地点</option>
                  <optgroup
                    v-for="group in locationGroups"
                    :key="group.campusName"
                    :label="group.campusName"
                  >
                    <option v-for="item in group.items" :key="item.id" :value="item.id">
                      {{ item.name }}
                    </option>
                  </optgroup>
                </select>
                <p v-if="err('location_id')" class="field__error">{{ err('location_id') }}</p>
              </label>
            </div>

            <label class="field">
              <span class="field__label">
                详细地点（选填，{{ LIMITS.location_detail.max }} 字以内，公开显示）
              </span>
              <input
                v-model="form.location_detail"
                class="input"
                type="text"
                :maxlength="LIMITS.location_detail.max"
                data-field="location_detail"
                :aria-invalid="!!err('location_detail')"
                placeholder="例如：二楼公共座位附近"
              />
              <span class="field__counter">{{ detailLength }} / {{ LIMITS.location_detail.max }}</span>
              <p v-if="err('location_detail')" class="field__error">{{ err('location_detail') }}</p>
            </label>

            <label class="field">
              <span class="field__label">
                {{ form.post_type === 'found' ? '拾获时间' : '丢失时间' }}（必填，不能晚于当前，按北京时间填写）
              </span>
              <input
                v-model="form.occurred_at"
                class="input input--datetime"
                type="datetime-local"
                data-field="occurred_at"
                :aria-invalid="!!err('occurred_at')"
              />
              <p v-if="err('occurred_at')" class="field__error">{{ err('occurred_at') }}</p>
            </label>

            <label class="field">
              <span class="field__label">
                描述（必填，{{ LIMITS.description.min }}～{{ LIMITS.description.max }} 字，写清物品特征和事件经过）
              </span>
              <textarea
                v-model="form.description"
                class="input"
                rows="6"
                :maxlength="LIMITS.description.max"
                data-field="description"
                :aria-invalid="!!err('description')"
                placeholder="例如：在图书馆二楼公共座位附近拾到一串钥匙，共四把，其中一把带蓝色硅胶钥匙套。请失主说明具体特征。"
              ></textarea>
              <span class="field__counter">{{ descriptionLength }} / {{ LIMITS.description.max }}</span>
              <p v-if="err('description')" class="field__error">{{ err('description') }}</p>
            </label>

            <label v-if="form.post_type === 'found'" class="field">
              <span class="field__label">
                保管 / 交接说明（招领必填，{{ LIMITS.handover_note.min }}～{{ LIMITS.handover_note.max }} 字）
              </span>
              <textarea
                v-model="form.handover_note"
                class="input"
                rows="3"
                :maxlength="LIMITS.handover_note.max"
                data-field="handover_note"
                :aria-invalid="!!err('handover_note')"
                placeholder="例如：暂由本人保管，核实特征后在校内约定地点交接。"
              ></textarea>
              <span class="field__counter">{{ handoverLength }} / {{ LIMITS.handover_note.max }}</span>
              <p v-if="err('handover_note')" class="field__error">{{ err('handover_note') }}</p>
            </label>
          </section>

          <section class="card">
            <ImageUploader
              v-model="images"
              :disabled="!canSubmit"
              @error="onImageError"
            />
            <p v-if="err('image_ids')" class="field__error">{{ err('image_ids') }}</p>
          </section>

          <section class="card submit-bar">
            <div class="submit-bar__info">
              <p class="submit-bar__hint">
                {{ isEdit ? '修改只提交允许编辑的字段；图片顺序即 image_ids 顺序。' : '发布后状态为“进行中（open）”。' }}
              </p>
              <p v-if="savedNotice" class="submit-bar__saved" role="status">{{ savedNotice }}</p>
            </div>
            <div class="submit-bar__actions">
              <button type="button" class="btn btn--ghost" :disabled="submitting" @click="goBack">
                取消
              </button>
              <button type="submit" class="btn btn--primary" :disabled="!canSubmit">
                {{ submitting ? '提交中…' : isEdit ? '保存修改' : '发布信息' }}
              </button>
            </div>
          </section>
        </form>
      </template>
    </template>
  </div>
</template>

<style scoped>
.view--narrow {
  max-width: 860px;
  margin: 0 auto;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--muted);
}

.linklike {
  border: 0;
  background: none;
  padding: 0;
  font: inherit;
  color: var(--primary-dark);
  cursor: pointer;
}

.linklike:hover {
  text-decoration: underline;
}

.editor {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field-group {
  border: 0;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-group legend {
  padding: 0;
  margin-bottom: 6px;
}

.type-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px;
}

.type-option {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  cursor: pointer;
  background: var(--surface);
}

.type-option.is-active {
  border-color: var(--primary);
  background: var(--primary-soft);
  box-shadow: 0 0 0 1px var(--primary) inset;
}

.type-option input {
  margin-top: 3px;
}

.type-option__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.type-option__body small {
  color: var(--muted);
  font-size: 12px;
}

.type-readonly {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.type-chip {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid var(--line);
}

.type-chip--lost {
  color: #b91c1c;
  border-color: #f3c6c6;
  background: #fff5f5;
}

.type-chip--found {
  color: #065f46;
  border-color: #bfe7d8;
  background: #f2fbf7;
}

.field-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.login-required {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.login-required__actions {
  display: flex;
  gap: 8px;
}

.editor-loading {
  padding: 32px;
  text-align: center;
  color: var(--muted);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.submit-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  position: sticky;
  bottom: 12px;
  box-shadow: 0 8px 24px #0f172a14;
}

.submit-bar__info {
  min-width: 0;
}

.submit-bar__hint {
  margin: 0;
  font-size: 12.5px;
  color: var(--muted);
}

.submit-bar__saved {
  margin: 4px 0 0;
  font-size: 13px;
  color: #0f766e;
}

.submit-bar__actions {
  display: flex;
  gap: 8px;
  flex: none;
}
</style>
