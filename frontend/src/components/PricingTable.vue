<script setup>
import PlanCard from '@/components/PlanCard.vue'

// Renders one PlanCard per active plan (Requirement 19.1). Emptiness and
// fetch-error placeholders are handled by the parent (Landing); this component
// only lays out the cards it is given.
defineProps({
  plans: { type: Array, default: () => [] },
  selectable: { type: Boolean, default: false },
})
const emit = defineEmits(['select'])
</script>

<template>
  <div
    class="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3"
    data-testid="pricing-table"
  >
    <PlanCard
      v-for="plan in plans"
      :key="plan.id"
      :plan="plan"
      :selectable="selectable"
      @select="emit('select', $event)"
    />
  </div>
</template>
