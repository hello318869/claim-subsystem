export const routes = [
  { path: '/login', component: () => import('./pages/LoginPage.vue') },
  { path: '/register', component: () => import('./pages/RegisterPage.vue') },
  { path: '/me/profile', component: () => import('./pages/ProfilePage.vue'), meta: { requiresAuth: true } },
  { path: '/me/posts', component: () => import('./pages/MyPostsPage.vue'), meta: { requiresAuth: true } },
  { path: '/me/campus-binding', component: () => import('./pages/CampusBindingPage.vue'), meta: { requiresAuth: true } },
]
