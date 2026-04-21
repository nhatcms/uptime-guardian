import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', () => ({
  default: {},
  TOKEN_STORAGE_KEY: 'uptime_guardian_token',
  extractErrorMessage: (e) => e?.message || 'error',
  plansApi: { list: vi.fn() },
  settingsApi: { get: vi.fn(), setTelegram: vi.fn() },
  paymentsApi: { initiate: vi.fn() },
}))

import SettingsPanel from '@/components/SettingsPanel.vue'
import { plansApi, settingsApi, paymentsApi } from '@/api'

const SETTINGS = {
  username: 'u',
  email: 'u@e.co',
  is_admin: false,
  telegram_chat_id: '123456',
  plan: {
    name: 'Pro',
    price: '100000.00',
    max_monitors: 10,
    min_interval_minutes: 1,
    ssl_check_enabled: true,
    duration_days: 30,
  },
  monitors_used: 3,
  monitors_total: 10,
  plan_expires_at: '2026-12-01T00:00:00Z',
}

const TEAM = {
  id: 2,
  name: 'Team',
  price: '200000.00',
  max_monitors: 50,
  min_interval_minutes: 1,
  ssl_check_enabled: true,
  duration_days: 30,
}

function mountPanel() {
  return mount(SettingsPanel, { global: { stubs: { RouterLink: true } } })
}

describe('Dashboard settings panel (Task 13.8)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    settingsApi.get.mockResolvedValue({ data: SETTINGS })
    plansApi.list.mockResolvedValue({ data: [TEAM] })
  })

  it('shows plan limits, "used of total" usage, expiry, and telegram field (Req 21.1-21.4)', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('[data-testid="plan-name"]').text()).toBe('Pro')
    expect(wrapper.find('[data-testid="usage"]').text()).toBe('3 of 10')
    expect(wrapper.find('[data-testid="expiry"]').exists()).toBe(true)
    expect(wrapper.find('#telegram').element.value).toBe('123456')
  })

  it('renders the SePay QR on a successful upgrade (Req 21.5)', async () => {
    paymentsApi.initiate.mockResolvedValue({
      data: { qr_url: 'https://qr.sepay.vn/img?x=1', reference_code: 'NCMSABC', amount: '200000.00' },
    })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('[data-testid="upgrade-2"]').trigger('click')
    await flushPromises()

    const qr = wrapper.find('[data-testid="upgrade-qr"]')
    expect(qr.exists()).toBe(true)
    expect(qr.find('img').attributes('src')).toBe('https://qr.sepay.vn/img?x=1')
  })

  it('shows a retryable error when the QR request fails (Req 21.6)', async () => {
    paymentsApi.initiate.mockRejectedValue(new Error('payment failed'))
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('[data-testid="upgrade-2"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="upgrade-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="upgrade-retry"]').exists()).toBe(true)
  })

  it('saves the telegram chat id (Req 10.1)', async () => {
    settingsApi.setTelegram.mockResolvedValue({ data: {} })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('#telegram').setValue('999')
    await wrapper.find('#telegram').trigger('input')
    // Click the Save button next to the field.
    const saveBtn = wrapper.findAll('button').find((b) => b.text() === 'Save')
    await saveBtn.trigger('click')
    await flushPromises()
    expect(settingsApi.setTelegram).toHaveBeenCalledWith('999')
  })
})
