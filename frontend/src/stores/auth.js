import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import api, { TOKEN_STORAGE_KEY, settingsApi } from '@/api'

/**
 * Read the persisted Auth_Token from localStorage.
 *
 * Wrapped in try/catch because localStorage may be unavailable (e.g. SSR or a
 * privacy-restricted browser context).
 */
function readPersistedToken() {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

/** Persist the Auth_Token to localStorage. */
function persistToken(token) {
  try {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token)
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
    }
  } catch {
    // localStorage may be unavailable; the in-memory token still works for
    // the current session.
  }
}

/**
 * Authentication store: holds the Auth_Token, exposes login/logout actions, and
 * wires the shared Axios instance so requests carry the token and 401 responses
 * clear it. (Requirement 11.8)
 */
export const useAuthStore = defineStore('auth', () => {
  // Initialise from localStorage so the session survives a page reload.
  const token = ref(readPersistedToken())

  // The authenticated user's profile, hydrated from GET /api/settings after
  // login or on first authenticated load. Null when not yet hydrated.
  // Shape: { username, email, is_admin, plan, telegram_chat_id }.
  const user = ref(null)

  const isAuthenticated = computed(() => Boolean(token.value))
  const isAdmin = computed(() => Boolean(user.value && user.value.is_admin))

  /** Set (or clear) the token both in memory and in localStorage. */
  function setToken(newToken) {
    token.value = newToken || null
    persistToken(token.value)
    if (!token.value) {
      // Clearing the token also clears the cached profile.
      user.value = null
    }
  }

  /**
   * Hydrate the user profile from GET /api/settings.
   *
   * Populates `user` (including `is_admin` for the admin guard, Requirement
   * 22.5). Returns the profile, or null when the request fails (e.g. no token).
   */
  async function fetchProfile() {
    try {
      const { data } = await settingsApi.get()
      user.value = {
        username: data.username,
        email: data.email,
        is_admin: Boolean(data.is_admin),
        plan: data.plan,
        telegram_chat_id: data.telegram_chat_id,
      }
      return user.value
    } catch {
      user.value = null
      return null
    }
  }

  /**
   * Authenticate with the backend.
   *
   * POSTs credentials plus the Turnstile token to the login endpoint, stores
   * the issued token, and hydrates the user profile (Requirements 12.1, 22.5).
   * Returns the token on success; throws on failure so callers can show an
   * error and reset the Turnstile widget (Requirement 20.6).
   */
  async function login(username, password, turnstileToken) {
    const { data } = await api.post('/auth/login', {
      username,
      password,
      turnstile_token: turnstileToken,
    })
    setToken(data.access_token)
    await fetchProfile()
    return data.access_token
  }

  /**
   * Register a new account with Turnstile verification (Requirement 11).
   *
   * Does not log the user in; the caller routes to the login page on success.
   * Throws on failure (duplicate, turnstile, validation) so the form can show
   * the error and reset the widget (Requirement 20.6).
   */
  async function register(username, email, password, turnstileToken) {
    const { data } = await api.post('/auth/register', {
      username,
      email,
      password,
      turnstile_token: turnstileToken,
    })
    return data
  }

  /**
   * Establish a session from a token issued out-of-band (e.g. the Google
   * OAuth callback). Stores the token and hydrates the profile, mirroring
   * `login` but without a credential round-trip.
   */
  async function loginWithToken(token) {
    setToken(token)
    await fetchProfile()
    return token
  }

  /** Clear the held token and profile, logging the user out. */
  function logout() {
    setToken(null)
  }

  // Provide the current token to the Axios request interceptor and let the
  // response interceptor clear it on a 401. (Requirement 11.9 wiring)
  api.authTokenProvider = () => token.value
  api.onUnauthorized = () => {
    setToken(null)
  }

  return {
    token,
    user,
    isAuthenticated,
    isAdmin,
    setToken,
    fetchProfile,
    login,
    loginWithToken,
    register,
    logout,
  }
})

export default useAuthStore
