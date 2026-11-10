export const routes = [
  { path: '/claims/new', component: () => import('./pages/ClaimCreatePage.vue'), meta: { requiresAuth: true } },
  { path: '/me/claims', component: () => import('./pages/ClaimListPage.vue'), meta: { requiresAuth: true } },
  { path: '/claims/:id', component: () => import('./pages/ClaimDetailPage.vue'), meta: { requiresAuth: true } },
  { path: '/posts/:id/matches', name: 'post-matches', component: () => import('./pages/MatchResultsPage.vue'), meta: { requiresAuth: true } },
]
