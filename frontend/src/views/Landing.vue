<script setup>
import { onMounted, ref } from 'vue'

import PricingTable from '@/components/PricingTable.vue'
import { plansApi } from '@/api'

// Public marketing landing page (Requirement 19).
//
// Fetches the active plans and renders a pricing table. When no plans exist a
// placeholder message is shown instead of the table (Req 19.3); when the fetch
// fails, the placeholder plus an error banner are shown while the rest of the
// page stays intact (Req 19.4). A single above-the-fold CTA routes to the
// registration page (Req 19.5, 19.6).
const plans = ref([])
const loading = ref(true)
const loadError = ref(false)

async function loadPlans() {
  loading.value = true
  loadError.value = false
  try {
    const { data } = await plansApi.list()
    plans.value = Array.isArray(data) ? data : []
  } catch {
    loadError.value = true
    plans.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadPlans)
</script>

<template>
  <div class="min-h-screen bg-bg text-slate-100">
    <!-- Hero with the single primary CTA (Requirements 19.5, 19.6) -->
    <section class="mx-auto max-w-5xl px-4 pt-20 pb-12 text-center sm:px-6">
      <h1 class="font-mono text-4xl font-bold tracking-tight text-up sm:text-5xl">
        Uptime Guardian
      </h1>
      <p class="mx-auto mt-4 max-w-2xl text-lg text-slate-300">
        Monitor your sites, get instant Telegram alerts, and track SSL expiry —
        all from one dashboard.
      </p>
      <router-link
        :to="{ name: 'register' }"
        data-testid="cta-register"
        class="mt-8 inline-block rounded-lg bg-up px-8 py-3 text-lg font-semibold text-bg transition hover:bg-up/90"
      >
        Get started free
      </router-link>
    </section>

    <!-- Pricing -->
    <section class="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
      <h2 class="mb-8 text-center text-2xl font-semibold text-slate-100">
        Pricing
      </h2>

      <p
        v-if="loadError"
        role="alert"
        data-testid="pricing-error"
        class="mx-auto mb-6 max-w-md rounded-lg border border-down/40 bg-down/10 px-4 py-3 text-center text-sm text-down"
      >
        Pricing could not be loaded right now. Please try again later.
      </p>

      <div v-if="loading" class="text-center text-slate-500">Loading plans…</div>

      <!-- Placeholder when there are no plans or the fetch failed (19.3, 19.4) -->
      <p
        v-else-if="plans.length === 0"
        data-testid="pricing-placeholder"
        class="text-center text-slate-400"
      >
        Pricing is not currently available.
      </p>

      <PricingTable v-else :plans="plans" />
    </section>
  </div>
</template>
