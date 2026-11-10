import { createRouter, createWebHistory } from 'vue-router'
import { session } from '../shared/session.js'
import { routes as claimRoutes } from '../modules/claims/routes.js'
import { routes as userRoutes } from '../modules/users/routes.js'
import { routes as postRoutes } from '../modules/posts/routes.js'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/team' },
    { path: '/demo', redirect: '/team' },
    ...postRoutes,
    ...userRoutes,
    ...claimRoutes,
    { path: '/:pathMatch(.*)*', redirect: '/team' },
  ],
  scrollBehavior(to, from, savedPosition) {
    return savedPosition || (to.path === from.path ? undefined : { top: 0 })
  },
})
router.beforeEach(to => {
  if (to.meta.requiresAuth && !session.token) return { path: '/login', query: { next: to.fullPath } }
})
export default router
