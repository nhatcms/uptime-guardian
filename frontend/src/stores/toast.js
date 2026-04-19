import { defineStore } from 'pinia'
import { ref } from 'vue'

import api from '@/api'

// Default time a toast stays visible before auto-dismissing (ms).
const DEFAULT_TIMEOUT_MS = 5000

// Monotonic id source for toasts. Module-level so ids stay unique across the
// store's lifetime.
let nextId = 0

/**
 * Toast notification store.
 *
 * Holds a list of transient notifications surfaced to the user — primarily API
 * errors (Requirement 11.7) — and exposes actions to add and dismiss them.
 * Toasts auto-dismiss after a timeout and can be dismissed manually. Identical
 * messages are de-duplicated so background polling (which can fail repeatedly)
 * does not stack the same notification over and over.
 *
 * On creation the store registers `api.onError`, the hook the shared Axios
 * response interceptor calls for non-401 errors. Wiring it here (rather than
 * importing the store into the Axios module) avoids a circular import, mirroring
 * the existing `api.onUnauthorized` pattern.
 */
export const useToastStore = defineStore('toast', () => {
  // Active toasts. Each: { id, message, type: 'error' | 'success', timer }.
  const toasts = ref([])

  /** Remove a toast by id and clear its auto-dismiss timer. */
  function removeToast(id) {
    const index = toasts.value.findIndex((t) => t.id === id)
    if (index === -1) return
    const [removed] = toasts.value.splice(index, 1)
    if (removed && removed.timer) clearTimeout(removed.timer)
  }

  /**
   * Add a toast. Returns its id.
   *
   * @param {string} message - the text to display.
   * @param {{ type?: 'error' | 'success', timeout?: number }} [options]
   *   `timeout` of 0 (or less) keeps the toast until dismissed manually.
   */
  function addToast(message, options = {}) {
    const { type = 'error', timeout = DEFAULT_TIMEOUT_MS } = options
    const text =
      typeof message === 'string' && message ? message : 'Something went wrong'

    // De-duplicate: if an identical toast is already visible, just refresh its
    // auto-dismiss timer instead of stacking a duplicate.
    const existing = toasts.value.find(
      (t) => t.message === text && t.type === type,
    )
    if (existing) {
      if (existing.timer) clearTimeout(existing.timer)
      existing.timer =
        timeout > 0 ? setTimeout(() => removeToast(existing.id), timeout) : null
      return existing.id
    }

    const id = (nextId += 1)
    const toast = { id, message: text, type, timer: null }
    if (timeout > 0) {
      toast.timer = setTimeout(() => removeToast(id), timeout)
    }
    toasts.value.push(toast)
    return id
  }

  /** Convenience helper for error toasts. */
  function error(message, options = {}) {
    return addToast(message, { ...options, type: 'error' })
  }

  /** Convenience helper for success toasts. */
  function success(message, options = {}) {
    return addToast(message, { ...options, type: 'success' })
  }

  // Wire the Axios error hook so API errors surface as toasts. The interceptor
  // already extracts a human-readable message and skips 401s (handled by the
  // auth redirect) and requests flagged with `skipErrorToast`.
  api.onError = (message) => {
    error(message)
  }

  return {
    toasts,
    addToast,
    removeToast,
    error,
    success,
  }
})

export default useToastStore
