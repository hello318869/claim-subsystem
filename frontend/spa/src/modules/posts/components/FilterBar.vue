<script setup>
import { computed } from 'vue'
import {
  LIMITS,
  SORT_OPTIONS,
  STATUS_FILTER_OPTIONS,
  TYPE_TABS,
} from '../config.js'
import { charLength } from '../utils/format.js'

const props = defineProps({
  categories: { type: Array, default: () => [] },
  campuses: { type: Array, default: () => [] },
  locations: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  total: { type: Number, default: 0 },
})

const filters = defineModel('filters', { type: Object, required: true })
const emit = defineEmits(['search', 'reset'])

const keywordLength = computed(() => charLength(filters.value.keyword || ''))

/** 只显示当前校区下的地点；未选校区时显示全部并标注校区 */
const locationOptions = computed(() => {
  const campusId = filters.value.campus_id
  const list = campusId
    ? props.locations.filter((item) => item.campus_id === campusId)
    : props.locations
  const campusName = (campusIdOfLocation) =>
    props.campuses.find((campus) => campus.id === campusIdOfLocation)?.name || ''
  return list.map((item) => ({
    ...item,
    label: campusId ? item.name : `${item.name}（${campusName(item.campus_id) || '未标注校区'}）`,
  }))
})

function patch(next) {
  filters.value = { ...filters.value, ...next, page: 1 }
  emit('search')
}

function setType(value) {
  if (filters.value.post_type === value) return
  patch({ post_type: value })
}

function setCategory(value) {
  patch({ category_id: value })
}

function setCampus(value) {
  const next = { campus_id: value }
  // 地点必须属于所选校区，否则后端 400；校区变化时清掉不再匹配的地点
  if (value && filters.value.location_id) {
    const current = props.locations.find((item) => item.id === filters.value.location_id)
    if (current && current.campus_id !== value) next.location_id = ''
  }
  if (!value) next.location_id = ''
  patch(next)
}

function setLocation(value) {
  const next = { location_id: value }
  // 选了地点就自动对齐校区，避免提交相互矛盾的 campus_id + location_id
  if (value) {
    const location = props.locations.find((item) => item.id === value)
    if (location?.campus_id) next.campus_id = location.campus_id
  }
  patch(next)
}

function setStatus(value) {
  patch({ status: value })
}

function setSort(value) {
  patch({ sort: value })
}

function setDateRange(which, value) {
  patch({ [which]: value })
}

function onKeywordInput(event) {
  filters.value = { ...filters.value, keyword: event.target.value }
}

function submitKeyword() {
  patch({ keyword: filters.value.keyword.trim() })
}

function clearKeyword() {
  patch({ keyword: '' })
}

function reset() {
  filters.value = {
    post_type: '',
    keyword: '',
    category_id: '',
    campus_id: '',
    location_id: '',
    status: '',
    sort: 'latest',
    occurred_from: '',
    occurred_to: '',
    page: 1,
    page_size: filters.value.page_size,
  }
  emit('reset')
}
</script>

<template>
  <section class="filters" aria-label="信息筛选">
    <div class="filters__types" role="tablist" aria-label="信息类型">
      <button
        v-for="tab in TYPE_TABS"
        :key="tab.value"
        type="button"
        role="tab"
        class="filters__tab"
        :class="{ 'is-active': filters.post_type === tab.value }"
        :aria-selected="filters.post_type === tab.value"
        @click="setType(tab.value)"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="filters__search">
      <label class="visually-hidden" for="keyword">关键词</label>
      <input
        id="keyword"
        :value="filters.keyword"
        class="input"
        type="search"
        :maxlength="LIMITS.keyword.max"
        placeholder="搜索标题或描述中的关键词（最多 50 字）"
        autocomplete="off"
        @input="onKeywordInput"
        @keydown.enter.prevent="submitKeyword"
      />
      <span class="filters__counter">{{ keywordLength }}/{{ LIMITS.keyword.max }}</span>
      <button v-if="filters.keyword" type="button" class="btn btn--ghost btn--sm" @click="clearKeyword">
        清除
      </button>
      <button type="button" class="btn btn--primary" :disabled="loading" @click="submitKeyword">
        搜索
      </button>
    </div>

    <div class="filters__grid">
      <label class="field field--inline">
        <span class="field__label">类别</span>
        <select class="input" :value="filters.category_id" @change="setCategory($event.target.value)">
          <option value="">全部类别</option>
          <option v-for="item in categories" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
      </label>

      <label class="field field--inline">
        <span class="field__label">校区</span>
        <select class="input" :value="filters.campus_id" @change="setCampus($event.target.value)">
          <option value="">全部校区</option>
          <option v-for="item in campuses" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
      </label>

      <label class="field field--inline">
        <span class="field__label">地点</span>
        <select class="input" :value="filters.location_id" @change="setLocation($event.target.value)">
          <option value="">全部地点</option>
          <option v-for="item in locationOptions" :key="item.id" :value="item.id">
            {{ item.label }}
          </option>
        </select>
      </label>

      <label class="field field--inline">
        <span class="field__label">状态</span>
        <select class="input" :value="filters.status" @change="setStatus($event.target.value)">
          <option v-for="item in STATUS_FILTER_OPTIONS" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </select>
      </label>

      <label class="field field--inline">
        <span class="field__label">排序</span>
        <select class="input" :value="filters.sort" @change="setSort($event.target.value)">
          <option v-for="item in SORT_OPTIONS" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </select>
      </label>

      <label class="field field--inline">
        <span class="field__label">发生时间（起）</span>
        <input
          class="input"
          type="date"
          :value="filters.occurred_from"
          @change="setDateRange('occurred_from', $event.target.value)"
        />
      </label>

      <label class="field field--inline">
        <span class="field__label">发生时间（止）</span>
        <input
          class="input"
          type="date"
          :value="filters.occurred_to"
          @change="setDateRange('occurred_to', $event.target.value)"
        />
      </label>

      <div class="filters__actions">
        <button type="button" class="btn btn--ghost" @click="reset">重置筛选</button>
      </div>
    </div>

    <p class="filters__summary">
      共 <strong>{{ total }}</strong> 条结果
      <span class="filters__summary-note">（按北京时间显示，筛选条件可组合，关键词匹配标题或描述）</span>
    </p>
  </section>
</template>

<style scoped>
.filters {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.filters__types {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  background: var(--surface-soft);
  border-radius: 10px;
  align-self: flex-start;
}

.filters__tab {
  border: 0;
  background: transparent;
  padding: 7px 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-soft);
  cursor: pointer;
  font-family: inherit;
}

.filters__tab:hover {
  color: var(--text);
}

.filters__tab.is-active {
  background: var(--surface);
  color: var(--primary-dark);
  box-shadow: 0 1px 2px #0f172a1a;
}

.filters__tab:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 1px;
}

.filters__search {
  display: flex;
  gap: 8px;
  align-items: center;
  position: relative;
}

.filters__search .input {
  flex: 1;
  padding-right: 62px;
}

.filters__counter {
  position: absolute;
  right: 148px;
  font-size: 11.5px;
  color: var(--muted);
  pointer-events: none;
}

.filters__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 10px 14px;
  align-items: end;
}

.filters__actions {
  display: flex;
  justify-content: flex-end;
  align-items: end;
  gap: 8px;
}

.filters__summary {
  margin: 0;
  font-size: 13px;
  color: var(--text-soft);
}

.filters__summary-note {
  color: var(--muted);
}

@media (max-width: 640px) {
  .filters__counter {
    display: none;
  }

  .filters__search {
    flex-wrap: wrap;
  }
}
</style>
