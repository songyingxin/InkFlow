<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
  >
    <template v-if="name === 'book'">
      <path d="M3 2v12l5-3 5 3V2a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1z" />
    </template>
    <template v-else-if="name === 'outline'">
      <rect x="2" y="2.5" width="12" height="11" rx="1" />
      <line x1="5" y1="5.5" x2="11" y2="5.5" />
      <line x1="5" y1="8" x2="11" y2="8" />
      <line x1="5" y1="10.5" x2="9" y2="10.5" />
    </template>
    <template v-else-if="name === 'future'">
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 4.5V8l2.5 1.5" />
    </template>
    <template v-else-if="name === 'settings'">
      <circle cx="8" cy="8" r="2" />
      <path d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4M12.6 12.6l-1.4-1.4M4.8 4.8L3.4 3.4" />
    </template>
    <template v-else-if="name === 'characters'">
      <circle cx="8" cy="5.5" r="2.5" />
      <path d="M3 13.5c0-2.5 2-4 5-4s5 1.5 5 4" />
    </template>
    <template v-else-if="name === 'relationships'">
      <circle cx="4.5" cy="4.5" r="2" />
      <circle cx="11.5" cy="11.5" r="2" />
      <circle cx="11.5" cy="4.5" r="2" />
      <path d="M6 5.5l4 5M6 4l4 0M9.5 11.5L6 6" />
    </template>
    <template v-else-if="name === 'foreshadowing'">
      <path d="M8 1.5l1.3 4.7L14 7.5l-4.7 1.3L8 13.5l-1.3-4.7L2 7.5l4.7-1.3z" />
    </template>
  </svg>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  name: 'book' | 'outline' | 'future' | 'settings' | 'characters' | 'relationships' | 'foreshadowing'
  size?: number
  strokeWidth?: number
}>(), {
  size: 14,
  strokeWidth: 1.2,
})
</script>
