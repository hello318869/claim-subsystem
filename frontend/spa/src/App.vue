<script setup>
import { watch, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { session, clearSession } from './shared/session.js'
import { errorText } from './shared/http.js'
import { logout as revokeSession } from './modules/users/api.js'

const router = useRouter()
const route = useRoute()
const loggingOut = ref(false)
const logoutError = ref('')
async function logout() {
  if (loggingOut.value) return
  loggingOut.value = true
  logoutError.value = ''
  const token = session.token
  clearSession()
  const revision = session.revision
  void router.replace('/team')
  try {
    await revokeSession(token)
  } catch (error) {
    if (session.revision === revision && error.name !== 'AbortError' && error.status !== 401) {
      logoutError.value = `当前页面已退出，服务端撤销会话失败。${errorText(error)}`
    }
  } finally {
    loggingOut.value = false
  }
}
watch(() => session.token, token => {
  if (token) logoutError.value = ''
  if (!token && !loggingOut.value && route.meta.requiresAuth) router.replace({ path: '/login', query: { next: route.fullPath } })
})
</script>

<template>
  <header class="site-header">
    <div class="header-inner">
      <RouterLink class="brand" to="/team"><span class="brand-mark">归</span><span>校园失物招领<small>让物品回到主人身边</small></span></RouterLink>
      <nav aria-label="主导航">
        <RouterLink to="/team">公开信息</RouterLink>
        <RouterLink to="/posts/new">发布信息</RouterLink>
        <template v-if="session.user">
          <RouterLink to="/me/claims?role=applicant">我的认领</RouterLink>
          <RouterLink to="/me/claims?role=publisher">收到的申请</RouterLink>
          <RouterLink to="/me/profile">个人中心</RouterLink>
          <RouterLink to="/me/posts">我的发布</RouterLink>
          <RouterLink to="/me/campus-binding">校园身份认证</RouterLink>
        </template>
        <template v-else>
          <RouterLink to="/login">登录</RouterLink>
          <RouterLink to="/register">注册</RouterLink>
        </template>
      </nav>
      <div v-if="session.user" class="account">
        <span>{{ session.user.nickname }}<small>{{ session.user.is_campus_verified ? (session.user.verification_mode === 'demo' ? '演示认证' : '已认证') : '未认证' }}</small></span>
        <button class="secondary small" :disabled="loggingOut" @click="logout">退出登录</button>
      </div>
    </div>
  </header>
  <main class="container">
    <p v-if="logoutError" class="error" role="alert">{{ logoutError }}</p>
    <RouterView v-slot="{ Component }">
      <div :class="{ 'posts-surface': route.meta.postsSurface }">
        <component v-if="!route.meta.requiresAuth || session.token" :is="Component" :key="`${route.path}:${session.revision}`" />
      </div>
    </RouterView>
  </main>
  <footer class="site-footer">课程演示 · 账户与校园身份 · 信息发布与浏览 · 认领、沟通与匹配</footer>
</template>

<style scoped>
@media (max-width: 850px) {
  nav { flex-wrap: wrap; row-gap: 2px; }
  .account { max-width: 100%; overflow-wrap: anywhere; }
}
</style>
