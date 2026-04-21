import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

// Views are lazily imported so the router config stays valid even before a
// view file exists (created in later tasks 13.2, 14, 15). Dynamic imports also
// keep each view in its own chunk.
const routes = [
  {
    path: '/',
    name: 'landing',
    component: () => import('@/views/Landing.vue'),
    meta: { public: true },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/Register.vue'),
    meta: { public: true },
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/Dashboard.vue'),
  },
  {
    path: '/monitors/:id',
    name: 'monitor-detail',
    component: () => import('@/views/MonitorDetail.vue'),
    props: true,
  },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('@/views/Admin.vue'),
    meta: { admin: true },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// Global navigation guard.
//
// - Public routes (landing, login, register) are always allowed (Req 19, 20).
// - Unauthenticated access to a protected route redirects to login
//   (Requirements 11.8, 22.6).
// - An authenticated non-admin reaching an admin route is sent to the
//   dashboard; the Admin view also renders an access-denied panel as defense
//   in depth (Requirement 22.5).
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    return true
  }

  if (!auth.isAuthenticated) {
    return { name: 'login' }
  }

  if (to.meta.admin) {
    // Ensure the profile (with is_admin) is loaded before deciding.
    if (!auth.user) {
      await auth.fetchProfile()
    }
    if (!auth.isAdmin) {
      return { name: 'dashboard' }
    }
  }

  return true
})

export default router
