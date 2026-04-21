<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import PlanForm from '@/components/admin/PlanForm.vue'
import TransactionTable from '@/components/admin/TransactionTable.vue'
import UserTable from '@/components/admin/UserTable.vue'
import { adminApi, extractErrorMessage } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'

// Administrative console (Requirement 22).
//
// The router guard already redirects non-admins to the dashboard, but this view
// also renders an access-denied panel as defense in depth (Requirement 22.5).
// It shows plan management (create/update/delete), the user list, and the
// transaction list, each with empty-state handling.
const auth = useAuthStore()
const toast = useToastStore()
const router = useRouter()

const isAdmin = computed(() => auth.isAdmin)

const plans = ref([])
const users = ref([])
const transactions = ref([])
const editingPlan = ref(null)
const loading = ref(true)

async function loadAll() {
  loading.value = true
  try {
    const [planRes, userRes, txnRes] = await Promise.all([
      adminApi.listPlans(),
      adminApi.listUsers(),
      adminApi.listTransactions(),
    ])
    plans.value = planRes.data
    users.value = userRes.data
    transactions.value = txnRes.data
  } catch (err) {
    toast.error(extractErrorMessage(err))
  } finally {
    loading.value = false
  }
}

async function savePlan(payload) {
  try {
    if (editingPlan.value) {
      await adminApi.updatePlan(editingPlan.value.id, payload)
      toast.success('Plan updated.')
    } else {
      await adminApi.createPlan(payload)
      toast.success('Plan created.')
    }
    editingPlan.value = null
    await loadAll()
  } catch (err) {
    toast.error(extractErrorMessage(err))
  }
}

async function deletePlan(plan) {
  try {
    await adminApi.deletePlan(plan.id)
    toast.success('Plan deleted.')
    await loadAll()
  } catch (err) {
    // A 409 (has subscribers) surfaces here as a toast (Requirement 17.6).
    toast.error(extractErrorMessage(err))
  }
}

function editPlan(plan) {
  editingPlan.value = plan
}

onMounted(async () => {
  if (!auth.user) await auth.fetchProfile()
  if (isAdmin.value) loadAll()
})
</script>

<template>
  <div class="min-h-screen bg-bg text-slate-100">
    <header class="border-b border-slate-800 bg-slate-900/40">
      <div class="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <h1 class="font-mono text-xl font-semibold tracking-tight text-up">
          Admin Console
        </h1>
        <router-link
          :to="{ name: 'dashboard' }"
          class="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 transition hover:bg-slate-800"
        >
          ← Dashboard
        </router-link>
      </div>
    </header>

    <!-- Access-denied panel for non-admins (Requirement 22.5) -->
    <main v-if="!isAdmin" class="mx-auto max-w-3xl px-4 py-24 text-center" data-testid="access-denied">
      <p class="text-lg text-down">Access denied</p>
      <p class="mt-2 text-sm text-slate-400">
        This area requires administrator privileges.
      </p>
    </main>

    <main v-else class="mx-auto max-w-6xl space-y-10 px-4 py-8 sm:px-6">
      <!-- Plan management -->
      <section>
        <h2 class="mb-4 text-lg font-semibold text-slate-100">Plans</h2>
        <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <PlanForm
            :plan="editingPlan"
            @save="savePlan"
            @cancel="editingPlan = null"
          />
          <div class="space-y-2" data-testid="plan-list">
            <div
              v-for="plan in plans"
              :key="plan.id"
              class="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3"
            >
              <div>
                <p class="font-mono text-up">{{ plan.name }}</p>
                <p class="text-xs text-slate-500">
                  {{ plan.max_monitors }} monitors · {{ plan.min_interval_minutes }} min
                </p>
              </div>
              <div class="flex gap-2">
                <button
                  type="button"
                  class="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 transition hover:bg-slate-800"
                  @click="editPlan(plan)"
                >
                  Edit
                </button>
                <button
                  type="button"
                  class="rounded-md border border-down/50 px-3 py-1 text-xs text-down transition hover:bg-down/10"
                  @click="deletePlan(plan)"
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Users -->
      <section>
        <h2 class="mb-4 text-lg font-semibold text-slate-100">Users</h2>
        <UserTable :users="users" />
      </section>

      <!-- Transactions -->
      <section>
        <h2 class="mb-4 text-lg font-semibold text-slate-100">Transactions</h2>
        <TransactionTable :transactions="transactions" />
      </section>
    </main>
  </div>
</template>
