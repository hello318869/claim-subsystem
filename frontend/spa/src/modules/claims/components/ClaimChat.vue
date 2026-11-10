<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import { session } from '../../../shared/session.js'
import { datetime } from '../../../shared/utils/datetime.js'
import { useClaimMessages } from '../composables/useClaimMessages.js'
const props = defineProps({ claim: Object, refreshClaim: Function })
const claimId = computed(() => props.claim.id)
const { messages, error, loading, sending, refresh, send } = useClaimMessages(claimId, () => props.refreshClaim?.())
const draft = ref('')
const log = ref(null)
const writable = computed(() => ['pending', 'accepted'].includes(props.claim.status))
const length = computed(() => Array.from(draft.value.trim()).length)
async function submit() {
  if (writable.value && length.value >= 1 && length.value <= 1000 && await send(draft.value.trim())) draft.value = ''
}
watch(() => messages.value.length, async () => {
  await nextTick()
  if (log.value) log.value.scrollTop = log.value.scrollHeight
})
</script>

<template>
  <section class="panel chat-panel">
    <div class="section-heading"><h2>双方站内沟通</h2><button class="secondary small" :disabled="loading" @click="refresh">刷新消息</button></div>
    <p class="muted">此会话仅认领双方可见。请勿发送手机号、邮箱或身份证号码。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div ref="log" class="chat-log" role="log" aria-label="认领消息" aria-live="polite">
      <p v-if="!messages.length" class="empty">{{ loading ? '加载消息中…' : '还没有消息，可以先打个招呼。' }}</p>
      <article v-for="message in messages" :key="message.id" class="chat-message" :class="{ mine: message.sender_id === session.user?.id }">
        <div class="message-meta">{{ message.sender_id === session.user?.id ? '我' : '对方' }} · {{ datetime(message.created_at) }}</div>
        <p class="message-bubble">{{ message.content }}</p>
      </article>
    </div>
    <form v-if="writable" class="chat-form" @submit.prevent="submit">
      <label for="chat-content">发送消息</label>
      <textarea id="chat-content" v-model="draft" rows="3" :disabled="sending" placeholder="补充物品特征或商量交接时间" />
      <div class="form-bottom"><span class="muted">{{ length }} / 1000 字</span><button :disabled="sending || length < 1 || length > 1000">{{ sending ? '发送中…' : '发送消息' }}</button></div>
    </form>
    <p v-else class="notice">申请已结束，保留消息历史供双方查看。</p>
  </section>
</template>
