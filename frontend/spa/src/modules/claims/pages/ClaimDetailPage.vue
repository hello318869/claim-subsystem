<script setup>
import { computed, ref, watch, onScopeDispose } from 'vue'
import { useRoute } from 'vue-router'
import { session } from '../../../shared/session.js'
import { errorText } from '../../../shared/http.js'
import { datetime } from '../../../shared/utils/datetime.js'
import { getClaim, actOnClaim } from '../api.js'
import { claimLabels, postLabels, closeLabels, availableActions, handoverHint } from '../constants.js'
import ClaimStatusSteps from '../components/ClaimStatusSteps.vue'
import ClaimChat from '../components/ClaimChat.vue'

const route = useRoute()
const claim = ref(null), loading = ref(false), busy = ref(false), error = ref(''), pendingAction = ref(''), note = ref('')
let generation = 0, loadRevision = 0
onScopeDispose(() => generation++)
async function load() {
  if (busy.value) return
  const run = generation
  const reading = ++loadRevision
  try {
    const result = await getClaim(route.params.id)
    if (run === generation && reading === loadRevision) claim.value = result
  } catch (err) {
    if (run !== generation || reading !== loadRevision) return
    if (err.status === 404 || err.status === 403) claim.value = null
    error.value = errorText(err)
  }
}
watch(() => route.params.id, async () => {
  generation++
  const run = generation
  claim.value = null
  busy.value = false
  pendingAction.value = ''
  error.value = ''
  loading.value = true
  await load()
  if (run === generation) loading.value = false
}, { immediate: true })
const actions = computed(() => availableActions(claim.value, session.user?.id))
const isApplicant = computed(() => claim.value?.applicant_id === session.user?.id)
const showHandoverHint = computed(() => isApplicant.value && claim.value?.post?.post_type === 'lost' && claim.value?.publisher?.is_campus_verified === false)
const actionLabels = { accept: '同意认领', reject: '拒绝申请', cancel: '取消申请', 'confirm-handover': '确认交接' }
const submitLabels = { accept: '确认同意', reject: '确认拒绝', cancel: '确认取消', 'confirm-handover': '我已完成交接' }
function choose(action) { pendingAction.value = action; note.value = ''; error.value = '' }
async function act() {
  const action = pendingAction.value
  if (busy.value || !actions.value.includes(action)) return
  const decision = note.value.trim()
  const reviewing = action === 'accept' || action === 'reject'
  if ((action === 'reject' && !decision) || (reviewing && Array.from(decision).length > 500)) return
  busy.value = true
  loadRevision++
  error.value = ''
  const run = generation
  let refresh = false
  try {
    const body = reviewing && decision ? { decision_note: decision } : undefined
    const result = await actOnClaim(claim.value.id, action, body)
    if (run === generation) { claim.value = result; pendingAction.value = '' }
  } catch (err) {
    if (run === generation) {
      if (err.status === 404 || err.status === 403) claim.value = null
      refresh = err.status === 409
      error.value = errorText(err)
      pendingAction.value = ''
    }
  } finally { if (run === generation) busy.value = false }
  if (refresh && run === generation) await load()
}
</script>

<template>
  <RouterLink class="back-link" :to="`/me/claims?role=${claim?.publisher.id === session.user?.id ? 'publisher' : 'applicant'}`">← 返回申请列表</RouterLink>
  <p v-if="loading" class="panel">正在加载申请…</p>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <template v-if="claim">
    <div class="page-heading detail-heading"><div><p class="eyebrow">认领进度</p><h1>{{ claim.post.title }}</h1><p class="muted">{{ isApplicant ? '我发起的' : '我收到的' }}</p></div><span class="badge large" :data-status="claim.status">{{ claimLabels[claim.status] }}</span></div>
    <p v-if="showHandoverHint" class="notice">{{ handoverHint }}</p>
    <ClaimStatusSteps :claim="claim" />
    <div class="detail-grid">
      <div>
        <section class="panel"><h2>认领证明 <span class="private-label">仅双方可见</span></h2><p class="preserve">{{ claim.verification_text }}</p><p class="muted">提交于 {{ datetime(claim.created_at) }} · 物品{{ postLabels[claim.post.status] }}</p><p v-if="claim.decision_note" class="notice">发布者说明：{{ claim.decision_note }}</p><p v-if="claim.close_reason" class="notice">{{ closeLabels[claim.close_reason] }}。历史申请保留，重新开放后需要重新申请。</p></section>
        <section class="panel">
          <h2>核实与交接</h2>
          <div class="confirmations"><div><strong>申请者确认</strong><span>{{ datetime(claim.applicant_confirmed_at) }}</span></div><div><strong>发布者确认</strong><span>{{ datetime(claim.publisher_confirmed_at) }}</span></div></div>
          <p v-if="claim.status === 'accepted'" class="notice">请在实际交接后各自确认。只有双方都确认，认领和物品才会一起完成。任一方确认后不能直接取消。</p>
          <p v-else-if="claim.status === 'completed'" class="success">双方均已确认，认领与关联信息已完成。</p>
          <div v-if="!pendingAction" class="actions"><button v-for="action in actions" :key="action" :class="{ secondary: ['reject', 'cancel'].includes(action) }" :disabled="busy" @click="choose(action)">{{ actionLabels[action] }}</button></div>
          <form v-else class="action-form" @submit.prevent="act">
            <h3>{{ actionLabels[pendingAction] }}</h3>
            <template v-if="['accept', 'reject'].includes(pendingAction)"><label for="decision-note">{{ pendingAction === 'reject' ? '拒绝原因（必填）' : '交接说明（选填）' }}</label><textarea id="decision-note" v-model="note" rows="3" maxlength="500" :required="pendingAction === 'reject'" :disabled="busy" /></template>
            <p v-else-if="pendingAction === 'confirm-handover'">请确认你已实际完成物品交接。本次确认提交后不能撤销。</p>
            <p v-else>取消后本次申请结束；如已被同意且双方尚未确认，物品会重新开放。</p>
            <div class="actions"><button :disabled="busy || !actions.includes(pendingAction) || (pendingAction === 'reject' && !note.trim())">{{ busy ? '处理中…' : submitLabels[pendingAction] }}</button><button type="button" class="secondary" :disabled="busy" @click="pendingAction = ''">返回</button></div>
          </form>
          <p v-if="!actions.length && !pendingAction && claim.status === 'pending'" class="muted">等待发布者核实，可先通过右侧会话补充细节。</p>
        </section>
      </div>
      <ClaimChat :key="claim.id" :claim="claim" :refresh-claim="load" />
    </div>
  </template>
</template>
