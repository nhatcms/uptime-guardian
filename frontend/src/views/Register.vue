<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import TurnstileWidget from '@/components/TurnstileWidget.vue'
import { extractErrorMessage, GOOGLE_LOGIN_URL } from '@/api'
import { useAuthStore } from '@/stores/auth'

// Registration view with the Turnstile bot challenge (Requirements 11, 20).
//
// Renders username, email, password fields plus the widget, each initially
// empty (Requirement 20.1). Submission is blocked until all required fields are
// filled and a token exists (Requirements 20.4, 20.5). On an API error the user
// stays on the page, the error is shown, and the widget is reset (Requirement
// 20.6); entered values are preserved except the password. On success the user
// is routed to the login page.
const auth = useAuthStore()
const router = useRouter()

const username = ref('')
const email = ref('')
const password = ref('')
const turnstileToken = ref('')
const widget = ref(null)

const fieldErrors = ref({})
const error = ref('')
const success = ref('')
const loading = ref(false)

function validate() {
  const errors = {}
  if (!username.value.trim()) errors.username = 'Username is required.'
  if (!email.value.trim()) errors.email = 'Email is required.'
  if (!password.value) errors.password = 'Password is required.'
  if (!turnstileToken.value) errors.turnstile = 'Complete the bot challenge.'
  fieldErrors.value = errors
  return Object.keys(errors).length === 0
}

async function handleSubmit() {
  if (loading.value) return
  error.value = ''
  success.value = ''
  if (!validate()) return

  loading.value = true
  try {
    await auth.register(
      username.value,
      email.value,
      password.value,
      turnstileToken.value,
    )
    success.value = 'Account created. You can now sign in.'
    await router.push({ name: 'login' })
  } catch (err) {
    error.value = extractErrorMessage(err)
    password.value = ''
    turnstileToken.value = ''
    if (widget.value) widget.value.reset()
  } finally {
    loading.value = false
  }
}

// Sign up via Google: hand off to the backend, which redirects to Google. A
// new account is provisioned automatically on first Google sign-in.
function signUpWithGoogle() {
  window.location.href = GOOGLE_LOGIN_URL
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-bg px-4">
    <div class="w-full max-w-sm">
      <div class="mb-8 text-center">
        <h1 class="font-mono text-2xl font-semibold tracking-tight text-up">
          Uptime Guardian
        </h1>
        <p class="mt-2 text-sm text-slate-400">Create your account</p>
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
          />
          <p v-if="fieldErrors.username" class="mt-1 text-xs text-down">
            {{ fieldErrors.username }}
          </p>
        </div>

        <div>
          <label for="email" class="mb-1.5 block text-sm font-medium text-slate-300">
            Email
          </label>
          <input
            id="email"
            v-model="email"
            type="email"
            name="email"
            autocomplete="email"
            :disabled="loading"
            class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 placeholder-slate-500 outline-none transition focus:border-up focus:ring-1 focus:ring-up disabled:opacity-60"
          />
          <p v-if="fieldErrors.email" class="mt-1 text-xs text-down">
            {{ fieldErrors.email }}
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
            autocomplete="new-password"
            :disabled="loading"
            class="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 placeholder-slate-500 outline-none transition focus:border-up focus:ring-1 focus:ring-up disabled:opacity-60"
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
          {{ loading ? 'Creating…' : 'Create account' }}
        </button>

        <div class="flex items-center gap-3">
          <span class="h-px flex-1 bg-slate-800"></span>
          <span class="text-xs uppercase tracking-wide text-slate-500">or</span>
          <span class="h-px flex-1 bg-slate-800"></span>
        </div>

        <button
          type="button"
          :disabled="loading"
          class="flex w-full items-center justify-center gap-2.5 rounded-lg border border-slate-700 bg-slate-950/40 px-4 py-2 font-medium text-slate-200 transition hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-60"
          @click="signUpWithGoogle"
        >
          <svg class="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="#4285F4"
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z"
            />
            <path
              fill="#34A853"
              d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.99.66-2.26 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"
            />
            <path
              fill="#FBBC05"
              d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84z"
            />
            <path
              fill="#EA4335"
              d="M12 4.75c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 1.46 14.97.5 12 .5A11 11 0 0 0 2.18 7.06l3.66 2.84C6.71 6.68 9.14 4.75 12 4.75z"
            />
          </svg>
          Sign up with Google
        </button>

        <p class="text-center text-sm text-slate-400">
          Already have an account?
          <router-link :to="{ name: 'login' }" class="text-up hover:underline">
            Sign in
          </router-link>
        </p>
      </form>
    </div>
  </div>
</template>
