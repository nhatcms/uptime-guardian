<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import api from '@/api'
import AddMonitorModal from '@/components/AddMonitorModal.vue'
import EditMonitorModal from '@/components/EditMonitorModal.vue'
import MonitorCard from '@/components/MonitorCard.vue'
import SettingsPanel from '@/components/SettingsPanel.vue'
import { useAuthStore } from '@/stores/auth'
import { useMonitorsStore } from '@/stores/monitors'

// Dashboard view: the main landing screen after login.
//
// Responsibilities (Requirements 11.1, 11.3):
//  - Header with the app name, total monitor count, and a GLOBAL 24h uptime
//    percentage aggregated across all monitors.
//  - A responsive grid of MonitorCard, one per monitor.
//  - A floating "+" button that opens AddMonitorModal.
//  - On mount, load monitors and global uptime; then poll every 30 seconds to
//    refresh the data. The interval is cleared on unmount.
//  - Loading and error states are handled gracefully: errors surface a banner
//    while the last successfully loaded data is preserved (Requirement 11.7
//    spirit — the store keeps the previous `monitors` array on a failed fetch).
//  - A logout button in the header (optional per the task).
//
// ---------------------------------------------------------------------------
// Global 24h uptime approach
// ---------------------------------------------------------------------------
// The monitor list endpoint embeds only the single `latest` CheckResult per
// monitor, which is not enough to compute a 24h uptime. The backend exposes
// per-monitor aggregates at GET /api/results/stats?monitor_id=&hours=24, which
// return `uptime_percentage`, `total_checks`, and `failed_checks` over the
// window.
//
// To get a single GLOBAL figure we aggregate across monitors by CHECK COUNT
// (a check-weighted mean), which is equivalent to pooling every check from the
// last 24h and dividing the number of "up" checks by the total:
//
//   up_checks(monitor)    = total_checks - failed_checks
//   global_uptime         = (Σ up_checks / Σ total_checks) × 100
//
// This weights busier monitors proportionally rather than treating a monitor
// with 2 checks the same as one with 200, which best matches "global uptime
// over the last 24 hours". When no monitor has any checks in the window, the
// figure is reported as N/A. Per-monitor stats requests that fail are skipped
// so one bad request does not void the whole figure.

const POLL_INTERVAL_MS = 30_000
const UPTIME_WINDOW_HOURS = 24
// Number of skeleton cards rendered during the very first load.
const SKELETON_COUNT = 6

const monitorsStore = useMonitorsStore()
const auth = useAuthStore()
const router = useRouter()

// Toggles the inline settings/plan panel (Requirement 21).
const showSettings = ref(false)
const isAdmin = computed(() => auth.isAdmin)

// Global 24h uptime as a percentage (0–100), or null when it cannot be
// computed (no checks in the window yet).
const globalUptime = ref(null)
// Whether a refresh cycle is currently in flight (for subtle UI affordances).
const refreshing = ref(false)
// Controls AddMonitorModal visibility (v-model).
const showAddModal = ref(false)
// Controls EditMonitorModal visibility (v-model) and the monitor it edits.
const showEditModal = ref(false)
const monitorBeingEdited = ref(null)
// Holds the setInterval handle so it can be cleared on unmount.
let pollHandle = null

const monitors = computed(() => monitorsStore.monitors)
const monitorCount = computed(() => monitors.value.length)
const error = computed(() => monitorsStore.error)
// Show the full-screen loading state only on the very first load, before any
// data has arrived. Subsequent polls refresh quietly in the background.
const initialLoading = computed(
  () => monitorsStore.loading && monitors.value.length === 0,
)

// Formatted uptime label for the header, e.g. "99.95%" or "N/A".
const globalUptimeLabel = computed(() =>
  globalUptime.value == null ? 'N/A' : `${globalUptime.value.toFixed(2)}%`,
)

// Color the uptime figure by health: green when healthy, amber when degraded,
// red when poor, muted when unknown.
const uptimeColorClass = computed(() => {
  const value = globalUptime.value
  if (value == null) return 'text-slate-400'
  if (value >= 99) return 'text-up'
  if (value >= 95) return 'text-amber-400'
  return 'text-down'
})

/**
 * Compute the global 24h uptime by aggregating per-monitor stats.
 *
 * Fetches GET /api/results/stats for each monitor (hours=24) in parallel,
 * pools the check counts, and produces a single check-weighted percentage.
 * Individual failed requests are ignored so a transient error on one monitor
 * does not blank the whole figure. Sets `globalUptime` to null when there are
 * no checks in the window.
 */
async function computeGlobalUptime() {
  const list = monitors.value
  if (list.length === 0) {
    globalUptime.value = null
    return
  }

  const statsResults = await Promise.allSettled(
    list.map((m) =>
      api.get('/results/stats', {
        params: { monitor_id: m.id, hours: UPTIME_WINDOW_HOURS },
        // Non-fatal background aggregation: a failed stats request must not
        // raise an error toast (Requirement 11.7 — surface real errors, not
        // routine polling hiccups).
        skipErrorToast: true,
      }),
    ),
  )

  let totalChecks = 0
  let totalUp = 0
  for (const outcome of statsResults) {
    if (outcome.status !== 'fulfilled') continue
    const stats = outcome.value?.data
    if (!stats) continue
    const total = Number(stats.total_checks) || 0
    const failed = Number(stats.failed_checks) || 0
    if (total <= 0) continue
    totalChecks += total
    totalUp += Math.max(0, total - failed)
  }

  globalUptime.value =
    totalChecks > 0 ? (totalUp / totalChecks) * 100 : null
}

/**
 * Refresh all dashboard data: the monitor list plus the global uptime figure.
 *
 * Errors from `fetchMonitors` are swallowed here because the store already
 * records the message in `error` and preserves the last good `monitors` data;
 * the header/grid keep showing prior state while the banner surfaces the
 * problem (Requirement 11.7 spirit).
 */
async function refresh() {
  refreshing.value = true
  try {
    await monitorsStore.fetchMonitors()
    await computeGlobalUptime()
  } catch {
    // Error state is handled via the store's `error`; keep last good data.
  } finally {
    refreshing.value = false
  }
}

/** Open the add-monitor modal. */
function openAddModal() {
  showAddModal.value = true
}

/** Open the edit modal for a given monitor (from a card's edit button). */
function openEditModal(monitor) {
  monitorBeingEdited.value = monitor
  showEditModal.value = true
}

/** Refresh the global uptime after a monitor is edited or deleted. */
function onMonitorChanged() {
  computeGlobalUptime()
}

/** Refresh after a monitor is created so the new card and counts appear. */
function onMonitorCreated() {
  // The store's addMonitor already re-fetches the list; refresh the global
  // uptime to include the new monitor.
  computeGlobalUptime()
}

/** Log out and redirect to the login view. */
function logout() {
  auth.logout()
  router.push({ name: 'login' })
}

onMounted(() => {
  // Ensure the admin link/guard has the profile, then load data + poll.
  auth.fetchProfile()
  refresh()
  pollHandle = setInterval(refresh, POLL_INTERVAL_MS)
})

onUnmounted(() => {
  // Clear the interval so polling stops when the view is torn down.
  if (pollHandle != null) {
    clearInterval(pollHandle)
    pollHandle = null
  }
})
</script>

<template>
  <div class="min-h-screen bg-bg text-slate-100">
    <!-- Header (Requirement 11.1) -->
    <header class="border-b border-slate-800 bg-slate-900/40">
      <div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-5 sm:px-6">
        <div class="flex items-baseline gap-3">
          <h1 class="font-mono text-xl font-semibold tracking-tight text-up">
            Uptime Guardian
          </h1>
        </div>

        <div class="flex items-center gap-6">
          <!-- Monitor count -->
          <div class="text-right">
            <p class="text-xs uppercase tracking-wide text-slate-500">Monitors</p>
            <p class="font-mono text-lg font-semibold text-slate-100">
              {{ monitorCount }}
            </p>
          </div>

          <!-- Global 24h uptime -->
          <div class="text-right">
            <p class="text-xs uppercase tracking-wide text-slate-500">Uptime (24h)</p>
            <p class="font-mono text-lg font-semibold" :class="uptimeColorClass">
              {{ globalUptimeLabel }}
            </p>
          </div>

          <!-- Admin console link (only for admins) -->
          <router-link
            v-if="isAdmin"
            :to="{ name: 'admin' }"
            class="rounded-lg border border-slate-700 px-3 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-800"
          >
            Admin
          </router-link>

          <!-- Settings toggle -->
          <button
            type="button"
            class="rounded-lg border border-slate-700 px-3 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-800"
            @click="showSettings = !showSettings"
          >
            {{ showSettings ? 'Hide settings' : 'Settings' }}
          </button>

          <!-- Logout -->
          <button
            type="button"
            class="rounded-lg border border-slate-700 px-3 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-800"
            @click="logout"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-6xl px-4 py-6 sm:px-6">
      <!-- Settings / plan panel (Requirement 21) -->
      <div v-if="showSettings" class="mb-6">
        <SettingsPanel />
      </div>

      <!-- Error banner: shown while preserving the last loaded data -->
      <p
        v-if="error"
        role="alert"
        class="mb-5 rounded-lg border border-down/40 bg-down/10 px-4 py-3 text-sm text-down"
      >
        {{ error }}
      </p>

      <!-- Initial loading state: skeleton cards (only before any data) -->
      <div
        v-if="initialLoading"
        class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        <MonitorCard
          v-for="n in SKELETON_COUNT"
          :key="`skeleton-${n}`"
          skeleton
        />
      </div>

      <!-- Empty state -->
      <div
        v-else-if="monitorCount === 0"
        class="flex flex-col items-center justify-center gap-3 py-24 text-center"
      >
        <p class="text-slate-300">No monitors yet.</p>
        <p class="text-sm text-slate-500">
          Add your first monitor with the + button to start watching a site.
        </p>
      </div>

      <!-- Responsive grid of monitor cards -->
      <div
        v-else
        class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        <MonitorCard
          v-for="monitor in monitors"
          :key="monitor.id"
          :monitor="monitor"
          @edit="openEditModal"
        />
      </div>
    </main>

    <!-- Floating add button -->
    <button
      type="button"
      aria-label="Add monitor"
      class="fixed bottom-6 right-6 flex h-14 w-14 items-center justify-center rounded-full bg-up text-bg shadow-xl transition hover:bg-up/90 focus:outline-none focus:ring-2 focus:ring-up focus:ring-offset-2 focus:ring-offset-bg"
      @click="openAddModal"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        class="h-7 w-7"
        viewBox="0 0 20 20"
        fill="currentColor"
        aria-hidden="true"
      >
        <path
          fill-rule="evenodd"
          d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z"
          clip-rule="evenodd"
        />
      </svg>
    </button>

    <!-- Add monitor modal -->
    <AddMonitorModal v-model="showAddModal" @created="onMonitorCreated" />

    <!-- Edit / delete monitor modal -->
    <EditMonitorModal
      v-model="showEditModal"
      :monitor="monitorBeingEdited"
      @updated="onMonitorChanged"
      @deleted="onMonitorChanged"
    />
  </div>
</template>
