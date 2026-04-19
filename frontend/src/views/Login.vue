<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

// Minimalist dark-theme login view. Submits credentials to the auth store,
// which stores the issued Auth_Token; on success we redirect to the dashboard,
// and on a 401 (invalid credentials) we show an inline error without
// navigating. (Requirements 12.1, 11.8)
const auth = useAuthStore()
const router = useRouter()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function handleSubmit() {
  // Guard against double submits while a request is in flight.
  if (loading.value) return

  error.value = ''
  loading.value = true

  try {
    await auth.login(username.value, password.value)
    // Token is persisted by the store; head to the dashboard.
    await router.push({ name: 'dashboard' })
  } catch (err) {
    // A 401 means the credentials did not match; show an inline message and
    // stay on the login view. Any other failure gets a generic message.
    if (err?.response?.status === 401) {
      error.value = 'Invalid username or password.'
    } else {
      error.value = 'Unable to sign in. Please try again.'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-bg px-4">
    <div class="w-full max-w-sm">
      <div class="mb-8 text-center">
        <h1 class="font-mono text-2xl font-semibold tracking-tight text-up">
          Uptime Guardian
        </h1>
        <p class="mt-2 text-sm text-slate-400">Sign in to your dashboard</p>
      </div>

      <form
        class="space-y-5 rounded-xl border border-slate-800 bg-slate-900/40 p-6 shadow-lg"
        novalidate
        @submit.prevent="handleSubmit"
      >
        <div>
          <label for="username" class="mb-1.5 block text-sm font-medium text-slate-300">
            Username
          </label>
          <input
            id="username"
            v-model="username"
            type="text"
            name="username"
            autocomplete="username"
            :disabled="loading"
            class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 placeholder-slate-500 outline-none transition focus:border-up focus:ring-1 focus:ring-up disabled:opacity-60"
            placeholder="admin"
          />
        </div>

        <div>
          <label for="password" class="mb-1.5 block text-sm font-medium text-slate-300">
            Password
          </label>
          <input
            id="password"
            v-model="password"
            type="password"
            name="password"
            autocomplete="current-password"
            :disabled="loading"
            class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 placeholder-slate-500 outline-none transition focus:border-up focus:ring-1 focus:ring-up disabled:opacity-60"
            placeholder="••••••••"
          />
        </div>

        <p
          v-if="error"
          role="alert"
          class="rounded-lg border border-down/40 bg-down/10 px-3 py-2 text-sm text-down"
        >
          {{ error }}
        </p>

        <button
          type="submit"
          :disabled="loading"
          class="w-full rounded-lg bg-up px-4 py-2 font-medium text-bg transition hover:bg-up/90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {{ loading ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>
    </div>
  </div>
</template>
