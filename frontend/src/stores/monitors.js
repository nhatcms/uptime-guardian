import { defineStore } from 'pinia'
import { ref } from 'vue'

import api from '@/api'

/**
 * Extract a human-readable message from an Axios/network error.
 *
 * Prefers the backend-provided `detail` field, then the Axios message, and
 * finally a generic fallback so the UI always has something to show.
 */
function errorMessage(err, fallback) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (err?.message) return err.message
  return fallback
}

/**
 * Monitors store: holds the list of monitors (each with its latest check result
 * embedded by the backend), a loading flag, and the last error message.
 *
 * Actions wrap the REST API exposed under `/api/monitors`. The shared Axios
 * instance already prefixes requests with `/api`, so paths here are relative to
 * that (e.g. `/monitors/`). The backend list route lives at `/api/monitors/`
 * (trailing slash), so it is used as-is to avoid a 307 redirect.
 *
 * Requirements: 1.3 (list with latest embedded), 1.1 (create), 1.7 (delete),
 * 4.5 (immediate check). On a failed refresh the previously loaded `monitors`
 * data is preserved so the dashboard keeps showing the last good state
 * (Requirement 11.7 spirit).
 */
export const useMonitorsStore = defineStore('monitors', () => {
  // Monitor list as returned by GET /api/monitors. Each entry is a
  // MonitorWithLatest: monitor fields (id, name, url, is_active,
  // check_interval_minutes, created_at, notify_on_failure) plus an embedded
  // `latest` CheckResult (or null when never checked).
  const monitors = ref([])
  const loading = ref(false)
  const error = ref(null)

  /**
   * Fetch all monitors with their latest check result embedded (Requirement
   * 1.3). On failure, sets `error` and PRESERVES the existing `monitors` data
   * so the UI can keep displaying the last successfully loaded state
   * (Requirement 11.7 spirit).
   */
  async function fetchMonitors() {
    loading.value = true
    error.value = null
    try {
      const { data } = await api.get('/monitors/')
      monitors.value = Array.isArray(data) ? data : []
    } catch (err) {
      // Preserve the last successfully loaded monitors; only record the error.
      error.value = errorMessage(err, 'Failed to load monitors')
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * Create a new monitor, then refresh the list (Requirement 1.1).
   *
   * @param {{name: string, url: string, check_interval_minutes?: number}} payload
   * @returns the created monitor as returned by the API.
   */
  async function addMonitor(payload) {
    error.value = null
    try {
      const { data } = await api.post('/monitors/', payload)
      await fetchMonitors()
      return data
    } catch (err) {
      error.value = errorMessage(err, 'Failed to add monitor')
      throw err
    }
  }

  /**
   * Update an existing monitor, then refresh the list (Requirement 1.6).
   *
   * Sends only the provided fields (PUT /api/monitors/{id} accepts a partial
   * MonitorUpdate where every field is optional). On success the list is
   * re-fetched so the embedded latest result and monitor fields stay in sync.
   *
   * @param {number} id
   * @param {{name?: string, url?: string, check_interval_minutes?: number, is_active?: boolean}} payload
   * @returns the updated monitor as returned by the API.
   */
  async function updateMonitor(id, payload) {
    error.value = null
    try {
      const { data } = await api.put(`/monitors/${id}`, payload)
      await fetchMonitors()
      return data
    } catch (err) {
      error.value = errorMessage(err, 'Failed to update monitor')
      throw err
    }
  }

  /**
   * Delete a monitor by id, then refresh the list (Requirement 1.7).
   *
   * Optimistically removes the monitor from local state on success so the UI
   * updates immediately, then re-fetches to stay consistent with the backend.
   */
  async function deleteMonitor(id) {
    error.value = null
    try {
      await api.delete(`/monitors/${id}`)
      monitors.value = monitors.value.filter((m) => m.id !== id)
      await fetchMonitors()
    } catch (err) {
      error.value = errorMessage(err, 'Failed to delete monitor')
      throw err
    }
  }

  /**
   * Trigger an immediate check for a monitor, then refresh the list so the
   * embedded latest result reflects the new check (Requirement 4.5).
   *
   * @returns the freshly persisted CheckResult as returned by the API.
   */
  async function triggerCheck(id) {
    error.value = null
    try {
      const { data } = await api.post(`/monitors/${id}/check-now`)
      await fetchMonitors()
      return data
    } catch (err) {
      error.value = errorMessage(err, 'Failed to trigger check')
      throw err
    }
  }

  return {
    monitors,
    loading,
    error,
    fetchMonitors,
    addMonitor,
    updateMonitor,
    deleteMonitor,
    triggerCheck,
  }
})

export default useMonitorsStore
