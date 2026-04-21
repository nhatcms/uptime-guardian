import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, RouterLinkStub } from '@vue/test-utils'

vi.mock('@/api', () => ({
  plansApi: { list: vi.fn() },
}))

import Landing from '@/views/Landing.vue'
import { plansApi } from '@/api'

const PLAN = {
  id: 1,
  name: 'Pro',
  price: '100000.00',
  max_monitors: 10,
  min_interval_minutes: 1,
  ssl_check_enabled: true,
  duration_days: 30,
}

function mountLanding() {
  return mount(Landing, {
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

describe('Landing page (Task 13.6)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders one card per active plan and a register CTA (Req 19.1, 19.6)', async () => {
    plansApi.list.mockResolvedValue({ data: [PLAN, { ...PLAN, id: 2, name: 'Team' }] })
    const wrapper = mountLanding()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="plan-card"]')).toHaveLength(2)
    const cta = wrapper.find('[data-testid="cta-register"]')
    expect(cta.exists()).toBe(true)
    expect(cta.props('to')).toEqual({ name: 'register' })
  })

  it('shows a placeholder when there are no plans (Req 19.3)', async () => {
    plansApi.list.mockResolvedValue({ data: [] })
    const wrapper = mountLanding()
    await flushPromises()

    expect(wrapper.find('[data-testid="pricing-placeholder"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="plan-card"]')).toHaveLength(0)
  })

  it('shows an error banner and placeholder when the fetch fails (Req 19.4)', async () => {
    plansApi.list.mockRejectedValue(new Error('boom'))
    const wrapper = mountLanding()
    await flushPromises()

    expect(wrapper.find('[data-testid="pricing-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="pricing-placeholder"]').exists()).toBe(true)
    // The rest of the page (CTA) stays intact.
    expect(wrapper.find('[data-testid="cta-register"]').exists()).toBe(true)
  })
})
