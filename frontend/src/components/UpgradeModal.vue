<script setup>
import { ref, watch } from 'vue'

import { paymentsApi, extractErrorMessage } from '@/api'

// Upgrade modal that initiates a SePay payment and renders the QR (Req 21.5).
//
// On open it calls POST /api/payments/initiate for the selected plan and shows
// the returned QR within 5 seconds. If the request fails or exceeds 5 seconds,
// the current plan is left unchanged and a retry error is shown (Req 21.6).
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  plan: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])

const QR_TIMEOUT_MS = 5000

const loading = ref(false)
const error = ref('')
const qrUrl = ref('')
const referenceCode = ref('')
const amount = ref(null)

function close() {
  emit('update:modelValue', false)
}

function reset() {
  loading.value = false
  error.value = ''
  qrUrl.value = ''
  referenceCode.value = ''
  amount.value = null
}

async function initiate() {
  if (!props.plan) return
  loading.value = true
  error.value = ''
  qrUrl.value = ''

  const timeout = new Promise((_, reject) =>
    setTimeout(() => reject(new Error('timeout')), QR_TIMEOUT_MS),
  )
  try {
    const { data } = await Promise.race([
      paymentsApi.initiate(props.plan.id),
      timeout,
    ])
    qrUrl.value = data.qr_url
    referenceCode.value = data.reference_code
    amount.value = data.amount
  } catch (err) {
    // Keep the current plan; show a retryable error (Requirement 21.6).
    error.value =
      err?.message === 'timeout'
        ? 'The payment QR code took too long to load.'
        : extractErrorMessage(err)
  } finally {
    loading.value = false
  }
}

// Initiate whenever the modal opens with a plan; reset when it closes.
watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      reset()
      initiate()
    }
  },
)
</script>

<template>
  <div
    v-if="modelValue"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
    data-testid="upgrade-modal"
  >
    <div class="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">
      <div class="mb-4 flex items-center justify-between">
        <h2 class="text-lg font-semibold text-slate-100">
          Upgrade to {{ plan ? plan.name : '' }}
        </h2>
        <button
          type="button"
          class="text-slate-400 hover:text-slate-200"
          aria-label="Close"
          @click="close"
        >
          ✕
        </button>
      </div>

      <div v-if="loading" class="py-10 text-center text-slate-400" data-testid="upgrade-loading">
        Generating payment QR…
      </div>

      <div v-else-if="error" class="py-6 text-center" data-testid="upgrade-error">
        <p class="mb-4 text-sm text-down">{{ error }}</p>
        <button
          type="button"
          class="rounded-lg bg-up px-4 py-2 font-medium text-bg transition hover:bg-up/90"
          data-testid="upgrade-retry"
          @click="initiate"
        >
          Retry
        </button>
      </div>

      <div v-else-if="qrUrl" class="text-center" data-testid="upgrade-qr">
        <p class="mb-3 text-sm text-slate-400">
          Scan with your banking app to complete the transfer.
        </p>
        <img
          :src="qrUrl"
          alt="SePay payment QR code"
          class="mx-auto h-56 w-56 rounded-lg bg-white p-2"
        />
        <p class="mt-3 font-mono text-sm text-slate-300">
          Ref: {{ referenceCode }}
        </p>
        <p class="text-xs text-slate-500">
          Your plan upgrades automatically once payment is confirmed.
        </p>
      </div>
    </div>
  </div>
</template>
