<script setup>
import { computed } from 'vue'

// UptimeBar renders the 30 most recent check results as a row of small blocks,
// using three distinct visual states: up (green), down (red), and no-data
// (muted). Each block exposes a tooltip (native `title`) describing the status
// and timestamp. When fewer than 30 results are available, the bar is padded
// on the left (older side) with no-data blocks so the most recent result is
// always flush right. (Requirement 11.4)

const BLOCK_COUNT = 30

const props = defineProps({
  // Recent CheckResult records. Expected newest-first (the order the API's
  // results endpoint returns), but the component normalizes regardless: it
  // takes the most recent 30 and renders them oldest -> newest, left -> right.
  // Each result has the CheckResultOut shape: { is_up, status_code,
  // response_time_ms, checked_at, error_message, ... }.
  results: {
    type: Array,
    default: () => [],
  },
})

/**
 * Format a timestamp into a compact, locale-aware label for tooltips. Falls
 * back to the raw value if it cannot be parsed.
 */
function formatTime(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString()
}

/**
 * Build a human-readable tooltip for a single real result.
 */
function buildTooltip(result) {
  const status = result.is_up ? 'UP' : 'DOWN'
  const parts = [status]
  if (result.status_code != null) parts.push(`HTTP ${result.status_code}`)
  if (result.response_time_ms != null) {
    parts.push(`${Math.round(result.response_time_ms)} ms`)
  }
  if (!result.is_up && result.error_message) parts.push(result.error_message)
  const when = formatTime(result.checked_at)
  if (when) parts.push(when)
  return parts.join(' • ')
}

// The 30 blocks to render, oldest first. Real results occupy the rightmost
// slots; any shortfall is padded with no-data blocks on the left.
const blocks = computed(() => {
  const source = Array.isArray(props.results) ? props.results : []

  // Take the 30 most recent (input is newest-first) and reverse to oldest-first.
  const recent = source.slice(0, BLOCK_COUNT).reverse()

  const padCount = Math.max(0, BLOCK_COUNT - recent.length)
  const padding = Array.from({ length: padCount }, (_, i) => ({
    key: `nodata-${i}`,
    state: 'no-data',
    title: 'No data',
  }))

  const filled = recent.map((result, i) => ({
    key: result.id != null ? `r-${result.id}` : `r-${i}`,
    state: result.is_up ? 'up' : 'down',
    title: buildTooltip(result),
  }))

  return [...padding, ...filled]
})
</script>

<template>
  <div class="flex items-end gap-0.5" role="img" aria-label="Uptime history, last 30 checks">
    <span
      v-for="block in blocks"
      :key="block.key"
      :title="block.title"
      class="h-6 flex-1 rounded-sm transition-colors"
      :class="{
        'bg-up': block.state === 'up',
        'bg-down': block.state === 'down',
        'bg-slate-700/50': block.state === 'no-data',
      }"
    />
  </div>
</template>
