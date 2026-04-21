<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import TurnstileWidget from '@/components/TurnstileWidget.vue'
import { extractErrorMessage } from '@/api'
import { useAuthStore } from '@/stores/auth'

// Login view with the Turnstile bot challenge (Requirements 12, 20).
//
// Submission is blocked until all required fields are filled AND a Turnstile
// token exists (Requirements 20.4, 20.5). On an API error the user stays on the
// page, an error is shown, and the widget is reset so a new token is required
// before the next attempt (Requirement 20.6). Entered values are preserved
// except the password.
const auth = useAuthStore()
const router = useRouter()

const username = ref('')
const password = ref('')
const turnstileToken = ref('')
const widget = ref(null)

const fieldErrors = ref({})
const error = ref('')
const loading = ref(false)

function validate() {
  const errors = {}
  if (!username.value.trim()) errors.username = 'Username is required.'
  if (!password.value) errors.password = 'Password is required.'
  if (!turnstileToken.value) errors.turnstile = 'Complete the bot challenge.'
  fieldErrors.value = errors
  return Object.keys(errors).length === 0
}

async function handleSubmit() {
  if (loading.value) return
  error.value = ''
  if (!validate()) return

  loading.value = true
  try {
    await auth.login(username.value, password.value, turnstileToken.value)
    await router.push({ name: 'dashboard' })
  } catch (err) {
    if (err?.response?.status === 401) {
      error.value = 'Invalid username or password.'
    } else {
      error.value = extractErrorMessage(err)
    }
    // Reset the challenge and clear the password (Requirement 20.6).
    password.value = ''
    turnstileToken.value = ''
    if (widget.value) widget.value.reset()
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
          <p v-if="fieldErrors.username" class="mt-1 text-xs text-down">
            {{ fieldErrors.username }}
          </p>
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
          <p v-if="fieldErrors.password" class="mt-1 text-xs text-down">
            {{ fieldErrors.password }}
          </p>
        </div>

        <div>
          <TurnstileWidget ref="widget" v-model="turnstileToken" />
          <p v-if="fieldErrors.turnstile" class="mt-1 text-xs text-down">
            {{ fieldErrors.turnstile }}
          </p>
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

        <p class="text-center text-sm text-slate-400">
          No account?
          <router-link :to="{ name: 'register' }" class="text-up hover:underline">
            Create one
          </router-link>
        </p>
      </form>
    </div>
  </div>
</template>
