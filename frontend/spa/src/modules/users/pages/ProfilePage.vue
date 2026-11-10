<script setup>
import { onMounted, ref } from 'vue'
import { session } from '../../../shared/session.js'
import { errorText } from '../../../shared/http.js'
import { datetime } from '../../../shared/utils/datetime.js'
import { me, updateMe } from '../api.js'

const profile = ref(null)
const loading = ref(true)
const busy = ref(false)
const loadError = ref('')
const formError = ref('')
const success = ref('')
const fieldErrors = ref({})
const nickname = ref('')
const bio = ref('')
const FIELD_KEYS = ['nickname', 'bio']

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await me()
    profile.value = data
    nickname.value = data.nickname
    bio.value = data.bio || ''
    // 进入个人中心时用服务端最新资料刷新内存会话。
    session.user = data
  } catch (err) {
    loadError.value = errorText(err)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function validate() {
  const problems = {}
  const nick = nickname.value.trim()
  if (nick.length < 1 || nick.length > 30) problems.nickname = '昵称需为 1～30 个字符'
  if (bio.value.length > 200) problems.bio = '简介不能超过 200 个字符'
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
  formError.value = Object.keys(next).length ? '' : errorText(err)
}

async function save() {
  if (busy.value) return
  formError.value = ''
  success.value = ''
  const problems = validate()
  fieldErrors.value = problems
  if (Object.keys(problems).length) return
  busy.value = true
  try {
    const data = await updateMe({ nickname: nickname.value.trim(), bio: bio.value.trim() })
    profile.value = data
    session.user = data
    nickname.value = data.nickname
    bio.value = data.bio || ''
    success.value = '资料已保存'
  } catch (err) {
    applyServerError(err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <RouterLink class="back-link" to="/demo">← 返回工作台</RouterLink>
  <div class="page-heading">
    <p class="eyebrow">MY PROFILE</p>
    <h1>个人中心</h1>
    <p class="muted">查看账号信息，维护昵称与简介。账号与注册时间不可修改。</p>
  </div>
  <p v-if="loading" class="panel">正在加载个人资料…</p>
  <template v-else>
    <p v-if="loadError" class="error" role="alert">{{ loadError }} <button class="secondary small" @click="load">重试</button></p>
    <template v-if="profile">
      <section class="panel">
        <div class="section-heading">
          <h2>账号信息</h2>
          <span class="badge">{{ profile.is_campus_verified ? '演示认证' : '未认证' }}</span>
        </div>
        <dl class="info-list">
          <div><dt>账号</dt><dd>{{ profile.username }}</dd></div>
          <div><dt>注册时间</dt><dd>{{ datetime(profile.created_at) }}</dd></div>
          <div><dt>认证状态</dt><dd>{{ profile.is_campus_verified ? '演示认证' : '未认证' }}</dd></div>
        </dl>
        <p class="muted">认证状态仅供本系统演示使用，不是真实学校认证。</p>
        <p class="profile-actions">
          <RouterLink class="button" to="/me/campus-binding">{{ profile.is_campus_verified ? '查看校园身份绑定' : '校园身份绑定（去认证）' }}</RouterLink>
          <RouterLink class="button secondary" to="/me/posts">我的发布</RouterLink>
        </p>
      </section>
      <form class="panel" novalidate @submit.prevent="save">
        <h2>编辑资料</h2>
        <p v-if="success" class="success" role="status">{{ success }}</p>
        <p v-if="formError" class="error" role="alert">{{ formError }}</p>
        <label for="profile-nickname">昵称</label>
        <input id="profile-nickname" v-model="nickname" name="nickname" maxlength="30" :disabled="busy">
        <p v-if="fieldErrors.nickname" class="field-error">{{ fieldErrors.nickname }}</p>
        <label for="profile-bio">简介</label>
        <textarea id="profile-bio" v-model="bio" name="bio" rows="4" maxlength="200" :disabled="busy" placeholder="一句话介绍自己（选填）" />
        <p v-if="fieldErrors.bio" class="field-error">{{ fieldErrors.bio }}</p>
        <div class="form-bottom">
          <span class="muted">{{ bio.length }} / 200 字</span>
          <button type="submit" :disabled="busy || loading">{{ busy ? '保存中…' : '保存资料' }}</button>
        </div>
      </form>
    </template>
  </template>
</template>

<style scoped>
.field-error { color: #994529; font-size: 13px; margin: 6px 0 0; }
.info-list { margin: 0 0 16px; }
.info-list > div { display: flex; gap: 16px; padding: 8px 0; border-bottom: 1px dashed #e3e9de; }
.info-list > div:last-child { border-bottom: 0; }
.info-list dt { flex: 0 0 88px; color: #718177; font-size: 14px; }
.info-list dd { margin: 0; font-weight: 600; overflow-wrap: anywhere; }
.profile-actions { display: flex; flex-wrap: wrap; gap: 10px; }
</style>
