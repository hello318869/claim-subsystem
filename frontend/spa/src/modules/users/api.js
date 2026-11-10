import { request } from '../../shared/http.js'

// 成员 A 的用户管理接口；页面不得自行拼接路径，统一经 shared/http.js 发送。
export const register = payload => request('/auth/register', { method: 'POST', body: payload, withAuth: false })
export const login = ({ username, password }) => request('/auth/login', { method: 'POST', body: { username, password }, withAuth: false })
export const logout = token => request('/auth/logout', { method: 'POST', authToken: token, sessionScoped: false })
export const me = () => request('/users/me')
export const updateMe = patch => request('/users/me', { method: 'PATCH', body: patch })
export const getBinding = () => request('/users/me/campus-binding')
export const bindCampus = payload => request('/users/me/campus-binding', { method: 'POST', body: payload })
// 校区字典由成员 B 提供；接口不可用时页面降级为文本输入。
export const campuses = () => request('/meta/campuses')
// 契约 v0.3：我的发布由 A 直接查询 B 的 Post 表，B 不再提供列表接口。
export const myPosts = ({ post_type, status, page = 1, page_size = 20 } = {}) =>
  request('/users/me/posts', { query: { post_type, status, page, page_size } })
