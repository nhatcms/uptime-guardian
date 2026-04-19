import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

// Views are lazily imported so the router config stays valid even before a
// view file exists (created in later tasks 13.2, 14, 15). Dynamic imports also
// keep each view in its own chunk.
const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    name: 'dashboard',
    component: () => import('@/views/Dashboard.vue'),
  },
  {
    path: '/monitors/:id',
    name: 'monitor-detail',
    component: () => import('@/views/MonitorDetail.vue'),
    props: true,
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// Global auth guard: redirect to /login when no Auth_Token is held. Routes
// flagged `meta.public` (the login view) are always allowed, which prevents a
// redirect loop. (Requirement 11.8)
router.beforeEach((to) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    return true
  }

  if (!auth.isAuthenticated) {
    return { name: 'login' }
  }

  return true
})

export default router
