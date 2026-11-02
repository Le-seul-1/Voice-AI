<script setup>
import { computed } from 'vue'

const props = defineProps({
  view: { type: String, default: 'client' },
  runtime: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['navigate'])

const modelLabel = computed(() => {
  const raw = props.runtime?.model || 'Gemma'
  const [family, tag] = raw.split(':')
  const prettyFamily = family
    .replace(/^gemma[\s-]*(\d)/i, 'Gemma $1')
    .replace(/[\s-]+/g, ' ')
    .trim()
  const prettyTag = tag ? tag.replace(/-/g, ' ').toUpperCase() : ''
  return `${prettyFamily}${prettyTag ? ` ${prettyTag}` : ''}`
})

const modelReady = computed(() => Boolean(props.runtime?.ollama?.model_available))
const ollamaReachable = computed(() => Boolean(props.runtime?.ollama?.reachable))

const statusLabel = computed(() => {
  if (modelReady.value) return 'Modèle prêt'
  if (ollamaReachable.value) return 'Ollama joignable'
  return 'Mode secours'
})

function go(target) {
  emit('navigate', target)
}
</script>

<template>
  <header class="app-header">
    <div class="header-inner">
      <button class="brand" type="button" aria-label="Banque Claire — accueil" @click="go('client')">
        <svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect x="1" y="1" width="30" height="30" rx="5.6" fill="#62f6b5" />
          <rect x="9" y="12" width="2.5" height="8" rx="1.25" fill="#0e0e13" />
          <rect x="14.75" y="8" width="2.5" height="16" rx="1.25" fill="#0e0e13" />
          <rect x="20.5" y="13" width="2.5" height="6" rx="1.25" fill="#0e0e13" />
        </svg>
        <span class="brand-word">banque <strong>claire</strong></span>
      </button>

      <nav class="header-nav" aria-label="Navigation principale">
        <button
          type="button"
          class="nav-link"
          :class="{ active: view === 'client' }"
          :aria-current="view === 'client' ? 'page' : undefined"
          @click="go('client')"
        >
          Assistant
        </button>
        <button
          type="button"
          class="nav-link"
          :class="{ active: view === 'agent' }"
          :aria-current="view === 'agent' ? 'page' : undefined"
          @click="go('agent')"
        >
          Poste conseiller
        </button>
        <a v-if="view === 'client'" class="nav-link" href="#agences">Agences</a>
        <a v-if="view === 'client'" class="nav-link" href="#stack">Sous le capot</a>
      </nav>

      <div class="header-actions">
        <span class="runtime-pill" :title="`${statusLabel} · ${runtime?.whisper_model || 'Whisper'} · TTS ${runtime?.tts_engine || 'auto'}`">
          <span class="dot" :class="modelReady ? 'mint' : ollamaReachable ? 'cream' : 'ember'"></span>
          <span class="runtime-model">{{ modelLabel }}</span>
          <span class="runtime-sep" aria-hidden="true">/</span>
          <span class="runtime-local">Local</span>
        </span>
        <button
          v-if="view === 'client'"
          class="btn btn-mint btn-compact header-cta"
          type="button"
          @click="go('agent')"
        >
          Conseiller
          <span aria-hidden="true">→</span>
        </button>
        <button
          v-else
          class="btn btn-ember btn-compact header-cta"
          type="button"
          @click="go('client')"
        >
          Espace client
          <span aria-hidden="true">→</span>
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: relative;
  z-index: 20;
  border-bottom: 1px solid rgba(216, 215, 212, 0.18);
  background: var(--void);
}

.header-inner {
  width: 100%;
  max-width: var(--page-max);
  min-height: 72px;
  margin: 0 auto;
  padding: 0 var(--page-pad);
  display: flex;
  align-items: center;
  gap: 24px;
}

.brand {
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
  padding: 0;
  color: var(--cream);
}

.brand-mark {
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
}

.brand-word {
  font-size: 17px;
  font-weight: 400;
  letter-spacing: -0.02em;
  white-space: nowrap;
}

.brand-word strong {
  font-weight: 650;
}

.header-nav {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 26px;
  flex: 1;
}

.nav-link {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  padding: 10px 0;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.08em;
  line-height: 1;
  text-transform: uppercase;
  transition: color 0.18s ease;
}

.nav-link:hover,
.nav-link.active {
  color: var(--cream);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 0 0 auto;
}

.runtime-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  background: var(--carbon);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.06em;
  line-height: 1;
  text-transform: uppercase;
  color: var(--mercury);
  white-space: nowrap;
}

.runtime-sep {
  color: var(--steel);
}

.runtime-local {
  color: var(--mint);
}

.header-cta {
  gap: 7px;
}

@media (max-width: 1000px) {
  .header-nav {
    gap: 16px;
  }

  .runtime-model {
    max-width: 110px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .nav-link[href='#stack'] {
    display: none;
  }
}

@media (max-width: 760px) {
  .header-inner {
    min-height: 62px;
    gap: 12px;
  }

  .header-nav {
    display: none;
  }

  .header-actions {
    margin-left: auto;
    gap: 8px;
  }

  .runtime-pill {
    padding: 6px 8px;
  }

  .runtime-model,
  .runtime-sep {
    display: none;
  }

  .header-cta {
    min-height: 40px;
    padding: 8px 12px;
    font-size: 9px;
  }

  .brand-word {
    font-size: 15px;
  }

  .brand-mark {
    width: 27px;
    height: 27px;
  }
}

@media (max-width: 380px) {
  .runtime-pill {
    display: none;
  }
}
</style>
