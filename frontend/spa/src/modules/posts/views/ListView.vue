<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FilterBar from '../components/FilterBar.vue'
import NoticeBar from '../components/NoticeBar.vue'
import PaginationBar from '../components/PaginationBar.vue'
import PostCard from '../components/PostCard.vue'
import { describeError } from '../api/http.js'
import { listPosts } from '../api/posts.js'
import { listCampuses, listCategories, listLocations } from '../api/meta.js'
import { DEFAULT_PAGE_SIZE } from '../config.js'
import { hasToken } from '../api/session.js'
import {
  dateInputToUtcEnd,
  dateInputToUtcStart,
} from '../utils/format.js'

/*
 * 公开列表（契约 §5.3 GET /posts）。
 * 未登录可访问；带无效令牌时 http 层会清令牌并匿名重试一次。
 * 筛选条件同步到 URL query，从详情返回列表时保留条件（E3 US-12 的“筛选条件回显”）。
 */
const route = useRoute()
const router = useRouter()

const VALID_SORT = ['latest', 'occurred_latest']
const VALID_TYPE = ['', 'lost', 'found']
const VALID_STATUS = ['', 'open', 'in_handover', 'completed']
const VALID_PAGE_SIZES = [10, 20, 50]

function firstQueryValue(value) {
  if (Array.isArray(value)) return value.length ? String(value[0]) : ''
  return value === undefined || value === null ? '' : String(value)
}

function numberQueryValue(value, fallback) {
  const parsed = Number(firstQueryValue(value))
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : fallback
}

function buildInitialFilters() {
  const query = route.query || {}
  const sort = firstQueryValue(query.sort)
  const type = firstQueryValue(query.post_type)
  const status = firstQueryValue(query.status)
  const pageSize = numberQueryValue(query.page_size, DEFAULT_PAGE_SIZE)
  const dateOnly = (value) => {
    const text = firstQueryValue(value)
    return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : ''
  }
  return {
    post_type: VALID_TYPE.includes(type) ? type : '',
    keyword: firstQueryValue(query.keyword).slice(0, 50),
    category_id: firstQueryValue(query.category_id),
    campus_id: firstQueryValue(query.campus_id),
    location_id: firstQueryValue(query.location_id),
    status: VALID_STATUS.includes(status) ? status : '',
    sort: VALID_SORT.includes(sort) ? sort : 'latest',
    occurred_from: dateOnly(query.occurred_from),
    occurred_to: dateOnly(query.occurred_to),
    page: numberQueryValue(query.page, 1),
    page_size: VALID_PAGE_SIZES.includes(pageSize) ? pageSize : DEFAULT_PAGE_SIZE,
  }
}

const filters = ref(buildInitialFilters())

const items = ref([])
const total = ref(0)
const totalPages = ref(0)
const loading = ref(false)
const error = ref(null)
const metaError = ref('')
const hasLoaded = ref(false)
const pageOutOfRange = ref(false)

const campuses = ref([])
const categories = ref([])
const locations = ref([])

let loadSeq = 0
let controller = null

const activeFilterCount = computed(() => {
  const keys = ['category_id', 'campus_id', 'location_id', 'status', 'occurred_from', 'occurred_to']
  return keys.filter((key) => filters.value[key]).length + (filters.value.keyword ? 1 : 0)
})

const hasAnyFilter = computed(
  () => activeFilterCount.value > 0 || !!filters.value.post_type || filters.value.sort !== 'latest',
)

const apiQuery = computed(() => ({
  post_type: filters.value.post_type,
  keyword: filters.value.keyword.trim(),
  category_id: filters.value.category_id,
  campus_id: filters.value.campus_id,
  location_id: filters.value.location_id,
  status: filters.value.status,
  sort: filters.value.sort,
  occurred_from: dateInputToUtcStart(filters.value.occurred_from),
  occurred_to: dateInputToUtcEnd(filters.value.occurred_to),
  page: filters.value.page,
  page_size: filters.value.page_size,
}))

const emptyMessage = computed(() => {
  if (hasAnyFilter.value) {
    return '没有符合当前条件的信息。可以试着清空关键词、换一个类别，或把状态改为“已完成”。'
  }
  return '目前还没有公开的失物 / 招领信息。'
})

function syncUrl() {
  const query = {}
  for (const [key, value] of Object.entries(filters.value)) {
    if (value === '' || value === undefined || value === null) continue
    if (key === 'sort' && value === 'latest') continue
    if (key === 'page' && Number(value) === 1) continue
    if (key === 'page_size' && Number(value) === DEFAULT_PAGE_SIZE) continue
    query[key] = String(value)
  }
  router.replace({ name: 'post-list', query }).catch(() => {})
}

async function load() {
  if (
    filters.value.occurred_from &&
    filters.value.occurred_to &&
    filters.value.occurred_from > filters.value.occurred_to
  ) {
    error.value = {
      status: 400,
      code: 'VALIDATION_ERROR',
      message: '发生时间的起始日期不能晚于结束日期',
      errors: {},
    }
    items.value = []
    total.value = 0
    totalPages.value = 0
    return
  }

  const seq = ++loadSeq
  if (controller) controller.abort()
  controller = new AbortController()

  loading.value = true
  error.value = null
  pageOutOfRange.value = false

  try {
    const data = await listPosts(apiQuery.value, { signal: controller.signal })
    if (seq !== loadSeq) return
    items.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total) || 0
    totalPages.value = Number(data?.total_pages) || 0
    // 契约 2.5：页码超过最后一页返回空列表而不是 404
    pageOutOfRange.value = !items.value.length && total.value > 0 && filters.value.page > 1
  } catch (err) {
    if (err?.name === 'AbortError' || seq !== loadSeq) return
    error.value = err
    items.value = []
    total.value = 0
    totalPages.value = 0
  } finally {
    if (seq === loadSeq) {
      loading.value = false
      hasLoaded.value = true
    }
  }
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
    metaError.value = `字典加载失败（${failed.join('、')}），筛选下拉框可能为空；列表浏览不受影响。`
  }
}

async function onSearch() {
  filters.value.page = 1
  syncUrl()
  await load()
  scrollToListTop()
}

async function onReset() {
  filters.value.page = 1
  syncUrl()
  await load()
  scrollToListTop()
}

async function onPageChange(page) {
  filters.value.page = page
  syncUrl()
  await load()
  scrollToListTop()
}

async function onPageSizeChange(size) {
  filters.value.page_size = size
  filters.value.page = 1
  syncUrl()
  await load()
}

function scrollToListTop() {
  const anchor = document.getElementById('list-top')
  if (anchor && typeof anchor.scrollIntoView === 'function') {
    anchor.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

onMounted(() => {
  loadMeta()
  load()
})
</script>

<template>
  <div class="view">
    <section id="list-top" class="page-head">
      <div>
        <h1 class="page-title">失物与招领</h1>
        <p class="page-subtitle">
          未登录也可以浏览公开信息；<template v-if="!hasToken()"
            >未登录时，发布者设为“仅登录可见”的图片会显示替代文字，不加载原图。</template
          ><template v-else>你已登录，可查看“仅登录可见”的图片。</template>
        </p>
      </div>
      <RouterLink class="btn btn--primary" :to="{ name: 'post-new' }">发布失物 / 招领</RouterLink>
    </section>

    <FilterBar
      v-model:filters="filters"
      :categories="categories"
      :campuses="campuses"
      :locations="locations"
      :loading="loading"
      :total="total"
      @search="onSearch"
      @reset="onReset"
    />

    <NoticeBar
      v-if="metaError"
      tone="warn"
      title="字典数据未就绪"
      :message="metaError"
      hint="字典接口（/meta/campuses、/meta/categories、/meta/locations）由 B 后端提供，标注为固定初始化数据。"
    />

    <NoticeBar
      v-if="error"
      tone="error"
      title="加载列表失败"
      :message="describeError(error)"
      :hint="
        error.status === 0
          ? '请确认后端服务和同源接口已启动。'
          : error.status === 400
            ? '查询参数不合法时会返回 400，可重置筛选后重试。'
            : ''
      "
    >
      <template #actions>
        <button type="button" class="btn btn--ghost btn--sm" @click="load">重试</button>
      </template>
    </NoticeBar>

    <div v-if="loading" class="grid" aria-busy="true" aria-live="polite">
      <div v-for="index in 6" :key="index" class="skeleton-card">
        <div class="skeleton-card__media"></div>
        <div class="skeleton-card__line"></div>
        <div class="skeleton-card__line skeleton-card__line--short"></div>
      </div>
    </div>

    <template v-else-if="!error">
      <ul v-if="items.length" class="grid" aria-label="信息列表">
        <li v-for="post in items" :key="post.id" class="grid__item">
          <PostCard :post="post" />
        </li>
      </ul>

      <div v-else class="empty" role="status">
        <p class="empty__title">没有找到信息</p>
        <p class="empty__text">{{ emptyMessage }}</p>
        <p v-if="pageOutOfRange" class="empty__text">
          当前页码超出现有结果范围（共 {{ totalPages }} 页），已显示空页；可以返回第一页。
        </p>
        <div class="empty__actions">
          <button
            v-if="pageOutOfRange"
            type="button"
            class="btn btn--primary btn--sm"
            @click="onPageChange(1)"
          >
            回到第一页
          </button>
          <RouterLink v-else class="btn btn--primary btn--sm" :to="{ name: 'post-new' }">
            发布一条信息
          </RouterLink>
        </div>
      </div>
    </template>

    <PaginationBar
      v-if="hasLoaded && total > 0 && !error"
      :page="filters.page"
      :page-size="filters.page_size"
      :total="total"
      :total-pages="totalPages"
      @update:page="onPageChange"
      @update:page-size="onPageSizeChange"
    />

    <p class="view__footnote">
      列表只展示公开可见的信息；状态为“已完成”的信息需要把状态筛选改为“已完成”才会出现，“已撤回”的信息不会出现在公开列表。
    </p>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.page-subtitle {
  margin: 6px 0 0;
  font-size: 13.5px;
  color: var(--text-soft);
  max-width: 62ch;
  line-height: 1.65;
}

.grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(255px, 1fr));
  gap: 16px;
}

.grid__item {
  min-width: 0;
}

.skeleton-card {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  overflow: hidden;
  padding-bottom: 16px;
}

.skeleton-card__media {
  aspect-ratio: 4 / 3;
  background: linear-gradient(100deg, #eef1f7 30%, #f7f9fc 50%, #eef1f7 70%);
  background-size: 300% 100%;
  animation: skeleton 1.4s infinite linear;
}

.skeleton-card__line {
  height: 12px;
  margin: 12px 14px 0;
  border-radius: 6px;
  background: #eef1f7;
}

.skeleton-card__line--short {
  width: 55%;
}

@keyframes skeleton {
  from {
    background-position: 150% 0;
  }
  to {
    background-position: -150% 0;
  }
}

.empty {
  padding: 42px 20px;
  text-align: center;
  background: var(--surface);
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
}

.empty__title {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
}

.empty__text {
  margin: 8px auto 0;
  max-width: 52ch;
  font-size: 13.5px;
  color: var(--text-soft);
  line-height: 1.7;
}

.empty__actions {
  margin-top: 14px;
}

.view__footnote {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.7;
}
</style>
