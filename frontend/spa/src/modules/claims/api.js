import { request } from '../../shared/http.js'

const id = value => encodeURIComponent(value)
export const getPost = postId => request(`/posts/${id(postId)}`)
export const createClaim = data => request('/claims', { method: 'POST', body: data })
export const getClaim = claimId => request(`/claims/${id(claimId)}`)
export const listClaims = query => request('/users/me/claims', { query })
export const actOnClaim = (claimId, action, body) => request(`/claims/${id(claimId)}/${action}`, { method: 'POST', body })
export const getMessages = (claimId, query, signal) => request(`/claims/${id(claimId)}/messages`, { query, signal })
export const sendMessage = (claimId, content, signal) => request(`/claims/${id(claimId)}/messages`, { method: 'POST', body: { content }, signal })
export const getMatches = postId => request(`/posts/${id(postId)}/matches`)
