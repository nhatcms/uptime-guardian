import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock the API module so importing the router/stores has no axios side effects.
vi.mock('@/api', () => {
  const api = {
    post: vi.fn(),
    get: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  }
  return {
    default: api,
    TOKEN_STORAGE_KEY: 'uptime_guardian_token',
    extractErrorMessage: (e) => e?.message || 'error',
    plansApi: { list: vi.fn() },
    settingsApi: { get: vi.fn().mockResolvedValue({ data: {} }), setTelegram: vi.fn() },
    paymentsApi: { initiate: vi.fn() },
    adminApi: {
      listPlans: vi.fn(),
      createPlan: vi.fn(),
      updatePlan: vi.fn(),
      deletePlan: vi.fn(),
      listUsers: vi.fn(),
      listTransactions: vi.fn(),
    },
  }
})

import router from '@/router'
import { useAuthStore } from '@/stores/auth'

describe('router navigation guard (Task 12.5)', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    // Reset to the public landing route between tests.
    await router.replace('/')
    await router.isReady()
  })

  it('allows public routes without authentication', async () => {
    await router.push('/login')
    expect(router.currentRoute.value.name).toBe('login')
    await router.push('/register')
    expect(router.currentRoute.value.name).toBe('register')
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('landing')
  })

  it('redirects unauthenticated access to /admin to login (Req 22.6)', async () => {
    const auth = useAuthStore()
    auth.setToken(null)
    await router.push('/admin')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('redirects unauthenticated access to /dashboard to login (Req 11.8)', async () => {
    const auth = useAuthStore()
    auth.setToken(null)
    await router.push('/dashboard')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('sends an authenticated non-admin away from /admin to dashboard (Req 22.5)', async () => {
    const auth = useAuthStore()
    auth.setToken('token')
    auth.user = { username: 'u', is_admin: false }
    await router.push('/admin')
    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  it('allows an authenticated admin into /admin', async () => {
    const auth = useAuthStore()
    auth.setToken('token')
    auth.user = { username: 'admin', is_admin: true }
    await router.push('/admin')
    expect(router.currentRoute.value.name).toBe('admin')
  })
})
