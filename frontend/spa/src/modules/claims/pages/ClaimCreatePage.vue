<script setup>
import { computed, onScopeDispose, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { session } from '../../../shared/session.js'
import { errorText } from '../../../shared/http.js'
import { datetime } from '../../../shared/utils/datetime.js'
import { getPost, createClaim } from '../api.js'
import ClaimForm from '../components/ClaimForm.vue'
import { handoverHint, postLabels } from '../constants.js'

const route = useRoute(), router = useRouter()
const post = ref(null), loading = ref(false), busy = ref(false), error = ref(''), uncertain = ref(false)
let generation = 0
onScopeDispose(() => generation++)
watch(() => route.query.post_id, async postId => {
  const run = ++generation
  post.value = null
  error.value = ''
  uncertain.value = false
  if (!postId || typeof postId !== 'string') { error.value = '请先选择要认领的失物或招领信息'; return }
  loading.value = true
  try { const result = await getPost(postId); if (run === generation) post.value = result } catch (err) {
    if (run === generation) error.value = errorText(err)
  } finally { if (run === generation) loading.value = false }
}, { immediate: true })
const blocked = computed(() => {
  if (!post.value) return ''
  if (post.value.publisher.id === session.user?.id) return '你不能认领自己发布的物品。'
  if (!session.user?.is_campus_verified) return '请先完成校园身份绑定，再提交认领申请。'
  if (post.value.status !== 'open') return '该物品当前不接受新的认领申请。'
  return ''
})
const needsVerification = computed(() => Boolean(session.user) && !session.user.is_campus_verified)
const bindingTarget = computed(() => ({ path: '/me/campus-binding', query: { next: route.fullPath } }))
async function submit(verification_text) {
  if (!post.value || busy.value || blocked.value || uncertain.value) return
  busy.value = true
  error.value = ''
  const run = generation
  try {
    const claim = await createClaim({ post_id: post.value.id, verification_text })
    if (run === generation) await router.push(`/claims/${encodeURIComponent(claim.id)}`)
  } catch (err) {
    if (run !== generation) return
    error.value = errorText(err)
    uncertain.value = err.status === 0 || err.status >= 500 || err.code === 'INVALID_RESPONSE'
  } finally { if (run === generation) busy.value = false }
}
</script>

<template>
  <RouterLink class="back-link" to="/team">← 返回公开信息</RouterLink>
  <div class="page-heading"><p class="eyebrow">CLAIM APPLICATION</p><h1>申请认领</h1><p class="muted">向信息发布者提供物品细节，核实后再安排交接。</p></div>
  <p v-if="loading" class="panel">正在读取物品…</p>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <template v-if="post">
    <article class="panel source-card"><span class="badge">{{ postLabels[post.status] }}</span><h2>{{ post.title }}</h2><p>{{ post.description }}</p><p class="muted">{{ post.location.name }} · {{ datetime(post.occurred_at) }} · {{ post.publisher.nickname }}</p><p v-if="post.handover_note">交接说明：{{ post.handover_note }}</p></article>
    <p v-if="post.post_type === 'lost' && post.publisher.is_campus_verified === false" class="notice">{{ handoverHint }}</p>
    <div v-if="blocked" class="notice">
      <p>{{ blocked }}</p>
      <RouterLink v-if="needsVerification" class="button" :to="bindingTarget">去完成校园身份认证</RouterLink>
    </div>
    <p v-else-if="uncertain" class="notice">提交结果未确认，请先在 <RouterLink to="/me/claims?role=applicant">我的认领</RouterLink> 中检查是否已生成申请。</p>
    <section v-else class="panel"><ClaimForm :busy="busy" @submit="submit" /></section>
  </template>
</template>
