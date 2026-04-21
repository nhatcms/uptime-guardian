<script setup>
// Admin user listing (Requirement 22.2, 22.3): identifier + active plan name,
// with an empty-state indication when there are no users.
defineProps({
  users: { type: Array, default: () => [] },
})
</script>

<template>
  <div data-testid="user-table">
    <p
      v-if="users.length === 0"
      class="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-6 text-center text-sm text-slate-400"
      data-testid="users-empty"
    >
      No registered users yet.
    </p>

    <table v-else class="w-full text-left text-sm">
      <thead class="text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th class="py-2">User</th>
          <th class="py-2">Email</th>
          <th class="py-2">Plan</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-800">
        <tr v-for="user in users" :key="user.username">
          <td class="py-2 font-mono text-slate-100">{{ user.username }}</td>
          <td class="py-2 text-slate-400">{{ user.email || '—' }}</td>
          <td class="py-2 text-up">{{ user.plan_name || '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
