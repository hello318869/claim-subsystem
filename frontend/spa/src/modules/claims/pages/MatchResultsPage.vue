<script setup>
import { onScopeDispose, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { errorText } from '../../../shared/http.js'
import { datetime } from '../../../shared/utils/datetime.js'
import { getMatches, getPost } from '../api.js'
import { reasonLabels } from '../constants.js'
const route = useRoute()
const source = ref(null), items = ref([]), loading = ref(false), error = ref('')
let generation = 0
onScopeDispose(() => generation++)
async function load() {
  const run = ++generation
  loading.value = true
  error.value = ''
  source.value = null
  items.value = []
  try {
    const [post, matches] = await Promise.all([getPost(route.params.id), getMatches(route.params.id)])
    if (run === generation) { source.value = post; items.value = matches.items }
  } catch (err) { if (run === generation) error.value = errorText(err) }
  finally { if (run === generation) loading.value = false }
}
watch(() => route.params.id, load, { immediate: true })
</script>

<template>
  <RouterLink class="back-link" to="/me/posts">← 返回我的发布</RouterLink>
  <div class="page-heading"><p class="eyebrow">MATCHING LEADS</p><h1>查找匹配线索</h1><p class="muted">同校区、同类别、相反类型，拾获时间在丢失之后 30 天内。</p></div>
  <p class="notice">分数是规则分，表示类别、地点、时间和标题的相似程度，不是失主身份概率。请通过私有认领证明人工核实。</p>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="loading" class="panel">正在计算匹配…</p>
  <template v-else-if="source">
    <div class="section-heading"><h2>来自「{{ source.title }}」的线索</h2><button class="secondary" @click="load">重新匹配</button></div>
    <p v-if="!items.length" class="panel empty">暂时没有符合规则的线索，可以稍后再试或通过信息浏览查找。</p>
    <div class="match-grid">
      <article v-for="item in items" :key="item.post.id" class="panel match-card">
        <div class="section-heading"><span class="tag">{{ item.post.post_type === 'found' ? '招领信息' : '寻物信息' }}</span><span class="score">{{ item.score }}<small>规则分</small></span></div>
        <h2>{{ item.post.title }}</h2><p class="muted">{{ item.post.category.name }} · {{ item.post.location.name }}<br>{{ datetime(item.post.occurred_at) }} · {{ item.post.publisher.nickname }}</p>
        <div class="reason-list"><span v-for="reason in item.reasons" :key="reason">{{ reasonLabels[reason] }}</span></div>
        <RouterLink class="button" :to="{ path: '/claims/new', query: { post_id: item.post.id } }">核实并申请认领</RouterLink>
      </article>
    </div>
  </template>
</template>
