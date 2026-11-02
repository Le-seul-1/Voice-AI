<script setup>
const props = defineProps({
  count: { type: Number, default: 96 },
})

const palette = ['--blue', '--pink', '--yellow', '--violet', '--mint', '--ember']

const bars = Array.from({ length: props.count }, (_, index) => {
  const progress = index / Math.max(1, props.count - 1)
  const envelope = Math.sin(progress * Math.PI)
  const texture = Math.abs(Math.sin(index * 0.91)) * 20 + Math.abs(Math.cos(index * 0.37)) * 10
  return {
    height: Math.round(8 + envelope * 44 + texture),
    color: palette[index % palette.length],
  }
})
</script>

<template>
  <div class="spectrogram" aria-hidden="true">
    <i
      v-for="(bar, index) in bars"
      :key="index"
      :style="{ height: `${bar.height}px`, background: `var(${bar.color})` }"
    ></i>
  </div>
</template>

<style scoped>
.spectrogram {
  width: 100%;
  height: 86px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  overflow: hidden;
  padding: 0 var(--page-pad);
}

.spectrogram i {
  width: 3px;
  flex: 0 0 3px;
  display: block;
  border-radius: 1.5px;
  opacity: 0.92;
}

@media (max-width: 760px) {
  .spectrogram {
    height: 68px;
    gap: 3px;
  }

  .spectrogram i {
    width: 2px;
    flex-basis: 2px;
  }

  .spectrogram i:nth-child(3n) {
    display: none;
  }
}

@media (max-width: 430px) {
  .spectrogram {
    height: 56px;
  }

  .spectrogram i:nth-child(2n) {
    display: none;
  }
}
</style>
