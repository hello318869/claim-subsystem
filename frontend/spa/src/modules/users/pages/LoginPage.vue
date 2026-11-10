<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { setSession } from '../../../shared/session.js'
import { errorText } from '../../../shared/http.js'
import { login } from '../api.js'

const route = useRoute()
const router = useRouter()
const username = ref(typeof route.query.username === 'string' ? route.query.username : '')
const password = ref('')
const fieldErrors = ref({})
const formError = ref('')
const busy = ref(false)
const registered = computed(() => route.query.registered === '1')
const registeredName = computed(() => (typeof route.query.username === 'string' ? route.query.username : ''))

// 只接受站内相对路径，拒绝 //evil.example 这类协议相对地址。
function safeNext(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return null
  return value
}

async function submit() {
  if (busy.value) return
  fieldErrors.value = {}
  formError.value = ''
  const account = username.value.trim()
  const problems = {}
  if (!account) problems.username = '请输入账号'
  if (!password.value) problems.password = '请输入密码'
  if (Object.keys(problems).length) {
    fieldErrors.value = problems
    return
  }
  busy.value = true
  try {
    const data = await login({ username: account, password: password.value })
    setSession(data)
    password.value = ''
    await router.replace(safeNext(route.query.next) || '/demo')
  } catch (err) {
    formError.value = errorText(err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page-heading">
    <p class="eyebrow">SIGN IN</p>
    <h1>登录</h1>
    <p class="muted">登录后可管理个人资料、绑定校园身份并参与失物认领。</p>
  </div>
  <p v-if="registered" class="success" role="status">注册成功，请使用新账号登录。{{ registeredName ? `账号：${registeredName}` : '' }}</p>
  <form class="panel auth-panel" novalidate @submit.prevent="submit">
    <h2>账号登录</h2>
    <p v-if="formError" class="error" role="alert">{{ formError }}</p>
    <label for="login-username">账号</label>
    <input id="login-username" v-model="username" name="username" autocomplete="username" :disabled="busy">
    <p v-if="fieldErrors.username" class="field-error">{{ fieldErrors.username }}</p>
    <label for="login-password">密码</label>
    <input id="login-password" v-model="password" name="password" type="password" autocomplete="current-password" :disabled="busy">
    <p v-if="fieldErrors.password" class="field-error">{{ fieldErrors.password }}</p>
    <button type="submit" :disabled="busy">{{ busy ? '登录中…' : '登录' }}</button>
    <p class="muted">还没有账号？<RouterLink to="/register">注册新账号</RouterLink> · <RouterLink to="/demo">演示工作台</RouterLink></p>
  </form>
</template>

<style scoped>
.auth-panel button { width: 100%; margin: 20px 0 12px; }
.field-error { color: #994529; font-size: 13px; margin: 6px 0 0; }
</style>
