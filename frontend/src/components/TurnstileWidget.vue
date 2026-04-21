<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

// Cloudflare Turnstile widget (Requirement 20.3).
//
// Emits the produced token via `v-model` and exposes a `reset()` method so the
// parent can clear the challenge after a failed submission (Requirement 20.6).
//
// When no site key is configured (VITE_TURNSTILE_SITE_KEY empty) the component
// renders a dev-mode control that produces a placeholder token, mirroring the
// backend's dev bypass so local development and tests work without a real
// Cloudflare account.

const props = defineProps({
  modelValue: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || ''
const SCRIPT_SRC =
  'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'

const container = ref(null)
let widgetId = null

const devMode = !SITE_KEY

function setToken(token) {
  emit('update:modelValue', token || '')
}

/** Reset the challenge so a fresh token is required (Requirement 20.6). */
function reset() {
  setToken('')
  if (!devMode && window.turnstile && widgetId != null) {
    try {
      window.turnstile.reset(widgetId)
    } catch {
      // Ignore reset failures; the cleared token already blocks submission.
    }
  }
}

defineExpose({ reset })

function renderWidget() {
  if (devMode || !window.turnstile || !container.value) return
  widgetId = window.turnstile.render(container.value, {
    sitekey: SITE_KEY,
    callback: (token) => setToken(token),
    'expired-callback': () => setToken(''),
    'error-callback': () => setToken(''),
  })
}

function loadScript() {
  if (window.turnstile) {
    renderWidget()
    return
  }
  const existing = document.querySelector(`script[src="${SCRIPT_SRC}"]`)
  if (existing) {
    existing.addEventListener('load', renderWidget, { once: true })
    return
  }
  const script = document.createElement('script')
  script.src = SCRIPT_SRC
  script.async = true
  script.defer = true
  script.addEventListener('load', renderWidget, { once: true })
  document.head.appendChild(script)
}

onMounted(() => {
  if (!devMode) loadScript()
})

onBeforeUnmount(() => {
  if (!devMode && window.turnstile && widgetId != null) {
    try {
      window.turnstile.remove(widgetId)
    } catch {
      // Ignore removal failures on teardown.
    }
  }
})

/** Dev-mode helper: emit a placeholder token accepted by the backend bypass. */
function emitDevToken() {
  setToken('dev-turnstile-token')
}
</script>

<template>
  <div class="turnstile-widget">
    <!-- Production: the Cloudflare widget mounts here. -->
    <div v-if="!devMode" ref="container" data-testid="turnstile-container" />

    <!-- Dev/test fallback when no site key is configured. -->
    <div v-else class="rounded-lg border border-slate-700 bg-slate-950/40 p-3">
      <button
        type="button"
        data-testid="turnstile-dev-verify"
        class="w-full rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-300 transition hover:bg-slate-800"
        @click="emitDevToken"
      >
        {{ modelValue ? '✓ Verified (dev)' : 'Complete bot challenge (dev)' }}
      </button>
    </div>
  </div>
</template>
