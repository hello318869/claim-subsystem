<script setup>
import { onMounted, ref } from 'vue'
import { errorText } from '../../../shared/http.js'
import { datetime } from '../../../shared/utils/datetime.js'
import BasePagination from '../../../shared/components/BasePagination.vue'
import { myPosts } from '../api.js'

const TYPE_LABELS = { lost: '寻物', found: '招领' }
const STATUS_LABELS = { open: '进行中', in_handover: '交接中', completed: '已完成', withdrawn: '已撤回' }

const postType = ref('')
const status = ref('')
const page = ref(1)
const pageSize = 20
const items = ref([])
const total = ref(0)
const totalPages = ref(0)
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await myPosts({
      post_type: postType.value || undefined,
      status: status.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    items.value = result.items
    total.value = result.total
    totalPages.value = result.total_pages
  } catch (err) {
    error.value = errorText(err)
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  load()
}
function changePage(next) {
  page.value = next
  load()
}
onMounted(load)
</script>

<template>
  <RouterLink class="back-link" to="/me/profile">← 返回个人中心</RouterLink>
  <div class="page-heading">
    <p class="eyebrow">MY POSTS</p>
    <h1>我的发布</h1>
    <p class="muted">查看、管理我发布的寻物和招领信息。</p>
  </div>

  <div class="panel filters">
    <label for="my-post-type">类型</label>
    <select id="my-post-type" v-model="postType" :disabled="loading" @change="applyFilters">
      <option value="">全部</option>
      <option value="lost">寻物</option>
      <option value="found">招领</option>
    </select>
    <label for="my-post-status">状态</label>
    <select id="my-post-status" v-model="status" :disabled="loading" @change="applyFilters">
      <option value="">全部状态</option>
      <option value="open">进行中</option>
      <option value="in_handover">交接中</option>
      <option value="completed">已完成</option>
      <option value="withdrawn">已撤回</option>
    </select>
  </div>

  <p v-if="error" class="error" role="alert">{{ error }} <button class="secondary small" @click="load">重试</button></p>
  <p v-if="loading" class="panel">正在加载我发布的信息…</p>
  <p v-else-if="!items.length" class="panel empty">还没有发布记录。</p>

  <section v-else class="my-posts">
    <article v-for="post in items" :key="post.id" class="panel post-row">
      <div class="row-head">
        <span class="tag">{{ TYPE_LABELS[post.post_type] }}</span>
        <span class="badge" :data-status="post.status">{{ STATUS_LABELS[post.status] }}</span>
      </div>
      <h2>{{ post.title }}</h2>
      <p class="muted">{{ post.category.name }} · {{ post.location.name }} · 事件时间 {{ datetime(post.occurred_at) }}</p>
      <p class="muted">发布于 {{ datetime(post.created_at) }}</p>
      <div class="actions">
        <RouterLink class="button secondary" :to="{ name: 'post-detail', params: { id: post.id } }">查看详情</RouterLink>
        <RouterLink
          v-if="post.status === 'open'"
          class="button"
          :to="{ path: `/posts/${encodeURIComponent(post.id)}/matches` }"
        >查看匹配线索</RouterLink>
      </div>
    </article>
  </section>

  <BasePagination
    v-if="!loading && totalPages > 0"
    :page="page"
    :total-pages="totalPages"
    :total="total"
    :disabled="loading"
    @change="changePage"
  />
</template>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; }
.filters label { margin: 0; }
.filters select { width: auto; min-width: 120px; margin: 0; }
.my-posts { display: grid; gap: 14px; }
.post-row { margin: 0; }
.post-row h2 { margin: 6px 0; }
.row-head { display: flex; align-items: center; gap: 10px; }
.actions { margin-top: 10px; }
</style>
