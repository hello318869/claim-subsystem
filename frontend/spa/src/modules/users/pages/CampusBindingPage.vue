<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { session } from '../../../shared/session.js'
import { errorText } from '../../../shared/http.js'
import { datetime } from '../../../shared/utils/datetime.js'
import { bindCampus, campuses as fetchCampuses, getBinding, me } from '../api.js'
import CampusBindingForm from '../components/CampusBindingForm.vue'

const route = useRoute()
const binding = ref(null)
const campusOptions = ref([])
const campusFallback = ref(false)
const loading = ref(true)
const loaded = ref(false)
const loadFailed = ref(false)
const busy = ref(false)
const error = ref('')
const success = ref('')
const fieldErrors = ref({})
const BINDING_FIELDS = ['campus_id', 'student_no', 'binding_code']

// 只接受站内相对路径，认证完成后可回到刚才被拦截的操作（如申请认领）。
function safeNext(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return null
  return value
}
const nextPath = computed(() => safeNext(route.query.next))

function normalizeCampuses(data) {
  const list = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : [])
  return list
    .map(item => ({ id: String(item?.id ?? ''), name: item?.name ?? String(item?.id ?? '') }))
    .filter(item => item.id)
}

async function load() {
  loading.value = true
  loadFailed.value = false
  error.value = ''
  const [bindingResult, campusResult] = await Promise.allSettled([getBinding(), fetchCampuses()])
  loading.value = false
  loaded.value = true
  if (bindingResult.status === 'fulfilled') {
    binding.value = bindingResult.value ?? null
  } else {
    loadFailed.value = true
    error.value = errorText(bindingResult.reason)
  }
  if (campusResult.status === 'fulfilled') {
    campusOptions.value = normalizeCampuses(campusResult.value)
    campusFallback.value = campusOptions.value.length === 0
  } else {
    // 字典暂时不可用时允许手动输入校区标识。
    campusOptions.value = []
    campusFallback.value = true
  }
}
onMounted(load)

const verificationLabel = computed(() => (binding.value && binding.value.verification_mode && binding.value.verification_mode !== 'demo'
  ? binding.value.verification_mode
  : '演示认证'))
const campusLabel = computed(() => {
  if (!binding.value) return ''
  const matched = campusOptions.value.find(campus => campus.id === binding.value.campus_id)
  return matched ? `${matched.name}（${binding.value.campus_id}）` : binding.value.campus_id
})

async function submit(payload) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  success.value = ''
  fieldErrors.value = {}
  try {
    const result = await bindCampus(payload)
    success.value = '校园身份绑定成功，演示认证已生效。'
    try {
      // 绑定成功后重新读取绑定状态，并刷新内存会话中的认证标记。
      binding.value = (await getBinding()) ?? result
    } catch {
      binding.value = result
    }
    try {
      session.user = await me()
    } catch {
      // 绑定已成功，资料刷新失败不影响结果展示。
    }
  } catch (err) {
    const serverErrors = err.errors || {}
    const next = {}
    for (const key of BINDING_FIELDS) {
      const values = serverErrors[key]
      if (Array.isArray(values) && values.length) next[key] = values.join('；')
    }
    fieldErrors.value = next
    if (err.status === 409) {
      error.value = next.binding_code || err.message || '该校园身份已被绑定或占用，请检查学号是否已被使用。'
      try {
        binding.value = (await getBinding()) ?? binding.value
      } catch {
        // 状态刷新失败时保留原页面，仅提示冲突。
      }
    } else {
      error.value = Object.keys(next).length ? '' : errorText(err)
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <RouterLink class="back-link" to="/me/profile">← 返回个人中心</RouterLink>
  <div class="page-heading">
    <p class="eyebrow">CAMPUS IDENTITY</p>
    <h1>校园身份绑定</h1>
    <p class="muted">绑定校园身份后即可发起认领。第一版为演示认证，不是真实学校认证。</p>
  </div>
  <p v-if="loading" class="panel">正在加载绑定状态…</p>
  <template v-else-if="loaded">
    <p v-if="error" class="error" role="alert">{{ error }}<button v-if="loadFailed" class="secondary small" @click="load">重试</button></p>
    <p v-if="success" class="success" role="status">{{ success }}</p>
    <section v-if="binding && !loadFailed" class="panel">
      <div class="section-heading">
        <h2>已绑定校园身份</h2>
        <span class="badge">{{ verificationLabel }}</span>
      </div>
      <dl class="info-list">
        <div><dt>校区</dt><dd>{{ campusLabel }}</dd></div>
        <div><dt>认证学号</dt><dd>{{ binding.student_no_masked }}</dd></div>
        <div><dt>认证方式</dt><dd>{{ verificationLabel }}</dd></div>
        <div><dt>绑定时间</dt><dd>{{ datetime(binding.verified_at) }}</dd></div>
      </dl>
      <p class="notice">第一版为演示认证，不是真实学校认证，仅用于课程演示。绑定后不支持解绑。</p>
      <p v-if="nextPath" class="muted"><RouterLink class="button" :to="nextPath">认证完成，继续刚才的操作</RouterLink></p>
      <p class="muted"><RouterLink to="/me/profile">返回个人中心</RouterLink></p>
    </section>
    <section v-else-if="!loadFailed" class="panel">
      <h2>绑定校园身份</h2>
      <p class="muted">填写校区、学号与一次性绑定码完成演示认证。演示绑定码由初始化命令输出。</p>
      <CampusBindingForm
        :busy="busy"
        :campuses="campusOptions"
        :fallback="campusFallback"
        :field-errors="fieldErrors"
        @submit="submit"
      />
    </section>
  </template>
</template>

<style scoped>
.field-error { color: #994529; font-size: 13px; margin: 6px 0 0; }
.info-list { margin: 0 0 16px; }
.info-list > div { display: flex; gap: 16px; padding: 8px 0; border-bottom: 1px dashed #e3e9de; }
.info-list > div:last-child { border-bottom: 0; }
.info-list dt { flex: 0 0 88px; color: #718177; font-size: 14px; }
.info-list dd { margin: 0; font-weight: 600; overflow-wrap: anywhere; }
</style>
