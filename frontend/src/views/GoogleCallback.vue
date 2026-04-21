<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'

// Landing page for the Google OAuth redirect. The backend bounces the browser
// here with the result in the URL *fragment* (#token=...&status=... or
// #error=...). The fragment is read on the client and never sent to a server,
// keeping the token out of access logs. On success we establish the session
// and route to the dashboard; on failure we show a friendly message and route
// back to login.
const auth = useAuthStore()
const toast = useToastStore()
const router = useRouter()

const message = ref('Signing you in…')

// Friendly copy for each error code the backend can return.
const ERROR_MESSAGES = {
  access_denied: 'Google sign-in was cancelled.',
  invalid_request: 'The sign-in request was invalid or expired. Please try again.',
  provider_unavailable: 'Could not reach Google. Please try again later.',
  exchange_failed: 'Google sign-in failed. Please try again.',
  account_conflict: 'This email is already linked to a different Google account.',
}

function parseFragment() {
  // location.hash looks like "#token=...&status=ok"; strip the leading '#'.
  const raw = window.location.hash.startsWith('#')
    ? window.location.hash.slice(1)
    : window.location.hash
  return new URLSearchParams(raw)
}

onMounted(async () => {
  const params = parseFragment()
  const error = params.get('error')
  const token = params.get('token')
  const statusFlag = params.get('status')

  // Clear the fragment so the token isn't left in the address bar / history.
  if (window.history.replaceState) {
    window.history.replaceState(null, '', window.location.pathname)
  }

  if (error || !token) {
    toast.error(ERROR_MESSAGES[error] || 'Google sign-in failed.')
    await router.replace({ name: 'login' })
    return
  }

  try {
    await auth.loginWithToken(token)
    if (statusFlag === 'linked') {
      toast.success('Your email account has been linked with Google.')
    } else {
      toast.success('Signed in with Google.')
    }
    await router.replace({ name: 'dashboard' })
  } catch {
    toast.error('Could not complete sign-in. Please try again.')
    await router.replace({ name: 'login' })
  }
})
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-bg px-4">
    <div class="text-center">
      <div
        class="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-up"
      ></div>
      <p class="text-sm text-slate-400">{{ message }}</p>
    </div>
  </div>
</template>
