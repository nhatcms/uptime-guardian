<script setup>
// Root application shell. Views are rendered through the router outlet.
import ToastContainer from '@/components/ToastContainer.vue'
import { useToastStore } from '@/stores/toast'

// Instantiate the toast store once at the app root so it registers the Axios
// error hook (api.onError) for the whole app lifetime. API errors then surface
// as toasts via the shared response interceptor. (Requirement 11.7)
useToastStore()
</script>

<template>
  <div id="app-root" class="min-h-screen bg-bg text-slate-100">
    <router-view />
    <ToastContainer />
  </div>
</template>
