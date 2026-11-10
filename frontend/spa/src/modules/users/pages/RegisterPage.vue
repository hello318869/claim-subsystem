<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { errorText } from '../../../shared/http.js'
import { register } from '../api.js'

const router = useRouter()
const username = ref('')
const nickname = ref('')
const password = ref('')
const confirm = ref('')
const fieldErrors = ref({})
const formError = ref('')
const busy = ref(false)
const USERNAME_PATTERN = /^[A-Za-z0-9_]{4,32}$/
const FIELD_KEYS = ['username', 'nickname', 'password']

function validate() {
  const problems = {}
  const account = username.value.trim()
  const nick = nickname.value.trim()
  if (!USERNAME_PATTERN.test(account)) problems.username = '账号需为 4～32 位字母、数字或下划线'
  if (nick.length < 1 || nick.length > 30) problems.nickname = '昵称需为 1～30 个字符'
  if (password.value.length < 8 || password.value.length > 64) problems.password = '密码长度需为 8～64 个字符'
  if (confirm.value !== password.value) problems.confirm = '两次输入的密码不一致'
  return problems
}

function applyServerError(err) {
  const errors = err.errors || {}
  const next = {}
  for (const key of FIELD_KEYS) {
    const values = errors[key]
    if (Array.isArray(values) && values.length) next[key] = values.join('；')
  }
  fieldErrors.value = next
  const hasFieldError = Object.keys(next).length > 0
  if (err.status === 409) {
    formError.value = next.username || err.message || '该账号已被注册，请更换账号'
  } else if (hasFieldError && Object.keys(errors).every(key => FIELD_KEYS.includes(key))) {
    formError.value = ''
  } else {
    formError.value = errorText(err)
  }
}

async function submit() {
  if (busy.value) return
  formError.value = ''
  const problems = validate()
  fieldErrors.value = problems
  if (Object.keys(problems).length) return
  const payload = { username: username.value.trim(), nickname: nickname.value.trim(), password: password.value }
  busy.value = true
  try {
    await register(payload)
    // 注册成功不自动登录，回到登录页并带入账号。
    await router.push({ path: '/login', query: { registered: '1', username: payload.username } })
  } catch (err) {
    applyServerError(err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page-heading">
    <p class="eyebrow">CREATE ACCOUNT</p>
    <h1>注册新账号</h1>
    <p class="muted">账号用于登录，昵称会展示在认领与沟通页面。注册成功后请返回登录页登录。</p>
  </div>
  <form class="panel auth-panel" novalidate @submit.prevent="submit">
    <h2>创建账号</h2>
    <p v-if="formError" class="error" role="alert">{{ formError }}</p>
    <label for="register-username">账号</label>
    <input id="register-username" v-model="username" name="username" autocomplete="username" maxlength="32" :disabled="busy" placeholder="4～32 位字母、数字或下划线">
    <p v-if="fieldErrors.username" class="field-error">{{ fieldErrors.username }}</p>
    <label for="register-nickname">昵称</label>
    <input id="register-nickname" v-model="nickname" name="nickname" autocomplete="nickname" maxlength="30" :disabled="busy" placeholder="1～30 个字符">
    <p v-if="fieldErrors.nickname" class="field-error">{{ fieldErrors.nickname }}</p>
    <label for="register-password">密码</label>
    <input id="register-password" v-model="password" name="password" type="password" autocomplete="new-password" maxlength="64" :disabled="busy" placeholder="8～64 个字符">
    <p v-if="fieldErrors.password" class="field-error">{{ fieldErrors.password }}</p>
    <label for="register-confirm">确认密码</label>
    <input id="register-confirm" v-model="confirm" name="confirm" type="password" autocomplete="new-password" maxlength="64" :disabled="busy" placeholder="再次输入密码">
    <p v-if="fieldErrors.confirm" class="field-error">{{ fieldErrors.confirm }}</p>
    <button type="submit" :disabled="busy">{{ busy ? '注册中…' : '注册' }}</button>
    <p class="muted">已有账号？<RouterLink to="/login">返回登录</RouterLink></p>
  </form>
</template>

<style scoped>
.auth-panel button { width: 100%; margin: 20px 0 12px; }
.field-error { color: #994529; font-size: 13px; margin: 6px 0 0; }
</style>
