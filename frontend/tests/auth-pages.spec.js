import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', () => ({
  default: { post: vi.fn() },
  TOKEN_STORAGE_KEY: 'uptime_guardian_token',
  extractErrorMessage: (e) => e?.message || 'error',
  settingsApi: { get: vi.fn().mockResolvedValue({ data: {} }) },
}))

const pushMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
}))

import Login from '@/views/Login.vue'
import Register from '@/views/Register.vue'
import { useAuthStore } from '@/stores/auth'

const stubs = { RouterLink: true }

describe('Login page (Task 13.7)', () => {
  let auth
  beforeEach(() => {
    setActivePinia(createPinia())
    auth = useAuthStore()
    pushMock.mockClear()
  })

  it('renders username, password, and the Turnstile widget initially empty (Req 20.2)', () => {
    const wrapper = mount(Login, { global: { stubs } })
    expect(wrapper.find('#username').exists()).toBe(true)
    expect(wrapper.find('#password').exists()).toBe(true)
    expect(wrapper.find('[data-testid="turnstile-dev-verify"]').exists()).toBe(true)
    expect(wrapper.find('#username').element.value).toBe('')
  })

  it('blocks submit without a Turnstile token (Req 20.4)', async () => {
    const spy = vi.spyOn(auth, 'login').mockResolvedValue('tok')
    const wrapper = mount(Login, { global: { stubs } })
    await wrapper.find('#username').setValue('alice')
    await wrapper.find('#password').setValue('pw')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(spy).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Complete the bot challenge')
  })

  it('blocks submit with empty required fields (Req 20.5)', async () => {
    const spy = vi.spyOn(auth, 'login').mockResolvedValue('tok')
    const wrapper = mount(Login, { global: { stubs } })
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(spy).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Username is required')
    expect(wrapper.text()).toContain('Password is required')
  })

  it('includes the token and calls login when valid (Req 20.3)', async () => {
    const spy = vi.spyOn(auth, 'login').mockResolvedValue('tok')
    const wrapper = mount(Login, { global: { stubs } })
    await wrapper.find('#username').setValue('alice')
    await wrapper.find('#password').setValue('pw')
    await wrapper.find('[data-testid="turnstile-dev-verify"]').trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(spy).toHaveBeenCalledWith('alice', 'pw', 'dev-turnstile-token')
  })

  it('shows an error and resets the widget on API failure (Req 20.6)', async () => {
    vi.spyOn(auth, 'login').mockRejectedValue({ response: { status: 401 } })
    const wrapper = mount(Login, { global: { stubs } })
    await wrapper.find('#username').setValue('alice')
    await wrapper.find('#password').setValue('pw')
    await wrapper.find('[data-testid="turnstile-dev-verify"]').trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('Invalid username or password')
    // A second submit is blocked because the token was reset (Req 20.6).
    const spy2 = vi.spyOn(auth, 'login')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(spy2).not.toHaveBeenCalled()
  })
})

describe('Register page (Task 13.7)', () => {
  let auth
  beforeEach(() => {
    setActivePinia(createPinia())
    auth = useAuthStore()
    pushMock.mockClear()
  })

  it('renders username, email, password, and the widget (Req 20.1)', () => {
    const wrapper = mount(Register, { global: { stubs } })
    expect(wrapper.find('#username').exists()).toBe(true)
    expect(wrapper.find('#email').exists()).toBe(true)
    expect(wrapper.find('#password').exists()).toBe(true)
    expect(wrapper.find('[data-testid="turnstile-dev-verify"]').exists()).toBe(true)
  })

  it('blocks submit without a token and reports each empty field (Req 20.4, 20.5)', async () => {
    const spy = vi.spyOn(auth, 'register').mockResolvedValue({})
    const wrapper = mount(Register, { global: { stubs } })
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(spy).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Username is required')
    expect(wrapper.text()).toContain('Email is required')
    expect(wrapper.text()).toContain('Complete the bot challenge')
  })

  it('submits with the token when valid', async () => {
    const spy = vi.spyOn(auth, 'register').mockResolvedValue({})
    const wrapper = mount(Register, { global: { stubs } })
    await wrapper.find('#username').setValue('bob')
    await wrapper.find('#email').setValue('bob@example.com')
    await wrapper.find('#password').setValue('pw')
    await wrapper.find('[data-testid="turnstile-dev-verify"]').trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(spy).toHaveBeenCalledWith('bob', 'bob@example.com', 'pw', 'dev-turnstile-token')
  })
})
