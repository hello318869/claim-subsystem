import { reactive } from 'vue'

export const session = reactive({ token: null, user: null, revision: 0 })
let lifetime = new AbortController()

export const sessionSignal = () => lifetime.signal

function renewLifetime() {
  lifetime.abort()
  lifetime = new AbortController()
}

export function setSession(data) {
  if (typeof data?.access_token !== 'string' || !data.access_token || typeof data.user?.id !== 'string' || !data.user.id) {
    throw new Error('登录响应缺少访问令牌或用户信息')
  }
  renewLifetime()
  session.user = data.user
  session.token = data.access_token
  session.revision++
}
export function clearSession() {
  if (!session.token && !session.user) return
  renewLifetime()
  session.token = null
  session.user = null
  session.revision++
}
