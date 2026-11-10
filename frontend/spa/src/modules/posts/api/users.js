import { request } from './http.js'

/*
 * 当前登录用户。GET /users/me 由 A 提供（契约 §4），B 只用它判断
 * “这条信息是不是我发布的”，以便显示编辑 / 撤回 / 恢复 / 办结按钮。
 * A 的接口未就绪时静默失败，页面按“身份未知”降级（操作结果仍以服务端校验为准）。
 */
export async function getCurrentUser() {
  try {
    return await request('/users/me')
  } catch (err) {
    return null
  }
}
