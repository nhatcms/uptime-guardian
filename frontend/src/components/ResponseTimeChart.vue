<script setup>
import { computed, ref } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js'

// ResponseTimeChart renders a line chart of response_time_ms over time for a
// monitor's recent CheckResult history (Requirement 11.5). The line is filled
// with an area gradient in the "up" brand color, and individual DOWN checks
// (is_up === false) are highlighted as red dots on the plotted line.
//
// X-axis choice: we deliberately use chart.js' CategoryScale with pre-formatted
// time strings as labels rather than a TimeScale. A TimeScale requires a date
// adapter dependency (e.g. chartjs-adapter-date-fns), which is not installed.
// Using a category axis keeps the dependency surface minimal while still giving
// a readable, time-ordered x-axis. The trade-off is that gaps between checks are
// not spaced proportionally to elapsed time — each check occupies one equal
// category slot. For monitoring on a fixed interval this is an acceptable and
// even desirable presentation.

ChartJS.register(
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
  Tooltip,
  Legend,
)

const props = defineProps({
  // Array of CheckResult objects:
  //   { checked_at, response_time_ms, is_up, status_code, ... }
  // Order is not assumed; the component sorts ascending by checked_at.
  results: {
    type: Array,
    default: () => [],
  },
})

// Dark-theme palette aligned with the Tailwind tokens (bg/up/down).
const UP_COLOR = '#00d4aa'
const DOWN_COLOR = '#ff4757'
const GRID_COLOR = 'rgba(148, 163, 184, 0.12)' // slate-400 @ low alpha
const TICK_COLOR = 'rgba(148, 163, 184, 0.85)' // slate-400
const TOOLTIP_BG = '#0a0f1e'

// Results ordered oldest -> newest for left-to-right plotting. We copy before
// sorting so the prop array is never mutated.
const ordered = computed(() => {
  return [...(props.results ?? [])]
    .filter((r) => r && r.checked_at != null)
    .sort((a, b) => new Date(a.checked_at) - new Date(b.checked_at))
})

const hasData = computed(() => ordered.value.length > 0)

// Format a timestamp into a compact HH:MM label for the category axis.
function formatTimeLabel(value) {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// Build an area gradient (up color, fading to transparent) under the line.
// vue-chartjs passes a scriptable context; we read the chart area to size the
// gradient. Returns a flat color until the chart area is laid out.
function buildGradient(ctx) {
  const { chart } = ctx
  const { ctx: canvasCtx, chartArea } = chart
  if (!chartArea) return 'rgba(0, 212, 170, 0.15)'
  const gradient = canvasCtx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom)
  gradient.addColorStop(0, 'rgba(0, 212, 170, 0.35)')
  gradient.addColorStop(1, 'rgba(0, 212, 170, 0.0)')
  return gradient
}

const chartData = computed(() => {
  const points = ordered.value.map((r) =>
    r.response_time_ms == null ? null : r.response_time_ms,
  )

  return {
    labels: ordered.value.map((r) => formatTimeLabel(r.checked_at)),
    datasets: [
      {
        label: 'Response time (ms)',
        data: points,
        borderColor: UP_COLOR,
        borderWidth: 2,
        tension: 0.3,
        spanGaps: true,
        fill: true,
        backgroundColor: buildGradient,
        // Per-point styling: DOWN checks become larger red dots, UP checks are
        // small up-colored dots that emphasize on hover.
        pointRadius: ordered.value.map((r) => (r.is_up === false ? 4 : 2)),
        pointHoverRadius: ordered.value.map((r) => (r.is_up === false ? 6 : 4)),
        pointBackgroundColor: ordered.value.map((r) =>
          r.is_up === false ? DOWN_COLOR : UP_COLOR,
        ),
        pointBorderColor: ordered.value.map((r) =>
          r.is_up === false ? DOWN_COLOR : UP_COLOR,
        ),
      },
    ],
  }
})

const chartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  interaction: {
    mode: 'index',
    intersect: false,
  },
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: TOOLTIP_BG,
      borderColor: 'rgba(148, 163, 184, 0.25)',
      borderWidth: 1,
      titleColor: '#e2e8f0', // slate-200
      bodyColor: '#cbd5e1', // slate-300
      padding: 10,
      callbacks: {
        // Annotate the tooltip with up/down state and status code.
        afterBody: (items) => {
          const idx = items?.[0]?.dataIndex
          if (idx == null) return ''
          const r = ordered.value[idx]
          if (!r) return ''
          const state = r.is_up === false ? 'DOWN' : 'UP'
          const code = r.status_code == null ? '—' : r.status_code
          return `Status: ${state} (${code})`
        },
      },
    },
  },
  scales: {
    x: {
      grid: { color: GRID_COLOR, drawTicks: false },
      border: { color: GRID_COLOR },
      ticks: {
        color: TICK_COLOR,
        maxRotation: 0,
        autoSkip: true,
        maxTicksLimit: 8,
        font: { family: '"JetBrains Mono", ui-monospace, monospace', size: 10 },
      },
    },
    y: {
      beginAtZero: true,
      grid: { color: GRID_COLOR, drawTicks: false },
      border: { color: GRID_COLOR },
      ticks: {
        color: TICK_COLOR,
        font: { family: '"JetBrains Mono", ui-monospace, monospace', size: 10 },
        callback: (value) => `${value} ms`,
      },
    },
  },
}))

// A stable-ish key so the canvas re-renders cleanly when the dataset changes.
const chartKey = computed(() => ordered.value.length)
const chartRef = ref(null)
</script>

<template>
  <div class="h-64 w-full rounded-xl border border-slate-800 bg-slate-900/40 p-4">
    <div
      v-if="!hasData"
      class="flex h-full w-full items-center justify-center text-sm text-slate-500"
    >
      No response-time data yet
    </div>
    <Line
      v-else
      ref="chartRef"
      :key="chartKey"
      :data="chartData"
      :options="chartOptions"
    />
  </div>
</template>
