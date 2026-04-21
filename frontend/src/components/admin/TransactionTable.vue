<script setup>
// Admin transaction listing (Requirement 22.4): user, plan, amount, status,
// with an empty-state indication when there are no transactions.
defineProps({
  transactions: { type: Array, default: () => [] },
})

function statusClass(status) {
  if (status === 'completed') return 'text-up'
  if (status === 'failed') return 'text-down'
  return 'text-amber-400'
}
</script>

<template>
  <div data-testid="transaction-table">
    <p
      v-if="transactions.length === 0"
      class="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-6 text-center text-sm text-slate-400"
      data-testid="transactions-empty"
    >
      No transactions yet.
    </p>

    <table v-else class="w-full text-left text-sm">
      <thead class="text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th class="py-2">User</th>
          <th class="py-2">Plan</th>
          <th class="py-2">Amount</th>
          <th class="py-2">Status</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-800">
        <tr v-for="(txn, idx) in transactions" :key="idx">
          <td class="py-2 font-mono text-slate-100">{{ txn.user }}</td>
          <td class="py-2 text-slate-300">{{ txn.plan }}</td>
          <td class="py-2 font-mono text-slate-300">{{ txn.amount }}</td>
          <td class="py-2 font-medium" :class="statusClass(txn.status)">
            {{ txn.status }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
