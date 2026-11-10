import { request } from './http.js'

/* 字典接口（契约 §5.1，均不分页）。字典由 B 维护固定种子数据，前端不自行编号。 */

export function listCampuses() {
  return request('/meta/campuses', { anonymousRetry: true })
}

export function listCategories() {
  return request('/meta/categories', { anonymousRetry: true })
}

export function listLocations(campusId) {
  return request('/meta/locations', {
    query: campusId ? { campus_id: campusId } : undefined,
    anonymousRetry: true,
  })
}
