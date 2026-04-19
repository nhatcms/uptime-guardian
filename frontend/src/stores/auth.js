import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import api, { TOKEN_STORAGE_KEY } from '@/api'

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

  const isAuthenticated = computed(() => Boolean(token.value))

  /** Set (or clear) the token both in memory and in localStorage. */
  function setToken(newToken) {
    token.value = newToken || null
    persistToken(token.value)
  }

  /**
   * Authenticate with the backend.
   *
   * POSTs the credentials to the login endpoint via the shared Axios instance
   * (whose baseURL already includes `/api`) and stores the returned token.
   * Returns the token on success; throws on failure so callers can show an
   * error.
   */
  async function login(username, password) {
    const { data } = await api.post('/auth/login', { username, password })
    setToken(data.access_token)
    return data.access_token
  }

  /** Clear the held token, logging the user out. */
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
    isAuthenticated,
    setToken,
    login,
    logout,
  }
})

export default useAuthStore
