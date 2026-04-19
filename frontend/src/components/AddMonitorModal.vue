<script setup>
import { computed, ref, watch } from 'vue'

import { useMonitorsStore } from '@/stores/monitors'

/**
 * AddMonitorModal — a dark-theme modal dialog for creating a new Monitor.
 *
 * Component contract
 * ------------------
 * Props:
 *   - `modelValue` (Boolean, default false): controls visibility. Designed for
 *     `v-model` so a parent (e.g. Dashboard, task 14.2) can open/close it:
 *         <AddMonitorModal v-model="showAddModal" />
 *
 * Emits:
 *   - `update:modelValue` (Boolean): paired with `modelValue` for `v-model`.
 *     Emitted with `false` whenever the modal requests to close.
 *   - `close`: emitted whenever the modal closes (cancel, backdrop/Escape, or
 *     after a successful create). Lets parents that prefer explicit events
 *     react without using v-model.
 *   - `created` (Monitor): emitted with the created monitor object after a
 *     successful POST, in case the parent wants to react (the store already
 *     refreshes the list itself).
 *
 * Behavior:
 *   - Form fields: name (text), url (validated http/https), and an interval
 *     dropdown with options 5/10/15/30 minutes.
 *   - Client-side URL validation shows an inline error for malformed URLs.
 *   - On submit, calls the monitors store `addMonitor`, which POSTs to
 *     `/api/monitors` and refreshes the list on success (Requirements 11.6,
 *     1.1). On success the modal closes; on failure an error is shown and the
 *     modal stays open so the user can retry.
 *   - Submit button shows a loading/disabled state while the request is in
 *     flight.
 */

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue', 'close', 'created'])

const monitors = useMonitorsStore()

// Allowed polling intervals (minutes) per design: 5/10/15/30.
const INTERVAL_OPTIONS = [5, 10, 15, 30]

const name = ref('')
const url = ref('')
const interval = ref(5)

// `urlError` holds a client-side validation message; `submitError` holds a
// server/network failure message surfaced after a failed POST.
const urlTouched = ref(false)
const submitError = ref('')
const submitting = ref(false)

/**
 * Validate that `value` is a well-formed absolute http/https URL. Uses the
 * platform URL parser and then constrains the scheme so values like
 * "ftp://x" or "javascript:..." are rejected.
 */
function isValidHttpUrl(value) {
  const trimmed = (value || '').trim()
  if (!trimmed) return false
  let parsed
  try {
    parsed = new URL(trimmed)
  } catch {
    return false
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false
  // Require a host (the URL parser accepts e.g. "http:" with empty host).
  return Boolean(parsed.hostname)
}

const urlError = computed(() => {
  // Only surface the inline error once the user has interacted with the field.
  if (!urlTouched.value) return ''
  if (!url.value.trim()) return 'URL is required.'
  if (!isValidHttpUrl(url.value)) {
    return 'Enter a valid http or https URL (e.g. https://example.com).'
  }
  return ''
})

const nameValid = computed(() => Boolean(name.value.trim()))
const canSubmit = computed(
  () => nameValid.value && isValidHttpUrl(url.value) && !submitting.value,
)

/** Reset all fields and transient state back to defaults. */
function resetForm() {
  name.value = ''
  url.value = ''
  interval.value = 5
  urlTouched.value = false
  submitError.value = ''
  submitting.value = false
}

/** Request close: clears the form, emits v-model false plus `close`. */
function close() {
  resetForm()
  emit('update:modelValue', false)
  emit('close')
}

async function handleSubmit() {
  // Mark touched so validation messages render if the user submits early.
  urlTouched.value = true
  submitError.value = ''

  if (!canSubmit.value) return

  submitting.value = true
  try {
    const created = await monitors.addMonitor({
      name: name.value.trim(),
      url: url.value.trim(),
      check_interval_minutes: interval.value,
    })
    // Store has already refreshed the list (Requirements 11.6, 1.1).
    emit('created', created)
    close()
  } catch (err) {
    // Prefer a backend-provided detail message, then a generic fallback.
    const detail = err?.response?.data?.detail
    submitError.value =
      (typeof detail === 'string' && detail) ||
      err?.message ||
      'Failed to add monitor. Please try again.'
  } finally {
    submitting.value = false
  }
}

// When the modal is opened, start from a clean slate.
watch(
  () => props.modelValue,
  (visible) => {
    if (visible) resetForm()
  },
)
</script>

<template>
  <div
    v-if="modelValue"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="add-monitor-title"
    @click.self="close"
    @keydown.esc="close"
  >
    <div class="w-full max-w-md rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
      <div class="mb-5 flex items-center justify-between">
        <h2 id="add-monitor-title" class="font-mono text-lg font-semibold text-slate-100">
          Add monitor
        </h2>
        <button
          type="button"
          aria-label="Close"
          class="rounded-md p-1 text-slate-400 transition hover:text-slate-200"
          @click="close"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            class="h-5 w-5"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fill-rule="evenodd"
              d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
              clip-rule="evenodd"
            />
          </svg>
        </button>
      </div>

      <form class="space-y-4" novalidate @submit.prevent="handleSubmit">
        <div>
          <label for="monitor-name" class="mb-1.5 block text-sm font-medium text-slate-300">
            Name
          </label>
          <input
            id="monitor-name"
            v-model="name"
            type="text"
            name="name"
            :disabled="submitting"
            class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 placeholder-slate-500 outline-none transition focus:border-up focus:ring-1 focus:ring-up disabled:opacity-60"
            placeholder="My website"
          />
        </div>

        <div>
          <label for="monitor-url" class="mb-1.5 block text-sm font-medium text-slate-300">
            URL
          </label>
          <input
            id="monitor-url"
            v-model="url"
            type="url"
            name="url"
            inputmode="url"
            autocomplete="off"
            :disabled="submitting"
            :aria-invalid="Boolean(urlError)"
            aria-describedby="monitor-url-error"
            class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 placeholder-slate-500 outline-none transition focus:border-up focus:ring-1 focus:ring-up disabled:opacity-60"
            :class="urlError ? 'border-down focus:border-down focus:ring-down' : ''"
            placeholder="https://example.com"
            @blur="urlTouched = true"
          />
          <p
            v-if="urlError"
            id="monitor-url-error"
            role="alert"
            class="mt-1.5 text-sm text-down"
          >
            {{ urlError }}
          </p>
        </div>

        <div>
          <label for="monitor-interval" class="mb-1.5 block text-sm font-medium text-slate-300">
            Check interval (minutes)
          </label>
          <select
            id="monitor-interval"
            v-model.number="interval"
            name="check_interval_minutes"
            :disabled="submitting"
            class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 outline-none transition focus:border-up focus:ring-1 focus:ring-up disabled:opacity-60"
          >
            <option v-for="opt in INTERVAL_OPTIONS" :key="opt" :value="opt">
              {{ opt }}
            </option>
          </select>
        </div>

        <p
          v-if="submitError"
          role="alert"
          class="rounded-lg border border-down/40 bg-down/10 px-3 py-2 text-sm text-down"
        >
          {{ submitError }}
        </p>

        <div class="flex justify-end gap-3 pt-2">
          <button
            type="button"
            :disabled="submitting"
            class="rounded-lg border border-slate-700 px-4 py-2 font-medium text-slate-300 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            @click="close"
          >
            Cancel
          </button>
          <button
            type="submit"
            :disabled="!canSubmit"
            class="rounded-lg bg-up px-4 py-2 font-medium text-bg transition hover:bg-up/90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {{ submitting ? 'Adding…' : 'Add monitor' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
