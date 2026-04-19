<script setup>
import { storeToRefs } from 'pinia'

import { useToastStore } from '@/stores/toast'

// ToastContainer renders the stack of transient notifications held in the toast
// store. It is mounted once at the app root (App.vue) so notifications are
// visible from any view. Errors use the dark-theme "down" red (#ff4757) and
// successes the "up" teal, keeping the look consistent with the rest of the UI.
// (Requirement 11.7)

const toastStore = useToastStore()
const { toasts } = storeToRefs(toastStore)

function dismiss(id) {
  toastStore.removeToast(id)
}
</script>

<template>
  <div
    class="pointer-events-none fixed inset-x-0 top-4 z-50 flex flex-col items-center gap-2 px-4 sm:items-end sm:px-6"
    aria-live="polite"
    aria-atomic="false"
  >
    <transition-group
      name="toast"
      tag="div"
      class="flex w-full max-w-sm flex-col gap-2"
    >
      <div
        v-for="toast in toasts"
        :key="toast.id"
        role="alert"
        class="pointer-events-auto flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-sm shadow-xl backdrop-blur"
        :class="{
          'border-down/50 bg-down/10 text-down': toast.type === 'error',
          'border-up/50 bg-up/10 text-up': toast.type === 'success',
        }"
      >
        <span class="flex-1 break-words leading-snug">{{ toast.message }}</span>
        <button
          type="button"
          class="-mr-1 shrink-0 rounded text-slate-400 transition hover:text-slate-200 focus:outline-none focus:ring-1 focus:ring-slate-500"
          aria-label="Dismiss notification"
          @click="dismiss(toast.id)"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            class="h-4 w-4"
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
    </transition-group>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
