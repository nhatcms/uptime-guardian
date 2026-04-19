<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import UptimeBar from '@/components/UptimeBar.vue'

// MonitorCard summarizes a single monitor: name, URL, an up/down status badge
// derived from the latest check result, current response time, SSL status, and
// an inline UptimeBar of recent history. Selecting the card navigates to the
// monitor detail view. (Requirements 11.2, 11.4, 11.5)
//
// Data assumption: the dashboard list endpoint (GET /api/monitors) returns each
// monitor as a MonitorWithLatest, i.e. a SINGLE embedded `latest` CheckResult
// rather than a list of recent results. To keep the card usable in both
// contexts, it accepts an OPTIONAL `results` prop with the recent history; when
// that is not supplied it falls back to `monitor.recent_results` (if a caller
// provides one) and finally to the single `latest` result. The UptimeBar pads
// any shortfall with no-data blocks, so a card with only `latest` shows one
// real block plus 29 no-data blocks.

const router = useRouter()

const props = defineProps({
  // A MonitorWithLatest object: monitor fields plus an embedded `latest`
  // CheckResult (or null when never checked). Not required when `skeleton` is
  // true, since a skeleton card renders placeholders rather than real data.
  monitor: {
    type: Object,
    required: false,
    default: null,
  },
  // Optional recent CheckResult history (newest-first) for the uptime bar.
  results: {
    type: Array,
    default: null,
  },
  // When true, render a loading placeholder instead of real monitor data.
  // Used by the dashboard while the initial fetch is in flight (Requirement
  // 11.7 — show a loading state without discarding any prior data).
  skeleton: {
    type: Boolean,
    default: false,
  },
})

// `edit` is emitted (with the monitor) when the inline edit button is clicked,
// so a parent can open the edit/delete modal (Requirements 1.6, 1.7). The click
// is stopped from bubbling so it does not also navigate to the detail view.
const emit = defineEmits(['edit'])

function onEdit() {
  emit('edit', props.monitor)
}

// The latest check result, or null if the monitor has never been checked.
const latest = computed(() => props.monitor?.latest ?? null)

// Up/down/unknown derived from the latest result (Requirement 11.2). "unknown"
// covers a monitor that has no check result yet.
const status = computed(() => {
  if (!latest.value) return 'unknown'
  return latest.value.is_up ? 'up' : 'down'
})

const statusLabel = computed(() => {
  if (status.value === 'up') return 'UP'
  if (status.value === 'down') return 'DOWN'
  return 'N/A'
})

// Current response time in ms, rounded; null when unavailable (e.g. connection
// failure or never checked).
const responseTime = computed(() => {
  const ms = latest.value?.response_time_ms
  return ms == null ? null : Math.round(ms)
})

// SSL status text (Requirement 11.2):
//  - null ssl_valid  => non-HTTPS monitor => "N/A"
//  - ssl_valid true  => "Valid (Nd)" with days remaining when known
//  - ssl_valid false => "Invalid"
const sslStatus = computed(() => {
  const result = latest.value
  if (!result || result.ssl_valid == null) return { text: 'N/A', state: 'na' }
  if (result.ssl_valid) {
    const days = result.ssl_days_remaining
    const text = days == null ? 'Valid' : `Valid (${days}d)`
    // Flag certificates close to expiry (matches the 14-day warning threshold).
    return { text, state: days != null && days < 14 ? 'warn' : 'ok' }
  }
  return { text: 'Invalid', state: 'bad' }
})

// Results feeding the uptime bar, with graceful fallbacks (see assumption note
// above). Newest-first ordering is preserved for UptimeBar to normalize.
const barResults = computed(() => {
  if (Array.isArray(props.results)) return props.results
  if (Array.isArray(props.monitor?.recent_results)) return props.monitor.recent_results
  return latest.value ? [latest.value] : []
})

function goToDetail() {
  router.push({ name: 'monitor-detail', params: { id: props.monitor.id } })
}

function onKeydown(event) {
  // Activate on Enter or Space for keyboard accessibility.
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    goToDetail()
  }
}
</script>

<template>
  <!-- Skeleton placeholder shown while monitor data is loading -->
  <div
    v-if="skeleton"
    class="rounded-xl border border-slate-800 bg-slate-900/40 p-4 shadow-lg"
    aria-hidden="true"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0 flex-1 space-y-2">
        <div class="h-4 w-1/2 animate-pulse rounded bg-slate-700/60" />
        <div class="h-3 w-3/4 animate-pulse rounded bg-slate-800" />
      </div>
      <div class="h-6 w-12 shrink-0 animate-pulse rounded-full bg-slate-700/60" />
    </div>

    <div class="mt-4 flex items-center justify-between">
      <div class="h-3 w-20 animate-pulse rounded bg-slate-800" />
      <div class="h-3 w-16 animate-pulse rounded bg-slate-800" />
    </div>

    <div class="mt-4 flex items-end gap-0.5">
      <span
        v-for="n in 30"
        :key="n"
        class="h-6 flex-1 animate-pulse rounded-sm bg-slate-700/40"
      />
    </div>
  </div>

  <article
    v-else
    role="button"
    tabindex="0"
    class="cursor-pointer rounded-xl border border-slate-800 bg-slate-900/40 p-4 shadow-lg outline-none transition hover:border-slate-600 focus:border-up focus:ring-1 focus:ring-up"
    @click="goToDetail"
    @keydown="onKeydown"
  >
    <!-- Header: name + status badge -->
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <h3 class="truncate font-medium text-slate-100">{{ monitor.name }}</h3>
        <p class="mt-0.5 truncate font-mono text-xs text-slate-400">{{ monitor.url }}</p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <span
          class="rounded-full px-2.5 py-1 text-xs font-semibold"
          :class="{
            'bg-up/15 text-up': status === 'up',
            'bg-down/15 text-down': status === 'down',
            'bg-slate-700/40 text-slate-400': status === 'unknown',
          }"
        >
          {{ statusLabel }}
        </span>
        <button
          type="button"
          aria-label="Edit monitor"
          title="Edit monitor"
          class="rounded-md p-1 text-slate-500 transition hover:bg-slate-800 hover:text-slate-200 focus:outline-none focus:ring-1 focus:ring-up"
          @click.stop="onEdit"
          @keydown.enter.stop
          @keydown.space.stop
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            class="h-4 w-4"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"
            />
          </svg>
        </button>
      </div>
    </div>

    <!-- Metrics row: response time + SSL status -->
    <div class="mt-4 flex items-center justify-between text-sm">
      <div class="flex items-center gap-1.5">
        <span class="text-slate-500">Response</span>
        <span class="font-mono text-slate-200">
          {{ responseTime == null ? '—' : `${responseTime} ms` }}
        </span>
      </div>
      <div class="flex items-center gap-1.5">
        <span class="text-slate-500">SSL</span>
        <span
          class="font-mono"
          :class="{
            'text-up': sslStatus.state === 'ok',
            'text-amber-400': sslStatus.state === 'warn',
            'text-down': sslStatus.state === 'bad',
            'text-slate-400': sslStatus.state === 'na',
          }"
        >
          {{ sslStatus.text }}
        </span>
      </div>
    </div>

    <!-- Inline uptime bar (last 30 checks) -->
    <div class="mt-4">
      <UptimeBar :results="barResults" />
    </div>
  </article>
</template>
