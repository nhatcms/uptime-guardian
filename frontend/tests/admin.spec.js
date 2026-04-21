import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', () => ({
  default: {},
  TOKEN_STORAGE_KEY: 'uptime_guardian_token',
  extractErrorMessage: (e) => e?.message || 'error',
  settingsApi: { get: vi.fn().mockResolvedValue({ data: { username: 'a', is_admin: true } }) },
  adminApi: {
    listPlans: vi.fn(),
    createPlan: vi.fn(),
    updatePlan: vi.fn(),
    deletePlan: vi.fn(),
    listUsers: vi.fn(),
    listTransactions: vi.fn(),
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

import Admin from '@/views/Admin.vue'
import { adminApi } from '@/api'
import { useAuthStore } from '@/stores/auth'

const PLAN = {
  id: 1,
  name: 'Pro',
  price: '100000.00',
  max_monitors: 10,
  min_interval_minutes: 1,
  ssl_check_enabled: true,
  duration_days: 30,
}

const stubs = { RouterLink: true }

describe('Admin console (Task 13.9)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders an access-denied panel for a non-admin (Req 22.5)', async () => {
    const auth = useAuthStore()
    auth.setToken('t')
    auth.user = { username: 'u', is_admin: false }
    const wrapper = mount(Admin, { global: { stubs } })
    await flushPromises()

    expect(wrapper.find('[data-testid="access-denied"]').exists()).toBe(true)
    expect(adminApi.listPlans).not.toHaveBeenCalled()
  })

  it('renders plan controls and lists for an admin (Req 22.1, 22.2, 22.4)', async () => {
    const auth = useAuthStore()
    auth.setToken('t')
    auth.user = { username: 'admin', is_admin: true }
    adminApi.listPlans.mockResolvedValue({ data: [PLAN] })
    adminApi.listUsers.mockResolvedValue({ data: [] })
    adminApi.listTransactions.mockResolvedValue({ data: [] })

    const wrapper = mount(Admin, { global: { stubs } })
    await flushPromises()

    // Plan create/update form is present (Req 22.1).
    expect(wrapper.find('[data-testid="plan-form"]').exists()).toBe(true)
    // Plan list shows the existing plan.
    expect(wrapper.find('[data-testid="plan-list"]').text()).toContain('Pro')
    // Empty-state indications for users and transactions (Req 22.3, 22.4).
    expect(wrapper.find('[data-testid="users-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="transactions-empty"]').exists()).toBe(true)
  })

  it('populates user and transaction tables when data is present (Req 22.2, 22.4)', async () => {
    const auth = useAuthStore()
    auth.setToken('t')
    auth.user = { username: 'admin', is_admin: true }
    adminApi.listPlans.mockResolvedValue({ data: [] })
    adminApi.listUsers.mockResolvedValue({
      data: [{ username: 'bob', email: 'bob@e.co', plan_name: 'Free' }],
    })
    adminApi.listTransactions.mockResolvedValue({
      data: [{ user: 'bob', plan: 'Pro', amount: '100000.00', status: 'completed' }],
    })

    const wrapper = mount(Admin, { global: { stubs } })
    await flushPromises()

    expect(wrapper.find('[data-testid="user-table"]').text()).toContain('bob')
    expect(wrapper.find('[data-testid="transaction-table"]').text()).toContain('completed')
  })
})
