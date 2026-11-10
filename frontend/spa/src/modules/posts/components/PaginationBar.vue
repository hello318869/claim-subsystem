<script setup>
import { computed } from 'vue'
import { PAGE_SIZE_OPTIONS } from '../config.js'

const props = defineProps({
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, default: 0 },
  totalPages: { type: Number, default: 0 },
})

const emit = defineEmits(['update:page', 'update:pageSize'])

const items = computed(() => {
  const total = props.totalPages
  const current = Math.min(Math.max(props.page, 1), Math.max(total, 1))
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => ({ type: 'page', value: index + 1 }))
  }
  const numbers = new Set([1, total, current - 1, current, current + 1])
  if (current <= 3) [2, 3, 4].forEach((n) => numbers.add(n))
  if (current >= total - 2) [total - 3, total - 2, total - 1].forEach((n) => numbers.add(n))
  const sorted = [...numbers].filter((n) => n >= 1 && n <= total).sort((a, b) => a - b)
  const result = []
  let previous = 0
  for (const value of sorted) {
    if (previous && value - previous > 1) result.push({ type: 'gap', key: `gap-${previous}` })
    result.push({ type: 'page', value })
    previous = value
  }
  return result
})

const canPrev = computed(() => props.page > 1)
const canNext = computed(() => props.page < props.totalPages)

function go(target) {
  const value = Math.min(Math.max(target, 1), Math.max(props.totalPages, 1))
  if (value === props.page) return
  emit('update:page', value)
}

function changeSize(event) {
  const value = Number(event.target.value)
  if (!Number.isFinite(value) || value <= 0) return
  emit('update:pageSize', value)
}
</script>

<template>
  <nav class="pagination" aria-label="分页">
    <p class="pagination__info">
      第 <strong>{{ totalPages ? page : 0 }}</strong> / {{ totalPages }} 页 · 共
      <strong>{{ total }}</strong> 条
    </p>

    <div class="pagination__controls">
      <button type="button" class="btn btn--ghost btn--sm" :disabled="!canPrev" @click="go(1)">
        首页
      </button>
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        :disabled="!canPrev"
        @click="go(page - 1)"
      >
        上一页
      </button>

      <template v-for="item in items" :key="item.type === 'gap' ? item.key : item.value">
        <span v-if="item.type === 'gap'" class="pagination__gap" aria-hidden="true">…</span>
        <button
          v-else
          type="button"
          class="pagination__page"
          :class="{ 'is-current': item.value === page }"
          :aria-current="item.value === page ? 'page' : undefined"
          :aria-label="`第 ${item.value} 页`"
          @click="go(item.value)"
        >
          {{ item.value }}
        </button>
      </template>

      <button
        type="button"
        class="btn btn--ghost btn--sm"
        :disabled="!canNext"
        @click="go(page + 1)"
      >
        下一页
      </button>
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        :disabled="!canNext"
        @click="go(totalPages)"
      >
        末页
      </button>

      <label class="pagination__size">
        <span class="visually-hidden">每页条数</span>
        <select class="input input--sm" :value="pageSize" @change="changeSize">
          <option v-for="size in PAGE_SIZE_OPTIONS" :key="size" :value="size">
            每页 {{ size }} 条
          </option>
        </select>
      </label>
    </div>
  </nav>
</template>

<style scoped>
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.pagination__info {
  margin: 0;
  font-size: 13px;
  color: var(--text-soft);
}

.pagination__controls {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.pagination__page {
  min-width: 32px;
  height: 32px;
  padding: 0 8px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-soft);
  font-family: inherit;
  font-size: 13.5px;
  cursor: pointer;
}

.pagination__page:hover {
  background: var(--surface-soft);
  color: var(--text);
}

.pagination__page.is-current {
  background: var(--primary);
  color: #fff;
  font-weight: 650;
}

.pagination__gap {
  color: var(--muted);
  padding: 0 2px;
}

.pagination__size {
  margin-left: 8px;
}
</style>
