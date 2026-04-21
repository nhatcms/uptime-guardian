<script setup>
import { reactive, watch } from 'vue'

// Plan create/update form (Requirement 22.1). Emits `save` with a payload the
// parent sends to the admin API, and `cancel` to leave edit mode. When `plan`
// is provided the form pre-fills for editing; otherwise it creates a new plan.
const props = defineProps({
  plan: { type: Object, default: null },
})
const emit = defineEmits(['save', 'cancel'])

const form = reactive({
  name: '',
  price: '0',
  max_monitors: 1,
  min_interval_minutes: 5,
  ssl_check_enabled: false,
  duration_days: 30,
})

function fill(plan) {
  if (plan) {
    form.name = plan.name
    form.price = String(plan.price)
    form.max_monitors = plan.max_monitors
    form.min_interval_minutes = plan.min_interval_minutes
    form.ssl_check_enabled = Boolean(plan.ssl_check_enabled)
    form.duration_days = plan.duration_days
  } else {
    form.name = ''
    form.price = '0'
    form.max_monitors = 1
    form.min_interval_minutes = 5
    form.ssl_check_enabled = false
    form.duration_days = 30
  }
}

watch(() => props.plan, fill, { immediate: true })

function submit() {
  emit('save', {
    name: form.name,
    price: String(form.price),
    max_monitors: Number(form.max_monitors),
    min_interval_minutes: Number(form.min_interval_minutes),
    ssl_check_enabled: Boolean(form.ssl_check_enabled),
    duration_days: Number(form.duration_days),
  })
}
</script>

<template>
  <form
    class="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-6"
    data-testid="plan-form"
    novalidate
    @submit.prevent="submit"
  >
    <h3 class="text-base font-semibold text-slate-100">
      {{ plan ? `Edit plan: ${plan.name}` : 'Create a plan' }}
    </h3>

    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <label class="block text-sm">
        <span class="mb-1 block text-slate-400">Name</span>
        <input
          v-model="form.name"
          type="text"
          class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100"
        />
      </label>
      <label class="block text-sm">
        <span class="mb-1 block text-slate-400">Price</span>
        <input
          v-model="form.price"
          type="number"
          step="0.01"
          class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100"
        />
      </label>
      <label class="block text-sm">
        <span class="mb-1 block text-slate-400">Max monitors</span>
        <input
          v-model.number="form.max_monitors"
          type="number"
          class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100"
        />
      </label>
      <label class="block text-sm">
        <span class="mb-1 block text-slate-400">Min interval (min)</span>
        <input
          v-model.number="form.min_interval_minutes"
          type="number"
          class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100"
        />
      </label>
      <label class="block text-sm">
        <span class="mb-1 block text-slate-400">Duration (days)</span>
        <input
          v-model.number="form.duration_days"
          type="number"
          class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100"
        />
      </label>
      <label class="flex items-center gap-2 text-sm text-slate-300">
        <input v-model="form.ssl_check_enabled" type="checkbox" class="h-4 w-4" />
        SSL checking enabled
      </label>
    </div>

    <div class="flex gap-2">
      <button
        type="submit"
        class="rounded-lg bg-up px-4 py-2 font-medium text-bg transition hover:bg-up/90"
      >
        {{ plan ? 'Save changes' : 'Create plan' }}
      </button>
      <button
        v-if="plan"
        type="button"
        class="rounded-lg border border-slate-700 px-4 py-2 text-slate-300 transition hover:bg-slate-800"
        @click="emit('cancel')"
      >
        Cancel
      </button>
    </div>
  </form>
</template>
