<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import api from '@/api'
import EditMonitorModal from '@/components/EditMonitorModal.vue'
import ResponseTimeChart from '@/components/ResponseTimeChart.vue'
import { useMonitorsStore } from '@/stores/monitors'

// MonitorDetail view: the per-monitor drill-down reached from a MonitorCard.
//
// Responsibilities (Requirements 11.5, 8.1, 8.2, 4.5):
//  - A back button that returns to the dashboard ('/').
//  - A monitor header showing the name, URL, and current up/down status
//    derived from the latest check result.
//  - A 24-hour statistics row: uptime percentage, average/min/max response
//    time, total checks, and failed checks (Requirement 8.2).
//  - A ResponseTimeChart fed with the recent check results.
//  - A table of the 50 most recent check results (Requirements 8.1, 11.5):
//    time, status, status code, response time, SSL, and error.
//  - A "Check Now" button that triggers an immediate check via the store
//    (Requirement 4.5) and refreshes the detail data and stats afterward.
//
// ---------------------------------------------------------------------------
// Data sources
// ---------------------------------------------------------------------------
//  - GET /api/monitors/{id} returns a MonitorDetail: the monitor fields, an
//    embedded `latest` CheckResult, and a `results` array of the 50 most
//    recent results (newest first).
//  - GET /api/results/stats?monitor_id={id}&hours=24 returns the 24h StatsOut
//    aggregate (uptime_percentage, avg/min/max response time, total_checks,
//    failed_checks).
//
// Loading and error states are handled gracefully; a 404 surfaces a dedicated
// "monitor not found" message rather than a generic error.

const STATS_WINDOW_HOURS = 24

const props = defineProps({
  // Monitor identifier injected by the router (route is declared with
  // `props: true`). Arrives as a string from the URL; coerced where needed.
  id: {
    type: [String, Number],
    required: true,
  },
})

const router = useRouter()
const monitorsStore = useMonitorsStore()

// The full MonitorDetail payload (monitor + latest + results), or null until
// the first successful load.
const monitor = ref(null)
// The 24h StatsOut aggregate, or null when unavailable / no checks in window.
const stats = ref(null)
// True only during the very first load, before any data has arrived.
const loading = ref(true)
// A human-readable error message, or null when there is no error.
const error = ref(null)
// True when the monitor id does not exist (HTTP 404).
const notFound = ref(false)
// True while a "Check Now" request (and the subsequent refresh) is in flight.
const checking = ref(false)
// Controls the edit/delete modal (v-model).
const showEditModal = ref(false)

// The recent check results (newest first), or an empty array before load.
const results = computed(() => monitor.value?.results ?? [])
// The latest check result, or null when the monitor has never been checked.
const latest = computed(() => monitor.value?.latest ?? null)

// Up/down/unknown status from the latest result (Requirement 11.5 header).
const status = computed(() => {
  if (!latest.value) return 'unknown'
  return latest.value.is_up ? 'up' : 'down'
})

const statusLabel = computed(() => {
  if (status.value === 'up') return 'UP'
  if (status.value === 'down') return 'DOWN'
  return 'N/A'
})

/**
 * Extract a readable message from an Axios/network error, preferring the
 * backend `detail` field.
 */
function errorMessage(err, fallback) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (err?.message) return err.message
  return fallback
}

/**
 * Fetch the monitor detail (monitor + latest + 50 recent results). Sets the
 * `notFound` flag on a 404 so the template can show a dedicated message.
 */
async function fetchMonitor() {
  try {
    const { data } = await api.get(`/monitors/${props.id}`, {
      // This view renders its own error / not-found UI and preserves the last
      // good monitor data, so suppress the global error toast to avoid a
      // redundant notification (Requirement 11.7).
      skipErrorToast: true,
    })
    monitor.value = data
    notFound.value = false
    return true
  } catch (err) {
    if (err?.response?.status === 404) {
      notFound.value = true
      monitor.value = null
    } else {
      // Preserve the last good monitor data; just record the message.
      error.value = errorMessage(err, 'Failed to load monitor')
    }
    return false
  }
}

/**
 * Fetch the 24h statistics aggregate. A failure here is non-fatal: the stats
 * row simply shows placeholders while the rest of the view keeps working.
 */
async function fetchStats() {
  try {
    const { data } = await api.get('/results/stats', {
      params: { monitor_id: props.id, hours: STATS_WINDOW_HOURS },
      // Non-fatal: failures here leave the last known stats in place, so do not
      // raise an error toast for them (Requirement 11.7).
      skipErrorToast: true,
    })
    stats.value = data
  } catch {
    // Non-fatal: leave the last known stats (or null) in place.
    stats.value = stats.value ?? null
  }
}

/**
 * Refresh both the monitor detail and the 24h stats in parallel.
 */
async function refresh() {
  error.value = null
  const ok = await fetchMonitor()
  // Only fetch stats when the monitor exists.
  if (ok) await fetchStats()
}

/**
 * Trigger an immediate check via the store (Requirement 4.5), then refresh the
 * detail data and stats so the new result is reflected.
 */
async function checkNow() {
  if (checking.value) return
  checking.value = true
  error.value = null
  try {
    await monitorsStore.triggerCheck(props.id)
    await refresh()
  } catch (err) {
    error.value = errorMessage(err, 'Failed to trigger check')
  } finally {
    checking.value = false
  }
}

/** Navigate back to the dashboard. */
function goBack() {
  router.push('/')
}

/** Open the edit/delete modal. */
function openEditModal() {
  showEditModal.value = true
}

/** Reload the detail data after the monitor is edited. */
function onMonitorUpdated() {
  refresh()
}

/** After deletion the monitor no longer exists, so return to the dashboard. */
function onMonitorDeleted() {
  router.push('/')
}

// --- Formatting helpers -----------------------------------------------------

/** Format a timestamp as a compact locale string; falls back to the raw value. */
function formatTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString()
}

/** Round a response time to whole milliseconds, or '—' when unavailable. */
function formatMs(value) {
  return value == null ? '—' : `${Math.round(value)} ms`
}

/** Format a percentage to two decimals, or 'N/A' when unavailable. */
function formatPercent(value) {
  return value == null ? 'N/A' : `${Number(value).toFixed(2)}%`
}

/** SSL cell text for a single result row. */
function sslText(result) {
  if (result.ssl_valid == null) return 'N/A'
  if (result.ssl_valid) {
    const days = result.ssl_days_remaining
    return days == null ? 'Valid' : `Valid (${days}d)`
  }
  return 'Invalid'
}

onMounted(async () => {
  loading.value = true
  await refresh()
  loading.value = false
})
</script>

<template>
  <div class="min-h-screen bg-bg text-slate-100">
    <!-- Header bar with back button and Check Now -->
    <header class="border-b border-slate-800 bg-slate-900/40">
      <div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-5 sm:px-6">
        <button
          type="button"
          class="flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-800"
          @click="goBack"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            class="h-4 w-4"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fill-rule="evenodd"
              d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z"
              clip-rule="evenodd"
            />
          </svg>
          Back
        </button>

        <div v-if="monitor" class="flex items-center gap-3">
          <button
            type="button"
            class="rounded-lg border border-slate-700 px-4 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-800"
            @click="openEditModal"
          >
            Edit
          </button>
          <button
            type="button"
            class="rounded-lg bg-up px-4 py-2 text-sm font-semibold text-bg transition hover:bg-up/90 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="checking"
            @click="checkNow"
          >
            {{ checking ? 'Checking…' : 'Check Now' }}
          </button>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-6xl px-4 py-6 sm:px-6">
      <!-- Error banner: shown while preserving the last loaded data -->
      <p
        v-if="error"
        role="alert"
        class="mb-5 rounded-lg border border-down/40 bg-down/10 px-4 py-3 text-sm text-down"
      >
        {{ error }}
      </p>

      <!-- Initial loading state -->
      <div
        v-if="loading"
        class="flex items-center justify-center py-24 text-slate-500"
      >
        <span class="font-mono text-sm">Loading monitor…</span>
      </div>

      <!-- Not found (404) -->
      <div
        v-else-if="notFound"
        class="flex flex-col items-center justify-center gap-3 py-24 text-center"
      >
        <p class="text-lg text-slate-200">Monitor not found</p>
        <p class="text-sm text-slate-500">
          This monitor may have been deleted. Head back to the dashboard.
        </p>
        <button
          type="button"
          class="mt-2 rounded-lg border border-slate-700 px-4 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-800"
          @click="goBack"
        >
          Back to dashboard
        </button>
      </div>

      <!-- Loaded monitor detail -->
      <template v-else-if="monitor">
        <!-- Monitor header: name, URL, status -->
        <section class="mb-6 flex flex-wrap items-start justify-between gap-4">
          <div class="min-w-0">
            <h1 class="truncate text-2xl font-semibold text-slate-100">
              {{ monitor.name }}
            </h1>
            <a
              :href="monitor.url"
              target="_blank"
              rel="noopener noreferrer"
              class="mt-1 block truncate font-mono text-sm text-slate-400 hover:text-up"
            >
              {{ monitor.url }}
            </a>
          </div>
          <span
            class="shrink-0 rounded-full px-3 py-1 text-sm font-semibold"
            :class="{
              'bg-up/15 text-up': status === 'up',
              'bg-down/15 text-down': status === 'down',
              'bg-slate-700/40 text-slate-400': status === 'unknown',
            }"
          >
            {{ statusLabel }}
          </span>
        </section>

        <!-- 24h statistics row (Requirement 8.2) -->
        <section class="mb-6">
          <h2 class="mb-3 text-xs uppercase tracking-wide text-slate-500">
            Last 24 hours
          </h2>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <div class="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Uptime</p>
              <p class="mt-1 font-mono text-lg font-semibold text-slate-100">
                {{ formatPercent(stats?.uptime_percentage) }}
              </p>
            </div>
            <div class="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Avg response</p>
              <p class="mt-1 font-mono text-lg font-semibold text-slate-100">
                {{ formatMs(stats?.avg_response_time_ms) }}
              </p>
            </div>
            <div class="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Min response</p>
              <p class="mt-1 font-mono text-lg font-semibold text-slate-100">
                {{ formatMs(stats?.min_response_time_ms) }}
              </p>
            </div>
            <div class="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Max response</p>
              <p class="mt-1 font-mono text-lg font-semibold text-slate-100">
                {{ formatMs(stats?.max_response_time_ms) }}
              </p>
            </div>
            <div class="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Total checks</p>
              <p class="mt-1 font-mono text-lg font-semibold text-slate-100">
                {{ stats?.total_checks ?? '—' }}
              </p>
            </div>
            <div class="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Failed checks</p>
              <p
                class="mt-1 font-mono text-lg font-semibold"
                :class="stats?.failed_checks ? 'text-down' : 'text-slate-100'"
              >
                {{ stats?.failed_checks ?? '—' }}
              </p>
            </div>
          </div>
        </section>

        <!-- Response time chart -->
        <section class="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <h2 class="mb-3 text-xs uppercase tracking-wide text-slate-500">
            Response time
          </h2>
          <ResponseTimeChart :results="results" />
        </section>

        <!-- Recent results table (Requirements 8.1, 11.5) -->
        <section class="rounded-xl border border-slate-800 bg-slate-900/40">
          <h2 class="border-b border-slate-800 px-4 py-3 text-xs uppercase tracking-wide text-slate-500">
            Recent checks (last 50)
          </h2>

          <div v-if="results.length === 0" class="px-4 py-10 text-center text-sm text-slate-500">
            No check results yet.
          </div>

          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-sm">
              <thead>
                <tr class="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                  <th class="px-4 py-2 font-medium">Time</th>
                  <th class="px-4 py-2 font-medium">Status</th>
                  <th class="px-4 py-2 font-medium">Code</th>
                  <th class="px-4 py-2 font-medium">Response</th>
                  <th class="px-4 py-2 font-medium">SSL</th>
                  <th class="px-4 py-2 font-medium">Error</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="result in results"
                  :key="result.id"
                  class="border-b border-slate-800/60 last:border-0"
                >
                  <td class="whitespace-nowrap px-4 py-2 font-mono text-xs text-slate-300">
                    {{ formatTime(result.checked_at) }}
                  </td>
                  <td class="px-4 py-2">
                    <span
                      class="rounded-full px-2 py-0.5 text-xs font-semibold"
                      :class="result.is_up ? 'bg-up/15 text-up' : 'bg-down/15 text-down'"
                    >
                      {{ result.is_up ? 'UP' : 'DOWN' }}
                    </span>
                  </td>
                  <td class="px-4 py-2 font-mono text-slate-300">
                    {{ result.status_code ?? '—' }}
                  </td>
                  <td class="px-4 py-2 font-mono text-slate-300">
                    {{ formatMs(result.response_time_ms) }}
                  </td>
                  <td class="px-4 py-2 font-mono text-slate-300">
                    {{ sslText(result) }}
                  </td>
                  <td class="max-w-xs truncate px-4 py-2 text-xs text-slate-400" :title="result.error_message || ''">
                    {{ result.error_message || '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </main>

    <!-- Edit / delete monitor modal -->
    <EditMonitorModal
      v-model="showEditModal"
      :monitor="monitor"
      @updated="onMonitorUpdated"
      @deleted="onMonitorDeleted"
    />
  </div>
</template>
