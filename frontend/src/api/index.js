import axios from 'axios'

// Base URL of the backend API. Defaults to the local FastAPI server; can be
// overridden at build time via the VITE_API_BASE_URL environment variable.
const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// Key used to persist the Auth_Token in localStorage. Kept in sync with the
// auth store (implemented in a later task).
export const TOKEN_STORAGE_KEY = 'uptime_guardian_token'

/**
 * Read the current Auth_Token.
 *
 * Prefers a token registered by the auth store at runtime, falling back to
 * localStorage so the token survives page reloads.
 */
function getToken() {
  if (api.authTokenProvider) {
    try {
      const fromStore = api.authTokenProvider()
      if (fromStore) return fromStore
    } catch {
      // Ignore provider errors and fall back to storage.
    }
  }
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

/**
 * Extract a human-readable message from an Axios/network error.
 *
 * Prefers the backend-provided `detail` field (string or FastAPI validation
 * array), then the Axios message, and finally a generic fallback so the UI
 * always has something to show.
 */
export function extractErrorMessage(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0]
    if (first && typeof first.msg === 'string' && first.msg) return first.msg
  }
  if (error?.message) return error.message
  return 'Request failed'
}

/** Clear the persisted Auth_Token. */
function clearToken() {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    // localStorage may be unavailable; nothing else to clean up here.
  }
}

const api = axios.create({
  baseURL: `${baseURL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor: attach `Authorization: Bearer <token>` when a token is
// held. (Requirement 11.9)
api.interceptors.request.use(
  (config) => {
    const token = getToken()
    if (token) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// Response interceptor: on a 401, clear the token and redirect to the login
// view so the user can re-authenticate (Requirement 11.9). For any other error
// status, surface it through the `onError` hook so the app can present an error
// indication (e.g. a toast) without the data layer importing UI code, which
// would create a circular dependency (mirrors the `onUnauthorized` pattern).
// A request can opt out by setting `skipErrorToast: true` in its config — used
// for non-fatal background aggregations (e.g. per-monitor stats polling).
// (Requirement 11.7)
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response && error.response.status
    if (status === 401) {
      clearToken()
      if (api.onUnauthorized) {
        // Allow the app to hook in router-based navigation.
        api.onUnauthorized()
      } else if (
        typeof window !== 'undefined' &&
        window.location &&
        window.location.pathname !== '/login'
      ) {
        window.location.assign('/login')
      }
    } else if (!error?.config?.skipErrorToast && api.onError) {
      api.onError(extractErrorMessage(error))
    }
    return Promise.reject(error)
  },
)

export default api

// ---------------------------------------------------------------------------
// Method groups for the multi-tenant SaaS API (Tasks 12.1).
//
// Each group reuses the shared `api` instance (Bearer interceptor + 401
// handling + error toasts). Paths are relative to the `/api` baseURL. Public
// endpoints (plans listing) work without a token; the rest require auth.
// ---------------------------------------------------------------------------

/** Public pricing/plans (no auth) — used by the landing page (Req 19.1). */
export const plansApi = {
  /** GET /api/plans → list of active plans (empty list if none). */
  list: () => api.get('/plans'),
}

/** Authenticated dashboard settings (Req 10, 21). */
export const settingsApi = {
  /** GET /api/settings → telegram id, active plan limits, usage, profile. */
  get: () => api.get('/settings'),
  /** PUT /api/settings/telegram → set/clear the Telegram chat id. */
  setTelegram: (telegramChatId) =>
    api.put('/settings/telegram', { telegram_chat_id: telegramChatId }),
}

/** SePay payments (Req 13, 21.5). */
export const paymentsApi = {
  /** POST /api/payments/initiate → pending tx + QR reference for a plan. */
  initiate: (planId) => api.post('/payments/initiate', { plan_id: planId }),
}

/** Administrative console operations (Req 17, 18). */
export const adminApi = {
  listPlans: () => api.get('/admin/plans'),
  createPlan: (payload) => api.post('/admin/plans', payload),
  updatePlan: (id, payload) => api.put(`/admin/plans/${id}`, payload),
  deletePlan: (id) => api.delete(`/admin/plans/${id}`),
  listUsers: () => api.get('/admin/users'),
  listTransactions: () => api.get('/admin/transactions'),
}
