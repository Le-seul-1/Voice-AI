<script setup>
import { computed } from 'vue'

const props = defineProps({
  active: { type: Boolean, default: false },
  recording: { type: Boolean, default: false },
  size: { type: Number, default: 190 },
})

const bars = Array.from({ length: 48 }, (_, index) => {
  const wave = Math.abs(Math.sin(index * 0.72)) * 13
  const detail = Math.abs(Math.cos(index * 0.27)) * 6
  return {
    angle: index * 7.5,
    height: 5 + wave + detail,
    delay: `${(index % 16) * 0.07}s`,
    opacity: 0.38 + (index % 5) * 0.11,
  }
})

const orbStyle = computed(() => ({ '--orb-size': `${props.size}px` }))
</script>

<template>
  <svg
    class="voice-orb"
    :class="{ active, recording }"
    :style="orbStyle"
    viewBox="0 0 200 200"
    aria-hidden="true"
  >
    <circle class="ring outer" cx="100" cy="100" r="92" />
    <circle class="ring middle" cx="100" cy="100" r="70" />
    <circle class="ring inner" cx="100" cy="100" r="52" />

    <g class="bars">
      <g v-for="(bar, index) in bars" :key="index" :transform="`rotate(${bar.angle} 100 100)`">
        <rect
          class="bar"
          x="99"
          y="14"
          width="2"
          :height="bar.height"
          rx="1"
          :style="{ animationDelay: bar.delay, opacity: bar.opacity }"
        />
      </g>
    </g>

    <circle class="core" cx="100" cy="100" r="30" />
    <g class="core-bars">
      <rect x="93" y="94" width="3" height="12" rx="1.5" />
      <rect x="98.5" y="88" width="3" height="24" rx="1.5" />
      <rect x="104" y="96" width="3" height="8" rx="1.5" />
    </g>
  </svg>
</template>

<style scoped>
.voice-orb {
  width: var(--orb-size);
  height: var(--orb-size);
  display: block;
  overflow: visible;
  color: var(--mint);
}

.ring {
  fill: none;
  stroke: currentColor;
  stroke-width: 1;
  opacity: 0.18;
}

.ring.middle {
  opacity: 0.14;
}

.ring.inner {
  opacity: 0.22;
  stroke-dasharray: 2 6;
  transform-box: fill-box;
  transform-origin: center;
  animation: orb-spin 28s linear infinite;
}

.bar {
  fill: currentColor;
  transform-box: fill-box;
  transform-origin: center bottom;
  animation: orb-breathe 3.6s ease-in-out infinite;
}

.active .bar {
  animation: orb-live 1.15s ease-in-out infinite;
}

.recording {
  color: var(--ember);
}

.recording .ring {
  opacity: 0.3;
}

.core {
  fill: rgba(98, 246, 181, 0.06);
  stroke: currentColor;
  stroke-width: 1;
  opacity: 0.9;
}

.recording .core {
  fill: rgba(233, 107, 52, 0.08);
}

.core-bars rect {
  fill: currentColor;
}

.active .core {
  animation: orb-core 1.15s ease-in-out infinite;
}

@keyframes orb-breathe {
  0%,
  100% {
    transform: scaleY(0.72);
  }
  50% {
    transform: scaleY(1);
  }
}

@keyframes orb-live {
  0%,
  100% {
    transform: scaleY(0.5);
  }
  50% {
    transform: scaleY(1.28);
  }
}

@keyframes orb-core {
  0%,
  100% {
    opacity: 0.7;
  }
  50% {
    opacity: 1;
  }
}

@keyframes orb-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .bar,
  .active .bar,
  .ring.inner,
  .active .core {
    animation: none;
  }
}
</style>
