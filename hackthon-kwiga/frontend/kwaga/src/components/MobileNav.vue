<script setup>
defineProps({
  view: { type: String, default: 'client' },
})

const emit = defineEmits(['navigate'])
</script>

<template>
  <nav class="mobile-nav" aria-label="Navigation mobile">
    <button
      type="button"
      class="mobile-nav-item"
      :class="{ active: view === 'client' }"
      :aria-current="view === 'client' ? 'page' : undefined"
      @click="emit('navigate', 'client')"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M20 11.5a8 8 0 0 1-11.6 7.1L4 20l1.4-4.2A8 8 0 1 1 20 11.5Z"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linejoin="round"
        />
        <path d="M8 11h8M8 14h5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
      </svg>
      <span>Assistant</span>
    </button>

    <span class="mobile-nav-local">
      <span class="dot mint"></span>
      Local
    </span>

    <button
      type="button"
      class="mobile-nav-item"
      :class="{ active: view === 'agent' }"
      :aria-current="view === 'agent' ? 'page' : undefined"
      @click="emit('navigate', 'agent')"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="4" y="4" width="6" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="1.5" />
        <rect x="14" y="4" width="6" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="1.5" />
        <rect x="4" y="14" width="6" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="1.5" />
        <rect x="14" y="14" width="6" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="1.5" />
      </svg>
      <span>Conseiller</span>
    </button>
  </nav>
</template>

<style scoped>
.mobile-nav {
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 50;
  display: none;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 6px 14px calc(6px + env(safe-area-inset-bottom));
  border-top: 1px solid var(--iron);
  background: var(--carbon);
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.mobile-nav-item {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 7px 8px;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  transition: color 0.18s ease;
}

.mobile-nav-item svg {
  width: 20px;
  height: 20px;
}

.mobile-nav-item.active {
  color: var(--mint);
}

.mobile-nav-local {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  padding: 0 6px;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.mobile-nav-local .dot {
  width: 5px;
  height: 5px;
}

@media (max-width: 760px) {
  .mobile-nav {
    display: flex;
  }
}
</style>
