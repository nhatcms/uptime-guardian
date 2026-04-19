<script setup>
import { computed, ref, watch } from 'vue'

import { useMonitorsStore } from '@/stores/monitors'
import { useToastStore } from '@/stores/toast'

/**
 * EditMonitorModal — a dark-theme modal dialog for editing or deleting a
 * Monitor (Requirements 1.6, 1.7).
 *
 * Component contract
 * ------------------
 * Props:
 *   - `modelValue` (Boolean, default false): controls visibility. Designed for
 *     `v-model` so a parent can open/close it:
 *         <EditMonitorModal v-model="showEditModal" :monitor="selected" />
 *   - `monitor` (Object): the monitor to edit. The form is pre-filled from this
 *     object whenever the modal opens.
 *
 * Emits:
 *   - `update:modelValue` (Boolean): paired with `modelValue` for `v-model`.
 *   - `close`: emitted whenever the modal closes.
 *   - `updated` (Monitor): emitted with the updated monitor after a successful
 *     PUT (the store already refreshes the list itself).
 *   - `deleted` (id): emitted with the monitor id after a successful DELETE.
 *
 * Behavior:
 *   - Form fields: name, url (validated http/https), interval dropdown, and an
 *     "active" toggle (is_active).
 *   - Only the fields that actually changed are sent in the PUT payload, since
 *     MonitorUpdate treats every field as optional.
 *   - A "Delete" action with an inline confirm step removes the monitor via the
 *     store and emits `deleted` (Requirement 1.7).
 */

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  monitor: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['update:modelValue', 'close', 'updated', 'deleted'])

const monitors = useMonitorsStore()
const toast = useToastStore()

// Allowed polling intervals (minutes) per design: 5/10/15/30.
const INTERVAL_OPTIONS = [5, 10, 15, 30]

const name = ref('')
const url = ref('')
const interval = ref(5)
const isActive = ref(true)

const urlTouched = ref(false)
const submitError = ref('')
const submitting = ref(false)
// Two-step delete: the first click arms the confirm, the second commits it.
const confirmingDelete = ref(false)
const deleting = ref(false)

/**
 * Validate that `value` is a well-formed absolute http/https URL.
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
  return Boolean(parsed.hostname)
}

const urlError = computed(() => {
  if (!urlTouched.value) return ''
  if (!url.value.trim()) return 'URL is required.'
  if (!isValidHttpUrl(url.value)) {
    return 'Enter a valid http or https URL (e.g. https://example.com).'
  }
  return ''
})

const nameValid = computed(() => Boolean(name.value.trim()))
const busy = computed(() => submitting.value || deleting.value)
const canSubmit = computed(
  () => nameValid.value && isValidHttpUrl(url.value) && !busy.value,
)

/** Populate the form fields from the supplied monitor. */
function fillFromMonitor() {
  const m = props.monitor || {}
  name.value = m.name ?? ''
  url.value = m.url ?? ''
  interval.value = m.check_interval_minutes ?? 5
  isActive.value = m.is_active ?? true
  urlTouched.value = false
  submitError.value = ''
  submitting.value = false
  confirmingDelete.value = false
  deleting.value = false
}

/** Request close: emits v-model false plus `close`. */
function close() {
  emit('update:modelValue', false)
  emit('close')
}

/**
 * Build a partial payload containing only the fields that differ from the
 * original monitor, so unchanged values are not needlessly sent.
 */
function buildChangedPayload() {
  const m = props.monitor || {}
  const payload = {}
  const trimmedName = name.value.trim()
  const trimmedUrl = url.value.trim()
  if (trimmedName !== m.name) payload.name = trimmedName
  if (trimmedUrl !== m.url) payload.url = trimmedUrl
  if (interval.value !== m.check_interval_minutes) {
    payload.check_interval_minutes = interval.value
  }
  if (isActive.value !== m.is_active) payload.is_active = isActive.value
  return payload
}

async function handleSubmit() {
  urlTouched.value = true
  submitError.value = ''

  if (!canSubmit.value || !props.monitor) return

  const payload = buildChangedPayload()
  // Nothing changed — just close without a request.
  if (Object.keys(payload).length === 0) {
    close()
    return
  }

  submitting.value = true
  try {
    const updated = await monitors.updateMonitor(props.monitor.id, payload)
    toast.success('Monitor updated.')
    emit('updated', updated)
    close()
  } catch (err) {
    const detail = err?.response?.data?.detail
    submitError.value =
      (typeof detail === 'string' && detail) ||
      err?.message ||
      'Failed to update monitor. Please try again.'
  } finally {
    submitting.value = false
  }
}

async function handleDelete() {
  // First click arms the confirm; second click performs the delete.
  if (!confirmingDelete.value) {
    confirmingDelete.value = true
    return
  }
  if (!props.monitor) return

  deleting.value = true
  submitError.value = ''
  try {
    await monitors.deleteMonitor(props.monitor.id)
    toast.success('Monitor deleted.')
    emit('deleted', props.monitor.id)
    close()
  } catch (err) {
    const detail = err?.response?.data?.detail
    submitError.value =
      (typeof detail === 'string' && detail) ||
      err?.message ||
      'Failed to delete monitor. Please try again.'
  } finally {
    deleting.value = false
    confirmingDelete.value = false
  }
}

// Re-populate the form each time the modal opens.
watch(
  () => props.modelValue,
  (visible) => {
    if (visible) fillFromMonitor()
  },
)
</script>

<template>
  <div
    v-if="modelValue"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="edit-monitor-title"
    @click.self="close"
    @keydown.esc="close"
  >
    <div class="w-full max-w-md rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
      <div class="mb-5 flex items-center justify-between">
        <h2 id="edit-monitor-title" class="font-mono text-lg font-semibold text-slate-100">
          Edit monitor
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
          <label for="edit-monitor-name" class="mb-1.5 block text-sm font-medium text-slate-300">
            Name
          </label>
          <input
            id="edit-monitor-name"
            v-model="name"
            type="text"
            name="name"
            :disabled="busy"
            class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 placeholder-slate-500 outline-none transition focus:border-up focus:ring-1 focus:ring-up disabled:opacity-60"
            placeholder="My website"
          />
        </div>

        <div>
          <label for="edit-monitor-url" class="mb-1.5 block text-sm font-medium text-slate-300">
            URL
          </label>
          <input
            id="edit-monitor-url"
            v-model="url"
            type="url"
            name="url"
            inputmode="url"
            autocomplete="off"
            :disabled="busy"
            :aria-invalid="Boolean(urlError)"
            aria-describedby="edit-monitor-url-error"
            class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 placeholder-slate-500 outline-none transition focus:border-up focus:ring-1 focus:ring-up disabled:opacity-60"
            :class="urlError ? 'border-down focus:border-down focus:ring-down' : ''"
            placeholder="https://example.com"
            @blur="urlTouched = true"
          />
          <p
            v-if="urlError"
            id="edit-monitor-url-error"
            role="alert"
            class="mt-1.5 text-sm text-down"
          >
            {{ urlError }}
          </p>
        </div>

        <div>
          <label for="edit-monitor-interval" class="mb-1.5 block text-sm font-medium text-slate-300">
            Check interval (minutes)
          </label>
          <select
            id="edit-monitor-interval"
            v-model.number="interval"
            name="check_interval_minutes"
            :disabled="busy"
            class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 outline-none transition focus:border-up focus:ring-1 focus:ring-up disabled:opacity-60"
          >
            <option v-for="opt in INTERVAL_OPTIONS" :key="opt" :value="opt">
              {{ opt }}
            </option>
          </select>
        </div>

        <label class="flex items-center gap-3">
          <input
            v-model="isActive"
            type="checkbox"
            name="is_active"
            :disabled="busy"
            class="h-4 w-4 rounded border-slate-600 bg-slate-950/60 text-up focus:ring-up disabled:opacity-60"
          />
          <span class="text-sm font-medium text-slate-300">
            Active (run scheduled checks)
          </span>
        </label>

        <p
          v-if="submitError"
          role="alert"
          class="rounded-lg border border-down/40 bg-down/10 px-3 py-2 text-sm text-down"
        >
          {{ submitError }}
        </p>

        <div class="flex items-center justify-between gap-3 pt-2">
          <!-- Delete (two-step confirm) -->
          <button
            type="button"
            :disabled="busy"
            class="rounded-lg border px-4 py-2 font-medium transition disabled:cursor-not-allowed disabled:opacity-60"
            :class="confirmingDelete
              ? 'border-down bg-down/15 text-down hover:bg-down/25'
              : 'border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-down'"
            @click="handleDelete"
          >
            {{ deleting ? 'Deleting…' : confirmingDelete ? 'Confirm delete' : 'Delete' }}
          </button>

          <div class="flex gap-3">
            <button
              type="button"
              :disabled="busy"
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
              {{ submitting ? 'Saving…' : 'Save changes' }}
            </button>
          </div>
        </div>
      </form>
    </div>
  </div>
</template>
