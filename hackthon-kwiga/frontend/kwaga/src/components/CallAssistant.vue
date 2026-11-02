<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { API_URL, readJson } from '../api'
import Spectrogram from './Spectrogram.vue'
import VoiceOrb from './VoiceOrb.vue'

const props = defineProps({
  runtime: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['open-agent'])

const messages = ref([])
const suggestions = ref([])
const isRecording = ref(false)
const isProcessing = ref(false)
const isSpeaking = ref(false)
const errorMessage = ref('')
const elapsedSeconds = ref(0)
const conversation = ref(null)
const textInput = ref('')
const textInputEl = ref(null)
const voiceEnabled = ref(localStorage.getItem('bc_voice') !== 'off')
const sessionId = ref(loadSessionId())
const agencies = ref([])

let recorder
let microphoneStream
let recordingTimer
let affluenceTimer
const audioUrls = []
const playingAudios = []

const topics = [
  { label: 'Ma carte est bloquée', text: 'Ma carte bancaire est bloquée, pouvez-vous m’aider ?' },
  { label: 'Ouvrir un compte', text: 'Quels sont les documents pour ouvrir un compte courant ?' },
  { label: 'Horaires d’agence', text: 'Quels sont les horaires de l’agence République à Paris ?' },
  { label: 'Demander un crédit', text: 'Quelles sont les conditions pour un crédit à la consommation ?' },
  { label: 'Faire une réclamation', text: 'Je souhaite déposer une réclamation.' },
]

const flow = [
  {
    step: '01',
    title: 'Vous parlez ou vous écrivez',
    description: 'Claire vous écoute et identifie le besoin en quelques secondes.',
  },
  {
    step: '02',
    title: 'Elle vérifie la base locale',
    description: 'RAG BM25 et Gemma répondent à partir des documents Banque Claire.',
  },
  {
    step: '03',
    title: 'Réponse ou ticket conseiller',
    description: 'Un conseiller prend le relais quand la demande le nécessite.',
  },
]

const capabilities = [
  {
    title: 'Carte bancaire',
    description: 'Opposition, déblocage, paiements refusés et plafonds, avec vérification du client.',
  },
  {
    title: 'Ouverture de compte',
    description: 'Documents nécessaires, formules disponibles et prise de rendez-vous en agence.',
  },
  {
    title: 'Crédit',
    description: 'Montants, durées, taux et conditions du crédit à la consommation.',
  },
  {
    title: 'Réclamation',
    description: 'Dépôt guidé, création d’un ticket et transmission au conseiller.',
  },
  {
    title: 'Agences & horaires',
    description: 'Adresses, contacts et affluence en direct pour choisir le bon moment.',
  },
  {
    title: 'Produits & services',
    description: 'Livrets, virements SEPA, assurances et application Claire & Moi.',
  },
]

const recordingLabel = computed(() => {
  const minutes = Math.floor(elapsedSeconds.value / 60).toString().padStart(2, '0')
  const seconds = (elapsedSeconds.value % 60).toString().padStart(2, '0')
  return `${minutes}:${seconds}`
})

const statusText = computed(() => {
  if (isRecording.value) return `Je vous écoute… ${recordingLabel.value}`
  if (isProcessing.value) return 'Claire réfléchit…'
  if (isSpeaking.value) return 'Claire vous répond…'
  return 'Parlez ou écrivez · réponse en français'
})

const canSend = computed(
  () => textInput.value.trim().length > 0 && !isProcessing.value && !isRecording.value,
)

const modelLabel = computed(() => prettyModel(props.runtime?.model))

const modelReady = computed(() => Boolean(props.runtime?.ollama?.model_available))

const ttsLabel = computed(() => {
  const engine = (props.runtime?.tts_engine || 'auto').toLowerCase()
  if (engine === 'browser' || engine === 'none' || engine === '') return 'Voix navigateur'
  if (engine === 'auto') return 'Voix locale · cache'
  if (engine === 'piper') return 'Piper · local'
  if (engine === 'qwen3') return 'Qwen3 · local'
  return `TTS ${engine}`
})

const stackItems = computed(() => [
  {
    label: 'LLM',
    value: modelLabel.value,
    note: modelReady.value ? 'Chargé sur le Jetson, sans cloud' : 'Réponses extractives de secours',
    ready: modelReady.value,
  },
  {
    label: 'STT',
    value: `Whisper ${props.runtime?.whisper_model || 'tiny'}`,
    note: 'Transcription française locale',
    ready: true,
  },
  {
    label: 'TTS',
    value: ttsLabel.value,
    note: 'Voix pré-générées en cache, zéro latence',
    ready: true,
  },
  {
    label: 'Vision',
    value: 'YOLO · affluence.csv',
    note: 'Comptage des personnes en agence',
    ready: true,
  },
])

const liveAgency = computed(() => {
  if (!agencies.value.length) return null
  return (
    agencies.value.find((agency) => agency.alerte) ||
    [...agencies.value].sort((a, b) => b.visibles - a.visibles)[0]
  )
})

const sortedAgencies = computed(() => [...agencies.value].sort((a, b) => a.visibles - b.visibles))

function prettyModel(raw) {
  if (!raw) return 'Gemma'
  const [family, tag] = raw.split(':')
  const prettyFamily = family
    .replace(/^gemma[\s-]*(\d)/i, 'Gemma $1')
    .replace(/[\s-]+/g, ' ')
    .trim()
  const prettyTag = tag ? tag.replace(/-/g, ' ').toUpperCase() : ''
  return `${prettyFamily}${prettyTag ? ` ${prettyTag}` : ''}`
}

function levelLabel(level) {
  return { calme: 'Calme', moderee: 'Modérée', forte: 'Forte', inconnu: 'Inconnue' }[level] || '—'
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

function loadSessionId() {
  const existing = localStorage.getItem('bc_session_id')
  if (existing) return existing
  const suffix = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID().replaceAll('-', '').slice(0, 12)
    : Math.random().toString(36).slice(2, 14)
  const id = `ses-${suffix}`
  localStorage.setItem('bc_session_id', id)
  return id
}

function newSessionId() {
  const suffix = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID().replaceAll('-', '').slice(0, 12)
    : Math.random().toString(36).slice(2, 14)
  return `ses-${suffix}`
}

function scrollToLatest() {
  nextTick(() => conversation.value?.scrollTo({ top: conversation.value.scrollHeight, behavior: 'smooth' }))
}

function chooseMimeType() {
  if (typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported) return ''
  return ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find((type) => MediaRecorder.isTypeSupported(type)) || ''
}

function frenchVoice() {
  const voices = window.speechSynthesis?.getVoices?.() || []
  return voices.find((voice) => voice.lang?.toLowerCase().startsWith('fr'))
}

function speak(text) {
  if (!voiceEnabled.value || !text || !('speechSynthesis' in window)) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'fr-FR'
  utterance.rate = 1.02
  const voice = frenchVoice()
  if (voice) utterance.voice = voice
  utterance.onstart = () => {
    isSpeaking.value = true
  }
  utterance.onend = () => {
    isSpeaking.value = false
  }
  utterance.onerror = () => {
    isSpeaking.value = false
  }
  window.speechSynthesis.speak(utterance)
}

function stopAudio() {
  isSpeaking.value = false
  window.speechSynthesis?.cancel()
  conversation.value?.querySelectorAll('audio').forEach((audio) => audio.pause())
  playingAudios.forEach((audio) => audio.pause())
  playingAudios.length = 0
}

async function playResponse(text) {
  if (!voiceEnabled.value || !text) return
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 12000)
  try {
    const response = await fetch(`${API_URL}/api/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    })
    const payload = await readJson(response)
    if (payload.audio_base64) {
      const bytes = Uint8Array.from(atob(payload.audio_base64), (character) => character.charCodeAt(0))
      const url = URL.createObjectURL(new Blob([bytes], { type: payload.audio_mime_type || 'audio/wav' }))
      audioUrls.push(url)
      const audio = new Audio(url)
      playingAudios.push(audio)
      isSpeaking.value = true
      audio.addEventListener('ended', () => {
        isSpeaking.value = false
        const index = playingAudios.indexOf(audio)
        if (index >= 0) playingAudios.splice(index, 1)
      }, { once: true })
      audio.addEventListener('pause', () => {
        isSpeaking.value = false
      }, { once: true })
      await audio.play().catch(() => speak(text))
      return
    }
  } catch {
    // Le navigateur prend le relais si Qwen3/Piper ne répond pas assez vite.
  } finally {
    window.clearTimeout(timer)
  }
  speak(text)
}

function toggleVoice() {
  voiceEnabled.value = !voiceEnabled.value
  localStorage.setItem('bc_voice', voiceEnabled.value ? 'on' : 'off')
  if (!voiceEnabled.value) stopAudio()
}

function assistantMessage(payload) {
  return {
    role: 'assistant',
    text: payload.answer || payload.response || '',
    intentLabel: payload.intent_label || '',
    sources: payload.sources || [],
    ticket: payload.ticket || null,
    customer: payload.customer || null,
    quickReplies: payload.quick_replies || [],
    action: payload.action || '',
    audioUrl: '',
  }
}

async function playAudioFor(index, text) {
  await nextTick()
  const audio = document.getElementById(`audio-${index}`)
  if (!audio) {
    speak(text)
    return
  }
  audio.currentTime = 0
  isSpeaking.value = true
  audio.onended = () => {
    isSpeaking.value = false
  }
  audio.onpause = () => {
    isSpeaking.value = false
  }
  audio.play().catch(() => speak(text))
}

function replay(message, index) {
  stopAudio()
  if (message.audioUrl) playAudioFor(index, message.text)
  else playResponse(message.text)
}

function focusComposer() {
  document.querySelector('.voice-console')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  window.setTimeout(() => textInputEl.value?.focus(), 350)
}

async function sendMessage(rawText) {
  const text = (rawText ?? textInput.value).trim()
  if (!text || isProcessing.value || isRecording.value) return

  stopAudio()
  textInput.value = ''
  suggestions.value = []
  errorMessage.value = ''
  isProcessing.value = true
  messages.value.push({ role: 'user', text })
  scrollToLatest()

  try {
    const response = await fetch(`${API_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: sessionId.value }),
    })
    const payload = await readJson(response)
    const message = assistantMessage(payload)
    messages.value.push(message)
    suggestions.value = message.quickReplies
    scrollToLatest()
    playResponse(message.text)
  } catch (error) {
    errorMessage.value = error.message || 'Une erreur est survenue pendant le traitement de votre demande.'
  } finally {
    isProcessing.value = false
  }
}

async function startRecording() {
  errorMessage.value = ''
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    errorMessage.value = 'La capture audio n’est pas disponible dans ce navigateur.'
    return
  }

  try {
    microphoneStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = chooseMimeType()
    recorder = new MediaRecorder(microphoneStream, mimeType ? { mimeType } : undefined)
    const chunks = []
    recorder.addEventListener('dataavailable', (event) => {
      if (event.data.size) chunks.push(event.data)
    })
    recorder.addEventListener('stop', () => {
      const audioBlob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
      releaseMicrophone()
      if (audioBlob.size) sendAudio(audioBlob)
    }, { once: true })

    elapsedSeconds.value = 0
    recorder.start()
    isRecording.value = true
    recordingTimer = window.setInterval(() => elapsedSeconds.value += 1, 1000)
  } catch (error) {
    releaseMicrophone()
    errorMessage.value = error.name === 'NotAllowedError'
      ? 'Autorisez l’accès au microphone pour parler à l’assistant.'
      : 'Impossible de démarrer le microphone. Vérifiez qu’il est connecté.'
  }
}

function stopRecording() {
  if (!recorder || recorder.state === 'inactive') return
  isRecording.value = false
  window.clearInterval(recordingTimer)
  recorder.stop()
}

function releaseMicrophone() {
  window.clearInterval(recordingTimer)
  microphoneStream?.getTracks().forEach((track) => track.stop())
  microphoneStream = null
  isRecording.value = false
}

async function sendAudio(audioBlob) {
  stopAudio()
  isProcessing.value = true
  errorMessage.value = ''
  suggestions.value = []
  const userMessage = { role: 'user', text: 'Transcription en cours…', pending: true }
  messages.value.push(userMessage)
  scrollToLatest()

  const formData = new FormData()
  const extension = audioBlob.type.includes('mp4') ? 'm4a' : 'webm'
  formData.append('file', audioBlob, `message.${extension}`)
  formData.append('session_id', sessionId.value)

  try {
    const response = await fetch(`${API_URL}/api/voice-chat`, { method: 'POST', body: formData })
    const payload = await readJson(response)

    userMessage.text = payload.transcription || 'Transcription indisponible'
    userMessage.pending = false
    const message = assistantMessage(payload)
    messages.value.push(message)
    suggestions.value = message.quickReplies
    scrollToLatest()

    if (payload.audio_base64) {
      const bytes = Uint8Array.from(atob(payload.audio_base64), (character) => character.charCodeAt(0))
      message.audioUrl = URL.createObjectURL(new Blob([bytes], { type: payload.audio_mime_type || 'audio/mpeg' }))
      audioUrls.push(message.audioUrl)
      playAudioFor(messages.value.length - 1, message.text)
    } else {
      playResponse(message.text)
    }
  } catch (error) {
    messages.value = messages.value.filter((item) => item !== userMessage)
    errorMessage.value = error.message || 'Une erreur est survenue pendant le traitement de votre demande.'
  } finally {
    isProcessing.value = false
  }
}

function toggleRecording() {
  if (isRecording.value) stopRecording()
  else if (!isProcessing.value) startRecording()
}

function resetConversation() {
  stopAudio()
  messages.value = []
  suggestions.value = []
  errorMessage.value = ''
  sessionId.value = newSessionId()
  localStorage.setItem('bc_session_id', sessionId.value)
}

async function loadAffluence() {
  try {
    const response = await fetch(`${API_URL}/api/affluence`)
    const payload = await readJson(response)
    agencies.value = payload.agencies || []
  } catch {
    // Le bandeau vision reste masqué si le CSV n'est pas encore disponible.
  }
}

onMounted(() => {
  if ('speechSynthesis' in window) window.speechSynthesis.getVoices()
  loadAffluence()
  affluenceTimer = window.setInterval(loadAffluence, 8000)
})

onBeforeUnmount(() => {
  if (recorder?.state === 'recording') recorder.stop()
  releaseMicrophone()
  stopAudio()
  window.clearInterval(affluenceTimer)
  audioUrls.forEach((url) => URL.revokeObjectURL(url))
})
</script>

<template>
  <main class="client-main">
    <section class="hero" aria-labelledby="page-title">
      <div class="hero-copy">
        <p class="eyebrow"><span class="dot mint"></span> Assistant bancaire · 100 % local</p>
        <h1 id="page-title">Une question ?<br /><span>Parlons-en.</span></h1>
        <p class="lede">
          Claire vous répond en français, à l’écrit comme à la voix. Tout est traité
          sur le Jetson, sans cloud, avec des données de démonstration.
        </p>

        <div class="hero-actions">
          <button class="btn btn-ember" type="button" @click="focusComposer">
            Démarrer la conversation
            <span aria-hidden="true">→</span>
          </button>
          <button class="btn btn-mint" type="button" @click="emit('open-agent')">
            Poste conseiller
            <span aria-hidden="true">→</span>
          </button>
        </div>

        <div class="trust-row" aria-label="Garanties du prototype">
          <span><span class="dot mint"></span> Sans cloud</span>
          <span><span class="dot cream"></span> Voix française</span>
          <span><span class="dot ember"></span> Données fictives</span>
        </div>

        <div class="flow-list" aria-label="Déroulé d’un appel">
          <article v-for="item in flow" :key="item.step">
            <span class="mono-label">{{ item.step }}</span>
            <div>
              <h3>{{ item.title }}</h3>
              <p>{{ item.description }}</p>
            </div>
          </article>
        </div>

        <div v-if="liveAgency" class="live-banner">
          <div class="live-banner-copy">
            <span class="mono-label">Vision · affluence en direct</span>
            <p>
              <strong>{{ liveAgency.name }}</strong> · {{ liveAgency.visibles }} personnes ·
              {{ levelLabel(liveAgency.level) }}
            </p>
          </div>
          <span class="status-chip" :class="liveAgency.alerte ? 'alert' : liveAgency.level">
            {{ liveAgency.alerte ? 'Zone d’alerte' : levelLabel(liveAgency.level) }}
          </span>
        </div>
      </div>

      <section class="voice-console panel" aria-label="Conversation avec Claire, assistante bancaire">
        <header class="console-head">
          <div class="console-identity">
            <span class="avatar" aria-hidden="true">bc</span>
            <div>
              <h2>Claire</h2>
              <p><span class="dot mint"></span> Assistante bancaire · en ligne</p>
            </div>
          </div>
          <div class="console-tools">
            <button
              class="voice-toggle"
              :class="{ off: !voiceEnabled }"
              type="button"
              :aria-pressed="voiceEnabled"
              :aria-label="voiceEnabled ? 'Désactiver la voix' : 'Activer la voix'"
              @click="toggleVoice"
            >
              <svg v-if="voiceEnabled" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 9v6h4l5 4V5L8 9H4Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
                <path d="M16 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              </svg>
              <svg v-else viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 9v6h4l5 4V5L8 9H4Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
                <path d="m16 9 5 6M21 9l-5 6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              </svg>
              <span>{{ voiceEnabled ? 'Voix on' : 'Voix off' }}</span>
            </button>
            <span class="demo-tag">Démo</span>
          </div>
        </header>

        <div class="console-stage" :class="{ listening: isRecording, thinking: isProcessing }">
          <VoiceOrb :active="isRecording || isProcessing || isSpeaking" :recording="isRecording" :size="180" />
          <p class="stage-kicker">
            {{ isRecording ? 'À l’écoute' : isProcessing ? 'Claire réfléchit' : isSpeaking ? 'Claire vous répond' : 'Claire · assistante bancaire' }}
          </p>
          <h2 v-if="!messages.length">Bonjour, comment puis-je vous aider ?</h2>
          <p v-else class="stage-sub">
            {{ isRecording ? 'Parlez, je vous écoute.' : isProcessing ? 'Je cherche la meilleure réponse.' : 'Je suis là pour vous accompagner.' }}
          </p>
          <div class="stage-wave" :class="{ live: isRecording || isProcessing || isSpeaking }" aria-hidden="true">
            <i
              v-for="n in 28"
              :key="n"
              :style="{ '--bar': `${6 + ((n * 13) % 22)}px`, '--delay': `${(n % 10) * 0.08}s` }"
            ></i>
          </div>
        </div>

        <div ref="conversation" class="conversation" aria-live="polite" aria-relevant="additions text">
          <div v-if="!messages.length" class="conversation-empty">
            <span class="mono-label">Conversation</span>
            <p>Posez votre question ou choisissez un sujet ci-dessous. Claire vous répond en quelques secondes.</p>
          </div>

          <template v-for="(message, index) in messages" :key="index">
            <article class="message" :class="message.role === 'user' ? 'user' : 'assistant'">
              <div class="message-head">
                <span class="mono-label">{{ message.role === 'user' ? 'Vous' : 'Claire' }}</span>
                <span v-if="message.pending" class="pending-label">transcription…</span>
              </div>
              <p>{{ message.text }}</p>

              <div
                v-if="message.role === 'assistant' && (message.intentLabel || message.ticket || message.sources?.length)"
                class="message-meta"
              >
                <span v-if="message.intentLabel" class="meta-chip mint">{{ message.intentLabel }}</span>
                <span v-if="message.ticket" class="meta-chip ember">Ticket {{ message.ticket.id }}</span>
                <span
                  v-for="source in message.sources"
                  :key="`${index}-${source.label}-${source.title}`"
                  class="meta-chip"
                >
                  {{ source.label }}
                </span>
              </div>

              <div v-if="message.role === 'assistant' && !message.pending && message.text" class="message-actions">
                <button class="listen-button" type="button" @click="replay(message, index)">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M4 9v6h4l5 4V5L8 9H4Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
                    <path d="M16 8.5a5 5 0 0 1 0 7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
                  </svg>
                  Réécouter
                </button>
              </div>

              <audio
                v-if="message.audioUrl"
                :id="`audio-${index}`"
                class="hidden-audio"
                :src="message.audioUrl"
                preload="auto"
              ></audio>
            </article>
          </template>

          <div v-if="isProcessing" class="processing-note">
            <span></span><span></span><span></span>
            L’assistant réfléchit
          </div>
        </div>

        <div class="console-foot">
          <p v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</p>

          <div v-if="suggestions.length" class="suggestions" aria-label="Suggestions">
            <button
              v-for="suggestion in suggestions"
              :key="suggestion"
              class="suggestion-chip"
              type="button"
              @click="sendMessage(suggestion)"
            >
              {{ suggestion }}
            </button>
          </div>

          <div v-if="!messages.length" class="topic-row" aria-label="Exemples de sujets">
            <button
              v-for="topic in topics.slice(0, 3)"
              :key="topic.label"
              class="topic-chip"
              type="button"
              @click="sendMessage(topic.text)"
            >
              {{ topic.label }}
            </button>
          </div>

          <form class="composer" @submit.prevent="sendMessage(textInput)">
            <button
              class="mic-button"
              :class="{ recording: isRecording }"
              :disabled="isProcessing"
              :aria-label="isRecording ? 'Terminer l’enregistrement' : 'Parler à l’assistant'"
              type="button"
              @click="toggleRecording"
            >
              <svg v-if="!isRecording" viewBox="0 0 24 24" aria-hidden="true">
                <rect x="9" y="3" width="6" height="11" rx="3" fill="none" stroke="currentColor" stroke-width="1.8" />
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
              </svg>
              <svg v-else viewBox="0 0 24 24" aria-hidden="true">
                <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
              </svg>
            </button>

            <div class="composer-field">
              <input
                ref="textInputEl"
                v-model="textInput"
                class="text-input"
                type="text"
                maxlength="2000"
                :disabled="isProcessing || isRecording"
                placeholder="Écrivez votre question…"
                aria-label="Votre message"
              />
              <button class="send-button" type="submit" :disabled="!canSend" aria-label="Envoyer le message">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </button>
            </div>
          </form>

          <div class="composer-meta">
            <span class="status-text">
              <span v-if="isRecording" class="rec-dot" aria-hidden="true"></span>
              {{ statusText }}
            </span>
            <button class="reset-button" type="button" @click="resetConversation">Nouvelle conversation</button>
          </div>

          <p class="privacy-note">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="5" y="10" width="14" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5" />
              <path d="M8 10V7a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            </svg>
            Traitement 100 % local sur le Jetson · aucun code secret demandé.
          </p>
        </div>
      </section>
    </section>

    <Spectrogram />

    <section class="section-band" aria-labelledby="capabilities-title">
      <div class="section-inner">
        <div class="section-head">
          <div>
            <span class="mono-label">Ce que Claire sait faire</span>
            <h2 id="capabilities-title">Six parcours, une seule voix.</h2>
          </div>
          <p class="lede">
            Le routage est déterministe, la réponse est ancrée dans la base de connaissances
            locale. Aucun appel ne part vers un service cloud.
          </p>
        </div>

        <div class="capability-grid">
          <article v-for="(capability, index) in capabilities" :key="capability.title" class="capability-item">
            <span class="cap-index">0{{ index + 1 }}</span>
            <h3>{{ capability.title }}</h3>
            <p>{{ capability.description }}</p>
          </article>
        </div>
      </div>
    </section>

    <section id="agences" class="section-band" aria-labelledby="agencies-title">
      <div class="section-inner">
        <div class="section-head">
          <div>
            <span class="mono-label">Vision · affluence en direct</span>
            <h2 id="agencies-title">L’agence la moins fréquentée, en un regard.</h2>
          </div>
          <button class="btn btn-ghost btn-compact" type="button" @click="emit('open-agent')">
            Ouvrir le poste conseiller
            <span aria-hidden="true">→</span>
          </button>
        </div>

        <div v-if="!agencies.length" class="empty-panel">
          Le flux d’affluence n’est pas encore disponible. Lancez le module de vision ou le simulateur.
        </div>
        <div v-else class="agency-grid">
          <article
            v-for="agency in sortedAgencies"
            :key="agency.name"
            class="agency-card panel"
            :class="agency.level"
          >
            <header>
              <div>
                <h3>{{ agency.name }}</h3>
                <p>{{ agency.city }}</p>
              </div>
              <span class="level-chip" :class="agency.level">{{ levelLabel(agency.level) }}</span>
            </header>

            <div class="agency-count">
              <strong>{{ agency.visibles }}</strong>
              <span>personnes</span>
            </div>

            <div class="level-bar" :class="agency.level" aria-hidden="true">
              <i></i><i></i><i></i>
            </div>

            <footer>
              <span :class="{ alert: agency.alerte }">
                {{ agency.alerte ? 'Zone d’alerte' : 'Flux vidéo local' }}
              </span>
              <time>{{ agency.stale ? 'démo' : formatTime(agency.heure) }}</time>
            </footer>
          </article>
        </div>

        <p class="source-note">
          Données produites par le module de comptage YOLO, lues depuis <code>affluence.csv</code>.
          Aucune image n’est envoyée dans le cloud.
        </p>
      </div>
    </section>

    <section id="stack" class="section-band" aria-labelledby="stack-title">
      <div class="section-inner">
        <div class="section-head">
          <div>
            <span class="mono-label">Sous le capot</span>
            <h2 id="stack-title">Une stack vocale qui tient dans la pièce.</h2>
          </div>
          <p class="lede">
            Gemma rédige, Whisper transcrit, la voix locale répond et YOLO compte les visiteurs.
            Le tout sur un seul Jetson Orin Nano.
          </p>
        </div>

        <div class="stack-grid">
          <article v-for="item in stackItems" :key="item.label" class="stack-item">
            <div class="stack-top">
              <span class="mono-label">{{ item.label }}</span>
              <span class="dot" :class="item.ready ? 'mint' : 'ember'"></span>
            </div>
            <h3>{{ item.value }}</h3>
            <p>{{ item.note }}</p>
          </article>
        </div>
      </div>
    </section>

    <footer class="client-footer">
      <span>Banque Claire · Assistant call center</span>
      <span>Prototype AI &amp; Offline · données fictives · aucun code secret demandé</span>
    </footer>
  </main>
</template>

<style scoped>
.client-main {
  flex: 1;
  display: flex;
  flex-direction: column;
}

/* ------------------------------------------------------------
   Hero
   ------------------------------------------------------------ */

.hero {
  width: 100%;
  max-width: var(--page-max);
  margin: 0 auto;
  padding: clamp(36px, 6vw, 76px) var(--page-pad) clamp(28px, 4vw, 48px);
  display: grid;
  grid-template-columns: minmax(0, 1.02fr) minmax(0, 0.98fr);
  align-items: start;
  gap: clamp(32px, 5vw, 64px);
}

.hero-copy {
  padding-top: 6px;
  animation: fade-up 0.55s ease-out both;
}

.hero h1 {
  margin-top: 20px;
  color: var(--cream);
  font-size: clamp(44px, 7vw, 76px);
  font-weight: 300;
  letter-spacing: -0.03em;
  line-height: 1.02;
}

.hero h1 span {
  color: var(--mint);
}

.hero .lede {
  margin-top: 22px;
  max-width: 44ch;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 28px;
}

.trust-row {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 24px;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.trust-row span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.trust-row .dot {
  width: 5px;
  height: 5px;
}

.flow-list {
  display: none;
  margin-top: 26px;
  border-top: 1px solid var(--iron);
}

.flow-list article {
  display: flex;
  gap: 14px;
  padding: 13px 0;
  border-bottom: 1px solid var(--iron);
}

.flow-list .mono-label {
  flex: 0 0 auto;
  padding-top: 2px;
  color: var(--mint);
  font-size: 9px;
}

.flow-list h3 {
  color: var(--cream);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: -0.01em;
  line-height: 1.3;
}

.flow-list p {
  margin-top: 3px;
  color: var(--mercury);
  font-size: 11px;
  line-height: 1.45;
}

.live-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 32px;
  padding: 14px 16px;
  border: 1px solid var(--iron);
  border-left: 2px solid var(--mint);
  border-radius: var(--radius-card);
  background: var(--carbon);
}

.live-banner-copy {
  min-width: 0;
}

.live-banner-copy p {
  margin-top: 6px;
  color: var(--bone);
  font-size: 12px;
  line-height: 1.45;
}

.live-banner-copy strong {
  font-weight: 500;
}

.status-chip,
.level-chip {
  flex: 0 0 auto;
  padding: 4px 8px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 500;
  letter-spacing: 0.06em;
  line-height: 1.3;
  text-transform: uppercase;
  color: var(--mercury);
}

.status-chip.calme,
.level-chip.calme {
  color: var(--mint);
  border-color: rgba(98, 246, 181, 0.32);
}

.status-chip.moderee,
.level-chip.moderee {
  color: var(--cream);
  border-color: var(--steel);
}

.status-chip.forte,
.level-chip.forte,
.status-chip.alert {
  color: var(--ember);
  border-color: rgba(233, 107, 52, 0.4);
}

/* ------------------------------------------------------------
   Console vocale
   ------------------------------------------------------------ */

.voice-console {
  min-width: 0;
  min-height: 620px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: fade-up 0.65s 0.08s ease-out both;
}

.console-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 15px 18px;
  border-bottom: 1px solid var(--iron);
}

.console-identity {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 11px;
}

.avatar {
  width: 36px;
  height: 36px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--mint);
  color: var(--void);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.console-identity h2 {
  color: var(--cream);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.2;
}

.console-identity p {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 3px;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.console-identity .dot {
  width: 5px;
  height: 5px;
}

.console-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.voice-toggle {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 9px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-pill);
  color: var(--cream);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  transition: border-color 0.18s ease, color 0.18s ease;
}

.voice-toggle:hover {
  border-color: var(--mint);
  color: var(--mint);
}

.voice-toggle svg {
  width: 13px;
  height: 13px;
}

.voice-toggle.off {
  color: var(--zinc);
}

.demo-tag {
  padding: 4px 7px;
  border: 1px solid rgba(98, 246, 181, 0.28);
  border-radius: var(--radius-card);
  color: var(--mint);
  font-family: var(--font-mono);
  font-size: 7px;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.console-stage {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 26px 20px 20px;
  border-bottom: 1px solid var(--iron);
  text-align: center;
}

.console-stage :deep(.voice-orb) {
  width: 180px;
  height: 180px;
}

.stage-kicker {
  margin-top: 12px;
  color: var(--mint);
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 500;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.console-stage h2 {
  max-width: 22ch;
  margin-top: 9px;
  color: var(--cream);
  font-size: clamp(20px, 2.2vw, 25px);
  font-weight: 300;
  letter-spacing: -0.02em;
  line-height: 1.15;
}

.stage-sub {
  max-width: 32ch;
  margin-top: 7px;
  color: var(--mercury);
  font-size: 12px;
  line-height: 1.5;
}

.stage-wave {
  height: 26px;
  display: flex;
  align-items: center;
  gap: 3px;
  margin-top: 14px;
  opacity: 0.55;
}

.stage-wave i {
  width: 2px;
  height: var(--bar);
  display: block;
  border-radius: 2px;
  background: var(--mint);
  transform-origin: center;
}

.stage-wave.live {
  opacity: 1;
}

.stage-wave.live i {
  animation: wave 1s ease-in-out infinite;
  animation-delay: var(--delay);
}

.conversation {
  min-height: 160px;
  max-height: 300px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  padding: 16px 18px 8px;
  scroll-behavior: smooth;
}

.conversation-empty {
  padding: 14px 15px;
  border: 1px dashed var(--iron);
  border-radius: var(--radius-card);
  text-align: left;
}

.conversation-empty p {
  margin-top: 7px;
  color: var(--mercury);
  font-size: 12px;
  line-height: 1.5;
}

.message {
  max-width: 94%;
  padding: 12px 14px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  background: var(--carbon);
  animation: fade-up 0.25s ease-out both;
}

.message.assistant {
  border-left: 2px solid var(--mint);
}

.message.user {
  align-self: flex-end;
  border-color: var(--steel);
  background: var(--slab);
}

.message-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}

.message-head .mono-label {
  font-size: 8px;
}

.message p {
  color: var(--bone);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.message.user p {
  color: var(--cream);
}

.pending-label {
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 8px;
  text-transform: uppercase;
}

.message-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 9px;
}

.meta-chip {
  padding: 3px 6px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 7px;
  letter-spacing: 0.04em;
  line-height: 1.3;
  text-transform: uppercase;
}

.meta-chip.mint {
  color: var(--mint);
  border-color: rgba(98, 246, 181, 0.3);
}

.meta-chip.ember {
  color: var(--ember);
  border-color: rgba(233, 107, 52, 0.34);
}

.message-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 9px;
}

.listen-button {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0;
  color: var(--mint);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.listen-button:hover {
  text-decoration: underline;
  text-underline-offset: 2px;
}

.listen-button svg {
  width: 12px;
  height: 12px;
}

.processing-note {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 2px 0 4px 3px;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.processing-note span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--mint);
  animation: pulse 1s infinite alternate;
}

.processing-note span:nth-child(2) {
  animation-delay: 0.2s;
}

.processing-note span:nth-child(3) {
  margin-right: 4px;
  animation-delay: 0.4s;
}

.console-foot {
  margin-top: auto;
  padding: 14px 18px 16px;
  border-top: 1px solid var(--iron);
  background: var(--carbon);
}

.error-message {
  margin-bottom: 10px;
  color: var(--ember);
  font-size: 11px;
  line-height: 1.45;
}

.suggestions,
.topic-row {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: none;
}

.suggestions::-webkit-scrollbar,
.topic-row::-webkit-scrollbar {
  display: none;
}

.suggestion-chip,
.topic-chip {
  min-height: 36px;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  padding: 8px 11px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-pill);
  color: var(--mercury);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.04em;
  line-height: 1.2;
  text-transform: uppercase;
  transition: border-color 0.18s ease, color 0.18s ease;
}

.suggestion-chip:hover,
.topic-chip:hover {
  border-color: var(--mint);
  color: var(--mint);
}

.topic-chip {
  color: var(--zinc);
}

.composer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mic-button {
  width: 52px;
  height: 52px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--mint);
  color: var(--void);
  transition: background-color 0.18s ease, transform 0.18s ease;
}

.mic-button:hover:not(:disabled) {
  background: #83f8c8;
  transform: translateY(-1px);
}

.mic-button:disabled {
  opacity: 0.5;
  cursor: wait;
}

.mic-button svg {
  width: 22px;
  height: 22px;
}

.mic-button.recording {
  background: var(--ember);
  color: var(--cream);
  animation: ring 1.7s infinite;
}

.composer-field {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 4px 4px 15px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-pill);
  background: var(--void);
  transition: border-color 0.18s ease;
}

.composer-field:focus-within {
  border-color: rgba(98, 246, 181, 0.55);
}

.text-input {
  min-width: 0;
  flex: 1;
  padding: 8px 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--cream);
  font-size: 12px;
}

.text-input::placeholder {
  color: var(--zinc);
}

.send-button {
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--ember);
  color: var(--cream);
  transition: background-color 0.18s ease, opacity 0.18s ease;
}

.send-button:hover:not(:disabled) {
  background: #f17b47;
}

.send-button:disabled {
  opacity: 0.32;
  cursor: not-allowed;
}

.send-button svg {
  width: 17px;
  height: 17px;
}

.composer-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 9px;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.status-text {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.rec-dot {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--ember);
  animation: pulse 0.7s infinite alternate;
}

.reset-button {
  min-height: 36px;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  padding: 0;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.04em;
  text-decoration: underline;
  text-underline-offset: 2px;
  text-transform: uppercase;
}

.reset-button:hover {
  color: var(--cream);
}

.privacy-note {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 9px;
  color: var(--zinc);
  font-size: 9px;
  line-height: 1.4;
}

.privacy-note svg {
  width: 11px;
  height: 11px;
  flex: 0 0 auto;
}

/* ------------------------------------------------------------
   Sections
   ------------------------------------------------------------ */

.section-band {
  border-top: 1px solid var(--iron);
}

.section-inner {
  width: 100%;
  max-width: var(--page-max);
  margin: 0 auto;
  padding: var(--section-gap) var(--page-pad);
}

.capability-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0 32px;
}

.capability-item {
  padding: 18px 0 22px;
  border-top: 1px solid var(--iron);
}

.cap-index {
  display: block;
  margin-bottom: 16px;
  color: var(--mint);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.08em;
}

.capability-item h3 {
  color: var(--cream);
  font-size: 17px;
  font-weight: 500;
  letter-spacing: -0.01em;
  line-height: 1.25;
}

.capability-item p {
  max-width: 34ch;
  margin-top: 8px;
  color: var(--mercury);
  font-size: 12px;
  line-height: 1.55;
}

.agency-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.agency-card {
  min-width: 0;
  padding: 16px;
  transition: border-color 0.18s ease;
}

.agency-card:hover {
  border-color: var(--steel);
}

.agency-card.forte {
  border-color: rgba(233, 107, 52, 0.32);
}

.agency-card header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.agency-card h3 {
  color: var(--cream);
  font-size: 14px;
  font-weight: 500;
  letter-spacing: -0.01em;
  line-height: 1.25;
}

.agency-card header p {
  margin-top: 3px;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.agency-count {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 22px;
}

.agency-count strong {
  color: var(--cream);
  font-size: 44px;
  font-weight: 300;
  letter-spacing: -0.04em;
  line-height: 0.9;
}

.agency-card.forte .agency-count strong {
  color: var(--ember);
}

.agency-count span {
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.level-bar {
  display: flex;
  gap: 3px;
  margin-top: 18px;
}

.level-bar i {
  height: 3px;
  flex: 1;
  border-radius: 2px;
  background: var(--steel);
}

.level-bar.calme i:first-child {
  background: var(--mint);
}

.level-bar.moderee i:nth-child(-n + 2) {
  background: var(--cream);
}

.level-bar.forte i {
  background: var(--ember);
}

.agency-card footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 12px;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.agency-card footer .alert {
  color: var(--ember);
}

.agency-card footer time {
  color: var(--zinc);
}

.source-note {
  margin-top: 16px;
  color: var(--mercury);
  font-size: 10px;
  line-height: 1.5;
}

.source-note code {
  padding: 1px 4px;
  border: 1px solid var(--iron);
  border-radius: 3px;
  color: var(--mercury);
  font-family: var(--font-mono);
  font-size: 9px;
}

.empty-panel {
  padding: 22px;
  border: 1px dashed var(--iron);
  border-radius: var(--radius-card);
  color: var(--zinc);
  font-size: 12px;
  line-height: 1.5;
}

.stack-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0 28px;
}

.stack-item {
  padding: 16px 0 20px;
  border-top: 1px solid var(--iron);
}

.stack-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.stack-top .dot {
  width: 5px;
  height: 5px;
}

.stack-item h3 {
  margin-top: 20px;
  color: var(--cream);
  font-size: 16px;
  font-weight: 500;
  letter-spacing: -0.01em;
  line-height: 1.3;
}

.stack-item p {
  margin-top: 7px;
  color: var(--mercury);
  font-size: 11px;
  line-height: 1.5;
}

.client-footer {
  width: 100%;
  max-width: var(--page-max);
  margin: 0 auto;
  padding: 22px var(--page-pad) 28px;
  border-top: 1px solid var(--iron);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.04em;
  line-height: 1.5;
  text-transform: uppercase;
}

/* ------------------------------------------------------------
   Animations
   ------------------------------------------------------------ */

@keyframes fade-up {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes wave {
  0%,
  100% {
    transform: scaleY(0.55);
  }
  50% {
    transform: scaleY(1.35);
  }
}

@keyframes pulse {
  from {
    opacity: 0.45;
    transform: scale(0.85);
  }
  to {
    opacity: 1;
    transform: scale(1.1);
  }
}

@keyframes ring {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(233, 107, 52, 0.25);
  }
  50% {
    box-shadow: 0 0 0 9px rgba(233, 107, 52, 0);
  }
}

/* ------------------------------------------------------------
   Responsive
   ------------------------------------------------------------ */

@media (min-width: 981px) {
  .flow-list {
    display: block;
  }
}

@media (max-width: 1080px) {
  .agency-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .stack-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 980px) {
  .hero {
    grid-template-columns: 1fr;
    gap: 34px;
  }

  .hero-copy {
    max-width: 640px;
  }

  .voice-console {
    width: 100%;
    max-width: 640px;
    margin: 0 auto;
    min-height: 0;
  }
}

@media (max-width: 760px) {
  .hero {
    padding-top: 28px;
    padding-bottom: 24px;
  }

  .hero h1 {
    margin-top: 14px;
    font-size: clamp(40px, 12vw, 54px);
  }

  .hero .lede {
    margin-top: 16px;
    font-size: 14px;
  }

  .hero-actions {
    margin-top: 22px;
  }

  .hero-actions .btn {
    flex: 1 1 100%;
  }

  .trust-row {
    gap: 12px;
    margin-top: 18px;
  }

  .live-banner {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
    margin-top: 24px;
  }

  .console-head {
    padding: 13px 14px;
  }

  .voice-toggle {
    min-height: 40px;
    padding: 8px 11px;
  }

  .suggestion-chip,
  .topic-chip {
    min-height: 40px;
    padding: 9px 12px;
  }

  /* Les exemples de sujets passent à la ligne au lieu de déborder. */
  .topic-row {
    flex-wrap: wrap;
    overflow-x: visible;
  }

  .reset-button {
    min-height: 36px;
  }

  .listen-button {
    min-height: 36px;
  }

  /* 16 px évite le zoom automatique de Safari iOS sur les champs. */
  .text-input {
    font-size: 16px;
  }

  .console-stage {
    padding: 20px 14px 16px;
  }

  .console-stage :deep(.voice-orb) {
    width: 150px;
    height: 150px;
  }

  .console-stage h2 {
    font-size: 21px;
  }

  .conversation {
    max-height: 280px;
    padding: 14px 14px 6px;
  }

  .console-foot {
    padding: 12px 14px 14px;
  }

  .mic-button {
    width: 48px;
    height: 48px;
  }

  .mic-button svg {
    width: 20px;
    height: 20px;
  }

  .composer-field {
    padding-left: 12px;
  }

  .text-input {
    font-size: 13px;
  }

  .composer-meta {
    font-size: 7px;
  }

  .privacy-note {
    font-size: 8px;
  }

  .section-inner {
    padding-top: 42px;
    padding-bottom: 42px;
  }

  .capability-grid {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .capability-item {
    padding: 16px 0 18px;
  }

  .agency-grid {
    grid-template-columns: 1fr;
  }

  .agency-count strong {
    font-size: 40px;
  }

  .stack-grid {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .client-footer {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
    padding-top: 18px;
    padding-bottom: 24px;
  }
}

@media (max-width: 420px) {
  .voice-toggle span,
  .demo-tag {
    display: none;
  }

  .console-stage :deep(.voice-orb) {
    width: 132px;
    height: 132px;
  }

  .composer-meta {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }

  .reset-button {
    align-self: flex-end;
  }
}
</style>
