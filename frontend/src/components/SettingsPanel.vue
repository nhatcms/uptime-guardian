<script setup>
import { computed, onMounted, ref } from 'vue'

import UpgradeModal from '@/components/UpgradeModal.vue'
import { plansApi, settingsApi, extractErrorMessage } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'

// Dashboard settings panel (Requirement 21).
//
// Displays the active plan name, max monitors, min interval, SSL flag, usage as
// "used of total" active monitors, the paid-plan expiry, and the Telegram chat
// id field populated with the stored value. Selecting a paid plan opens the
// upgrade modal which renders the SePay QR.
const auth = useAuthStore()
const toast = useToastStore()

const loading = ref(true)
const settings = ref(null)
const telegramInput = ref('')
const savingTelegram = ref(false)

const plans = ref([])
const upgradeOpen = ref(false)
const selectedPlan = ref(null)

const usageLabel = computed(() => {
  if (!settings.value) return ''
  return `${settings.value.monitors_used} of ${settings.value.monitors_total}`
})

const isPaidPlan = computed(
  () => settings.value && Number(settings.value.plan.price) > 0,
)

const expiryLabel = computed(() => {
  if (!settings.value || !settings.value.plan_expires_at) return null
  const d = new Date(settings.value.plan_expires_at)
  return Number.isNaN(d.getTime()) ? settings.value.plan_expires_at : d.toLocaleString()
})

// Paid plans other than the current one, offered for upgrade.
const upgradePlans = computed(() =>
  plans.value.filter(
    (p) => Number(p.price) > 0 && (!settings.value || p.name !== settings.value.plan.name),
  ),
)

async function loadSettings() {
  loading.value = true
  try {
    const { data } = await settingsApi.get()
    settings.value = data
    telegramInput.value = data.telegram_chat_id || ''
    // Keep the auth profile in sync for the admin guard.
    await auth.fetchProfile()
  } catch (err) {
    toast.error(extractErrorMessage(err))
  } finally {
    loading.value = false
  }
}

async function loadPlans() {
  try {
    const { data } = await plansApi.list()
    plans.value = Array.isArray(data) ? data : []
  } catch {
    plans.value = []
  }
}

async function saveTelegram() {
  if (savingTelegram.value) return
  savingTelegram.value = true
  try {
    await settingsApi.setTelegram(telegramInput.value.trim())
    toast.success('Telegram settings saved.')
    await loadSettings()
  } catch (err) {
    toast.error(extractErrorMessage(err))
  } finally {
    savingTelegram.value = false
  }
}

function openUpgrade(plan) {
  selectedPlan.value = plan
  upgradeOpen.value = true
}

onMounted(() => {
  loadSettings()
  loadPlans()
})
</script>

<template>
  <section
    class="rounded-2xl border border-slate-800 bg-slate-900/40 p-6"
    data-testid="settings-panel"
  >
    <h2 class="mb-4 text-lg font-semibold text-slate-100">Plan &amp; settings</h2>

    <div v-if="loading" class="text-slate-500">Loading settings…</div>

    <div v-else-if="settings" class="space-y-6">
      <!-- Active plan summary (Req 21.1, 21.2, 21.3) -->
      <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <p class="text-xs uppercase tracking-wide text-slate-500">Plan</p>
          <p class="font-mono text-base text-up" data-testid="plan-name">
            {{ settings.plan.name }}
          </p>
        </div>
        <div>
          <p class="text-xs uppercase tracking-wide text-slate-500">Usage</p>
          <p class="font-mono text-base text-slate-100" data-testid="usage">
            {{ usageLabel }}
          </p>
        </div>
        <div>
          <p class="text-xs uppercase tracking-wide text-slate-500">Min interval</p>
          <p class="font-mono text-base text-slate-100">
            {{ settings.plan.min_interval_minutes }} min
          </p>
        </div>
        <div>
          <p class="text-xs uppercase tracking-wide text-slate-500">SSL checks</p>
          <p class="font-mono text-base text-slate-100">
            {{ settings.plan.ssl_check_enabled ? 'On' : 'Off' }}
          </p>
        </div>
      </div>

      <p v-if="isPaidPlan && expiryLabel" class="text-sm text-slate-400" data-testid="expiry">
        Plan expires: {{ expiryLabel }}
      </p>

      <!-- Telegram configuration (Req 10, 21.4) -->
      <div>
        <label for="telegram" class="mb-1.5 block text-sm font-medium text-slate-300">
          Telegram chat ID
        </label>
        <div class="flex gap-2">
          <input
            id="telegram"
            v-model="telegramInput"
            type="text"
            placeholder="e.g. 123456789 (leave empty to disable)"
            class="flex-1 rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 placeholder-slate-500 outline-none transition focus:border-up focus:ring-1 focus:ring-up"
          />
          <button
            type="button"
            :disabled="savingTelegram"
            class="rounded-lg bg-up px-4 py-2 font-medium text-bg transition hover:bg-up/90 disabled:opacity-60"
            @click="saveTelegram"
          >
            Save
          </button>
        </div>
      </div>

      <!-- Upgrade options (Req 21.5) -->
      <div v-if="upgradePlans.length">
        <p class="mb-2 text-sm font-medium text-slate-300">Upgrade your plan</p>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="plan in upgradePlans"
            :key="plan.id"
            type="button"
            class="rounded-lg border border-up/50 px-4 py-2 text-sm text-up transition hover:bg-up/10"
            :data-testid="`upgrade-${plan.id}`"
            @click="openUpgrade(plan)"
          >
            {{ plan.name }}
          </button>
        </div>
      </div>
    </div>

    <UpgradeModal v-model="upgradeOpen" :plan="selectedPlan" />
  </section>
</template>
