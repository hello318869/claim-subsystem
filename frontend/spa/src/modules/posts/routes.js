export const routes = [
  {
    path: '/team', name: 'post-list', meta: { postsSurface: true },
    component: () => import('./views/ListView.vue'),
  },
  {
    path: '/posts/new', name: 'post-new', meta: { postsSurface: true, requiresAuth: true },
    component: () => import('./views/EditorView.vue'),
  },
  {
    path: '/posts/:id/edit', name: 'post-edit', meta: { postsSurface: true, requiresAuth: true },
    component: () => import('./views/EditorView.vue'),
  },
  {
    path: '/posts/:id', name: 'post-detail', meta: { postsSurface: true },
    component: () => import('./views/DetailView.vue'),
  },
]
