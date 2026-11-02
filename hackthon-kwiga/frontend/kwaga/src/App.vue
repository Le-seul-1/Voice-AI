<script setup>
import { onMounted, ref } from 'vue'
import { API_URL } from './api'
import AppHeader from './components/AppHeader.vue'
import AgentDashboard from './components/AgentDashboard.vue'
import CallAssistant from './components/CallAssistant.vue'
import MobileNav from './components/MobileNav.vue'

const view = ref('client')
const runtime = ref({
  model: 'Gemma',
  tts_engine: 'auto',
  whisper_model: 'tiny',
  ollama: null,
})

function navigate(target) {
  view.value = target
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(async () => {
  try {
    const response = await fetch(`${API_URL}/api/health`)
    if (response.ok) {
      runtime.value = await response.json()
    }
  } catch {
    // Le bandeau reste en « mode secours » si le backend n'est pas encore prêt.
  }
})
</script>

<template>
  <div class="app-frame">
    <AppHeader :view="view" :runtime="runtime" @navigate="navigate" />
    <CallAssistant v-if="view === 'client'" :runtime="runtime" @open-agent="navigate('agent')" />
    <AgentDashboard v-else :runtime="runtime" @back="navigate('client')" />
    <MobileNav :view="view" @navigate="navigate" />
  </div>
</template>
