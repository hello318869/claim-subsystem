import { computed, onScopeDispose, ref, watch } from 'vue'
import { session } from '../../../shared/session.js'
import { errorText } from '../../../shared/http.js'
import { getMessages, sendMessage } from '../api.js'

const PAGE_SIZE = 50
const POLL_MS = 5000

export function useClaimMessages(claimId, onRefresh = () => {}) {
  const messages = ref([])
  const readError = ref('')
  const sendError = ref('')
  const error = computed(() => sendError.value || readError.value)
  const loading = ref(false)
  const sending = ref(false)
  const seen = new Set()
  let controller, timer, flight
  let cursor = null
  let generation = 0

  function stop() {
    generation++
    clearTimeout(timer)
    controller?.abort()
    flight = null
  }

  function append(batch) {
    for (const message of batch) {
      if (typeof message.id !== 'string' || typeof message.content !== 'string') {
        throw new Error('消息字段不完整')
      }
      if (seen.has(message.id)) continue
      seen.add(message.id)
      messages.value.push(message)
    }
  }

  function refresh() {
    if (flight) return flight
    if (!claimId.value || !session.token || !controller) return Promise.resolve(false)
    const run = generation
    const activeId = claimId.value
    const { signal } = controller
    loading.value = true
    flight = (async () => {
      try {
        let more
        do {
          const batch = await getMessages(activeId, { after_id: cursor, limit: PAGE_SIZE }, signal)
          if (run !== generation) return false
          const next = batch?.next_after_id
          if (!Array.isArray(batch?.items) || typeof batch.has_more !== 'boolean' ||
              (next !== null && typeof next !== 'string') ||
              (batch.has_more && (!next || next === cursor))) {
            throw new Error('消息分页响应或游标无效')
          }
          append(batch.items)
          cursor = next
          more = batch.has_more
        } while (more)
        readError.value = ''
        await onRefresh()
        return run === generation
      } catch (err) {
        if (run !== generation || err.name === 'AbortError') return false
        if (err.status === 404 || err.status === 403) {
          messages.value = []
          seen.clear()
          cursor = null
          await onRefresh()
        }
        if (run === generation) readError.value = errorText(err)
        return false
      } finally {
        if (run === generation) {
          loading.value = false
          flight = null
        }
      }
    })()
    return flight
  }

  async function poll(run) {
    await refresh()
    if (run === generation && session.token) timer = setTimeout(() => poll(run), POLL_MS)
  }

  watch([claimId, () => session.revision], () => {
    stop()
    controller = new AbortController()
    cursor = null
    seen.clear()
    messages.value = []
    readError.value = ''
    sendError.value = ''
    loading.value = false
    sending.value = false
    if (claimId.value && session.token) void poll(generation)
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(stop)

  async function refreshAfterSend(run) {
    if (flight) await flight
    return run === generation && await refresh()
  }

  async function send(content) {
    if (sending.value || !claimId.value || !session.token || !controller) return false
    sending.value = true
    sendError.value = ''
    const run = generation
    try {
      await sendMessage(claimId.value, content, controller.signal)
      await refreshAfterSend(run)
      return run === generation
    } catch (err) {
      if (run !== generation || err.name === 'AbortError') return false
      if (!err.status || err.status >= 500 || err.code === 'INVALID_RESPONSE') {
        const refreshed = await refreshAfterSend(run)
        if (run === generation) sendError.value = refreshed
          ? '发送结果未确认，已刷新消息。请检查记录后再决定是否重新发送。'
          : '发送结果未确认，消息列表也未能刷新。请先刷新并检查记录，再决定是否重新发送。'
      } else {
        if ([403, 404, 409].includes(err.status)) await onRefresh()
        if (run === generation) sendError.value = errorText(err)
      }
      return false
    } finally {
      if (run === generation) sending.value = false
    }
  }

  return { messages, error, loading, sending, refresh, send }
}
