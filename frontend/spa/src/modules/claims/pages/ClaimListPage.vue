<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { errorText } from '../../../shared/http.js'
import { datetime } from '../../../shared/utils/datetime.js'
import BasePagination from '../../../shared/components/BasePagination.vue'
import { listClaims } from '../api.js'
import { claimLabels } from '../constants.js'

const route = useRoute(), router = useRouter()
const role = computed(() => route.query.role || 'applicant')
const status = computed(() => route.query.status || '')
const page = computed(() => route.query.page || '1')
const data = ref({ items: [], page: 1, total: 0, total_pages: 0 }), loading = ref(false), error = ref('')
let generation = 0
async function load() {
  const run = ++generation
  loading.value = true
  error.value = ''
  data.value = { items: [], page: 1, total: 0, total_pages: 0 }
  try {
    const result = await listClaims({ role: role.value, status: status.value, page: page.value, post_id: route.query.post_id })
    if (run === generation) data.value = result
  } catch (err) { if (run === generation) { error.value = errorText(err); data.value.items = [] } }
  finally { if (run === generation) loading.value = false }
}
watch(() => route.fullPath, load, { immediate: true })
function filter(value) { router.replace({ query: { ...route.query, role: role.value, status: value || undefined, page: undefined } }) }
function changePage(value) { router.replace({ query: { ...route.query, page: String(value) } }) }
</script>

<template>
  <div class="page-heading"><p class="eyebrow">MY CLAIMS</p><h1>{{ role === 'applicant' ? '我的认领' : '收到的申请' }}</h1><p class="muted">申请、核实和交接进度，都可以在这里查看。</p></div>
  <div class="tabs"><RouterLink to="/me/claims?role=applicant" :class="{ selected: role === 'applicant' }">我申请的</RouterLink><RouterLink to="/me/claims?role=publisher" :class="{ selected: role === 'publisher' }">我收到的</RouterLink></div>
  <div class="toolbar"><label>申请状态 <select :value="status" @change="filter($event.target.value)"><option value="">全部状态</option><option v-for="(label, value) in claimLabels" :key="value" :value="value">{{ label }}</option></select></label><button class="secondary" :disabled="loading" @click="load">刷新列表</button></div>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="loading" role="status" class="muted">正在加载申请…</p>
  <div v-else-if="!data.items.length && !error" class="panel empty">暂时没有符合条件的申请。<RouterLink to="/team">浏览公开信息</RouterLink></div>
  <div class="claim-list">
    <RouterLink v-for="claim in data.items" :key="claim.id" :to="`/claims/${encodeURIComponent(claim.id)}`" class="panel claim-row">
      <div><span class="badge" :data-status="claim.status">{{ claimLabels[claim.status] }}</span><h2>{{ claim.post.title }}</h2><p class="muted">{{ role === 'applicant' ? `发布者：${claim.publisher.nickname}` : `申请者：${claim.applicant.nickname}` }} · {{ datetime(claim.created_at) }}</p></div><span class="row-arrow">查看进度 →</span>
    </RouterLink>
  </div>
  <BasePagination v-if="!error" :page="data.page" :total-pages="data.total_pages" :total="data.total" :disabled="loading" @change="changePage" />
</template>
