<script setup>
import { computed } from 'vue'

// A single pricing card (Requirement 19.1): plan name, price, billing period,
// and the included-feature list derived from the plan's limits.
const props = defineProps({
  plan: { type: Object, required: true },
  // When true, render a primary call-to-action button that emits `select`.
  selectable: { type: Boolean, default: false },
  ctaLabel: { type: String, default: 'Choose plan' },
})
const emit = defineEmits(['select'])

const isFree = computed(() => Number(props.plan.price) === 0)

const priceLabel = computed(() => {
  const value = Number(props.plan.price)
  if (Number.isNaN(value)) return String(props.plan.price)
  // Whole numbers render without decimals (VND-style amounts).
  return value === Math.trunc(value) ? value.toLocaleString() : value.toFixed(2)
})

const billingPeriod = computed(() => {
  if (isFree.value) return 'free forever'
  const days = Number(props.plan.duration_days) || 0
  return days > 0 ? `per ${days} days` : 'one-time'
})

const features = computed(() => {
  const p = props.plan
  return [
    `${p.max_monitors} monitor${p.max_monitors === 1 ? '' : 's'}`,
    `Checks every ${p.min_interval_minutes} min or slower`,
    p.ssl_check_enabled ? 'SSL certificate monitoring' : 'No SSL monitoring',
  ]
})
</script>

<template>
  <div
    class="flex flex-col rounded-2xl border border-slate-800 bg-slate-900/40 p-6 shadow-lg"
    data-testid="plan-card"
  >
    <h3 class="font-mono text-lg font-semibold text-up">{{ plan.name }}</h3>

    <div class="mt-3 flex items-baseline gap-1">
      <span class="text-3xl font-bold text-slate-100">
        <span v-if="!isFree" class="text-base align-top">₫</span>{{ priceLabel }}
      </span>
      <span class="text-sm text-slate-500">{{ billingPeriod }}</span>
    </div>

    <ul class="mt-5 flex-1 space-y-2 text-sm text-slate-300">
      <li v-for="feature in features" :key="feature" class="flex items-start gap-2">
        <span class="text-up">✓</span>
        <span>{{ feature }}</span>
      </li>
    </ul>

    <button
      v-if="selectable"
      type="button"
      class="mt-6 w-full rounded-lg bg-up px-4 py-2 font-medium text-bg transition hover:bg-up/90"
      @click="emit('select', plan)"
    >
      {{ ctaLabel }}
    </button>
  </div>
</template>
