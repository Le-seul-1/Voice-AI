<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { API_URL, readJson } from '../api'

const props = defineProps({
  runtime: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['back'])

const EMPTY_STATS = {
  total_conversations: 0,
  bot_handled: 0,
  escalated: 0,
  open_tickets: 0,
  resolved_tickets: 0,
  by_intent: [],
}

const stats = ref({ ...EMPTY_STATS })
const conversations = ref([])
const tickets = ref([])
const affluence = ref([])
const selectedId = ref('')
const errorMessage = ref('')
const isRefreshing = ref(false)

let refreshTimer

const INTENT_LABELS = {
  compte: 'Ouverture de compte',
  carte: 'Carte bancaire',
  credit: 'Crédit',
  agence: 'Agence',
  reclamation: 'Réclamation',
  produit: 'Produits et services',
  salutation: 'Salutation',
  autre: 'Demande générale',
  conseiller: 'Transfert conseiller',
}

const STATUS_LABELS = {
  bot: 'Traité par l’IA',
  escalated: 'À rappeler',
  human: 'Conseiller',
  ouvert: 'Ouvert',
  resolu: 'Résolu',
  normale: 'Normale',
  haute: 'Haute',
  carte: 'Carte',
  reclamation: 'Réclamation',
  conseiller: 'Conseiller',
}

const MINT_INTENTS = new Set(['compte', 'carte', 'credit', 'agence', 'produit'])

const selectedConversation = computed(
  () => conversations.value.find((conversation) => conversation.id === selectedId.value) || null,
)

const resolutionRate = computed(() => {
  const total = stats.value.total_conversations || 0
  if (!total) return 0
  return Math.round((stats.value.bot_handled / total) * 100)
})

const modelLabel = computed(() => {
  const raw = String(props.runtime?.model || '').trim()
  if (!raw) return 'Gemma'
  const [family, tag] = raw.split(':')
  const prettyFamily = family
    .replace(/^gemma[\s-]*(\d+(?:\.\d+)?)/i, 'Gemma $1')
    .replace(/[\s_-]+/g, ' ')
    .trim()
  const normalizedFamily = prettyFamily
    ? prettyFamily.charAt(0).toUpperCase() + prettyFamily.slice(1)
    : 'Gemma'
  const prettyTag = tag ? tag.replace(/[-_]/g, ' ').toUpperCase() : ''
  return `${normalizedFamily}${prettyTag ? ` ${prettyTag}` : ''}`
})

const intentRows = computed(() => {
  const rows = Array.isArray(stats.value.by_intent) ? stats.value.by_intent : []
  const max = Math.max(1, ...rows.map((row) => Number(row.count) || 0))
  return rows.map((row) => {
    const count = Number(row.count) || 0
    return {
      key: row.intent || 'autre',
      label: intentLabel(row.intent),
      count,
      width: `${Math.max(3, Math.round((count / max) * 100))}%`,
      tone: row.intent === 'reclamation' ? 'ember' : MINT_INTENTS.has(row.intent) ? 'mint' : 'zinc',
    }
  })
})

function normalizeStats(payload) {
  const safe = payload && typeof payload === 'object' ? payload : {}
  return {
    ...EMPTY_STATS,
    ...safe,
    total_conversations: Number(safe.total_conversations) || 0,
    bot_handled: Number(safe.bot_handled) || 0,
    escalated: Number(safe.escalated) || 0,
    open_tickets: Number(safe.open_tickets) || 0,
    resolved_tickets: Number(safe.resolved_tickets) || 0,
    by_intent: Array.isArray(safe.by_intent) ? safe.by_intent : [],
  }
}

function intentLabel(intent) {
  return INTENT_LABELS[intent] || 'Demande générale'
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status || '—'
}

function typeLabel(type) {
  return STATUS_LABELS[type] || type || '—'
}

function shortId(id) {
  return id ? id.replace('ses-', '').slice(0, 8).toUpperCase() : '—'
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

function formatDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function levelLabel(level) {
  return { calme: 'Calme', moderee: 'Modérée', forte: 'Forte', inconnu: 'Inconnue' }[level] || '—'
}

async function loadAll() {
  if (isRefreshing.value) return
  isRefreshing.value = true
  errorMessage.value = ''

  const requests = await Promise.allSettled([
    fetch(`${API_URL}/api/agent/stats`).then(readJson),
    fetch(`${API_URL}/api/agent/conversations?limit=50`).then(readJson),
    fetch(`${API_URL}/api/agent/tickets?limit=50`).then(readJson),
    fetch(`${API_URL}/api/affluence`).then(readJson),
  ])

  if (requests[0].status === 'fulfilled') stats.value = normalizeStats(requests[0].value)
  if (requests[1].status === 'fulfilled') {
    conversations.value = Array.isArray(requests[1].value.conversations)
      ? requests[1].value.conversations
      : []
    if (!conversations.value.some((conversation) => conversation.id === selectedId.value)) {
      selectedId.value = conversations.value[0]?.id || ''
    }
  }
  if (requests[2].status === 'fulfilled') {
    tickets.value = Array.isArray(requests[2].value.tickets) ? requests[2].value.tickets : []
  }
  if (requests[3].status === 'fulfilled') {
    affluence.value = Array.isArray(requests[3].value.agencies) ? requests[3].value.agencies : []
  }

  const failure = requests.find((request) => request.status === 'rejected')
  if (failure) errorMessage.value = failure.reason?.message || 'Impossible de charger les données.'

  isRefreshing.value = false
}

async function resolveTicket(ticketId) {
  errorMessage.value = ''
  try {
    const response = await fetch(`${API_URL}/api/agent/tickets/${ticketId}/resolve`, { method: 'POST' })
    await readJson(response)
    await loadAll()
  } catch (error) {
    errorMessage.value = error.message || 'Impossible de résoudre ce ticket.'
  }
}

onMounted(() => {
  loadAll()
  refreshTimer = window.setInterval(loadAll, 5000)
})

onBeforeUnmount(() => {
  window.clearInterval(refreshTimer)
})
</script>

<template>
  <main class="agent">
    <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">
      {{ stats.total_conversations }} appels reçus · {{ stats.open_tickets }} tickets ouverts
    </p>

    <section class="hero" aria-labelledby="agent-title">
      <div class="hero-copy">
        <p class="eyebrow">
          <span class="dot mint" aria-hidden="true"></span>
          Poste conseiller · Supervision en direct
        </p>
        <h1 id="agent-title" class="hero-title">
          Vue d’ensemble<span class="title-dot">.</span>
        </h1>
        <p class="lede hero-lede">
          Appels, tickets et affluence des agences — une console locale, sans cloud.
        </p>
        <p class="mono-label stack-line">
          <span class="dot mint" aria-hidden="true"></span>
          <span>{{ modelLabel }} · Whisper · SQLite local</span>
        </p>
      </div>

      <div class="hero-actions">
        <button
          class="btn btn-mint"
          type="button"
          :disabled="isRefreshing"
          :aria-busy="isRefreshing"
          :aria-label="isRefreshing ? 'Actualisation en cours' : 'Actualiser les données du poste conseiller'"
          @click="loadAll"
        >
          {{ isRefreshing ? 'Actualisation…' : 'Actualiser' }}
        </button>
        <button
          class="btn btn-ember"
          type="button"
          aria-label="Revenir à l’espace client"
          @click="emit('back')"
        >
          Espace client <span aria-hidden="true">→</span>
        </button>
      </div>
    </section>

    <p v-if="errorMessage" class="error-banner" role="alert">{{ errorMessage }}</p>

    <section
      class="stats-grid"
      aria-label="Indicateurs du poste conseiller"
      :aria-busy="isRefreshing"
    >
      <article class="stat-card">
        <span class="stat-label">Appels reçus</span>
        <strong class="stat-value">{{ stats.total_conversations }}</strong>
        <span class="stat-note">depuis le démarrage</span>
      </article>
      <article class="stat-card is-mint">
        <span class="stat-label">Traités par l’IA</span>
        <strong class="stat-value">{{ stats.bot_handled }}</strong>
        <span class="stat-note">{{ resolutionRate }} % de résolution</span>
      </article>
      <article class="stat-card is-ember">
        <span class="stat-label">À rappeler</span>
        <strong class="stat-value">{{ stats.escalated }}</strong>
        <span class="stat-note">conversations escaladées</span>
      </article>
      <article class="stat-card">
        <span class="stat-label">Tickets ouverts</span>
        <strong class="stat-value">{{ stats.open_tickets }}</strong>
        <span class="stat-note">{{ stats.resolved_tickets }} résolu(s)</span>
      </article>
    </section>

    <section v-if="intentRows.length" class="panel intent-panel" aria-labelledby="intent-title">
      <div class="intent-head">
        <div>
          <p class="mono-label">Répartition</p>
          <h2 id="intent-title" class="panel-title">Demandes par motif</h2>
        </div>
        <span class="mono-label intent-total">{{ stats.total_conversations }} appels</span>
      </div>
      <ul class="intent-list">
        <li v-for="row in intentRows" :key="row.key" class="intent-row">
          <span class="intent-label">{{ row.label }}</span>
          <span class="intent-track" aria-hidden="true">
            <span class="intent-bar" :class="`tone-${row.tone}`" :style="{ width: row.width }"></span>
          </span>
          <span class="intent-count">
            {{ row.count }}<span class="sr-only"> appels</span>
          </span>
        </li>
      </ul>
    </section>

    <div class="workspace">
      <section class="panel conversations-panel" aria-labelledby="conversations-title">
        <div class="panel-head">
          <div>
            <p class="mono-label">Flux d’appels</p>
            <h2 id="conversations-title" class="panel-title">Conversations</h2>
          </div>
          <span class="count-badge">
            {{ conversations.length }}<span class="sr-only"> conversations</span>
          </span>
        </div>

        <p v-if="!conversations.length" class="empty-note">Aucun appel pour le moment.</p>
        <div v-else class="conversation-list">
          <button
            v-for="conversation in conversations"
            :key="conversation.id"
            class="conversation-item"
            :class="{ active: conversation.id === selectedId }"
            type="button"
            :aria-current="conversation.id === selectedId ? 'true' : undefined"
            @click="selectedId = conversation.id"
          >
            <span class="conversation-top">
              <span class="mono-label conversation-id">{{ shortId(conversation.id) }}</span>
              <span class="status-badge" :class="conversation.status">
                {{ statusLabel(conversation.status) }}
              </span>
            </span>
            <span class="conversation-intent">{{ intentLabel(conversation.intent) }}</span>
            <span class="conversation-preview">
              {{ conversation.last_message || conversation.summary || 'Aucun message' }}
            </span>
            <span class="conversation-time">{{ formatTime(conversation.updated_at) }}</span>
          </button>
        </div>
      </section>

      <section class="panel detail-panel" aria-label="Détail de la conversation">
        <template v-if="selectedConversation">
          <div class="detail-head" aria-live="polite" aria-atomic="true">
            <div class="detail-heading">
              <p class="mono-label detail-meta">
                {{ shortId(selectedConversation.id) }} ·
                {{ formatDateTime(selectedConversation.updated_at) }}
              </p>
              <h2 id="detail-title" class="panel-title detail-title">
                {{ intentLabel(selectedConversation.intent) }}
              </h2>
            </div>
            <span class="status-badge" :class="selectedConversation.status">
              {{ statusLabel(selectedConversation.status) }}
            </span>
          </div>

          <div
            v-if="selectedConversation.transcript?.length"
            class="transcript"
            role="group"
            aria-label="Transcription de l’appel"
          >
            <div
              v-for="(message, index) in selectedConversation.transcript"
              :key="index"
              class="transcript-row"
              :class="message.role"
            >
              <span class="transcript-role mono-label">
                {{ message.role === 'user' ? 'Client' : 'Assistant' }}
              </span>
              <p>{{ message.text }}</p>
            </div>
          </div>
          <p v-else class="empty-note detail-empty">Transcription indisponible.</p>

          <div v-if="selectedConversation.ticket" class="ticket-card">
            <div class="ticket-card-top">
              <span class="mono-label ticket-label">
                Ticket {{ selectedConversation.ticket.id }}
              </span>
              <span class="status-badge" :class="selectedConversation.ticket.status">
                {{ statusLabel(selectedConversation.ticket.status) }}
              </span>
            </div>
            <p class="ticket-summary">{{ selectedConversation.ticket.summary }}</p>
            <p
              v-if="selectedConversation.ticket.suggested_response"
              class="suggested-response"
            >
              <span class="mono-label suggested-label">Réponse suggérée</span>
              <span>{{ selectedConversation.ticket.suggested_response }}</span>
            </p>
            <button
              v-if="selectedConversation.ticket.status === 'ouvert'"
              class="btn btn-ember resolve-button"
              type="button"
              :aria-label="`Marquer comme résolu le ticket ${selectedConversation.ticket.id}`"
              @click="resolveTicket(selectedConversation.ticket.id)"
            >
              Marquer comme résolu
            </button>
          </div>
          <p v-else class="empty-note detail-empty">Aucun ticket associé à cet appel.</p>
        </template>

        <div v-else class="empty-state">
          <span class="empty-mark" aria-hidden="true">◌</span>
          <p>Sélectionnez une conversation pour voir la transcription.</p>
        </div>
      </section>
    </div>
    <div class="bottom-grid">
      <section class="panel tickets-panel" aria-labelledby="tickets-title">
        <div class="panel-head">
          <div>
            <p class="mono-label">Suivi</p>
            <h2 id="tickets-title" class="panel-title">Tickets récents</h2>
          </div>
          <span class="count-badge">
            {{ tickets.length }}<span class="sr-only"> tickets</span>
          </span>
        </div>

        <p v-if="!tickets.length" class="empty-note">Aucun ticket pour le moment.</p>
        <div v-else class="ticket-list">
          <article v-for="ticket in tickets.slice(0, 8)" :key="ticket.id" class="ticket-row">
            <div class="ticket-row-top">
              <span class="mono-label ticket-id">{{ ticket.id }}</span>
              <span class="priority-badge" :class="ticket.priority">
                {{ statusLabel(ticket.priority) }}
              </span>
              <span class="status-badge" :class="ticket.status">
                {{ statusLabel(ticket.status) }}
              </span>
            </div>
            <p class="ticket-row-summary">{{ ticket.summary }}</p>
            <div class="ticket-row-foot">
              <span class="mono-label ticket-meta">
                {{ typeLabel(ticket.type) }} · {{ formatTime(ticket.created_at) }}
              </span>
              <button
                v-if="ticket.status === 'ouvert'"
                class="link-button"
                type="button"
                :aria-label="`Résoudre le ticket ${ticket.id}`"
                @click="resolveTicket(ticket.id)"
              >
                Résoudre
              </button>
            </div>
          </article>
        </div>
      </section>

      <section class="panel affluence-panel" aria-labelledby="affluence-title">
        <div class="panel-head">
          <div>
            <p class="mono-label">Vision locale</p>
            <h2 id="affluence-title" class="panel-title">Affluence des agences</h2>
          </div>
          <span class="live-pill">
            <span class="live-dot" aria-hidden="true"></span>
            Live
          </span>
        </div>

        <p v-if="!affluence.length" class="empty-note">Aucune donnée d’affluence.</p>
        <div v-else class="affluence-list">
          <article
            v-for="agency in affluence"
            :key="agency.name"
            class="affluence-row"
            :class="agency.level"
          >
            <div class="agency-top">
              <div class="agency-name">
                <strong>{{ agency.name }}</strong>
                <span>{{ agency.city }}</span>
              </div>
              <div class="agency-count">
                <strong>{{ agency.visibles }}</strong>
                <span aria-hidden="true">pers.</span>
                <span class="sr-only">personnes visibles</span>
              </div>
            </div>

            <div class="level-bar" aria-hidden="true">
              <span
                class="level-seg seg-mint"
                :class="{ on: agency.level !== 'inconnu' }"
              ></span>
              <span
                class="level-seg seg-cream"
                :class="{ on: agency.level === 'moderee' || agency.level === 'forte' }"
              ></span>
              <span class="level-seg seg-ember" :class="{ on: agency.level === 'forte' }"></span>
            </div>

            <div class="agency-meta">
              <span class="level-badge" :class="agency.level">{{ levelLabel(agency.level) }}</span>
              <span v-if="agency.alerte" class="alert-badge">Zone d’alerte</span>
              <span class="mono-label affluence-time">
                {{ agency.stale ? 'démo' : formatTime(agency.heure) }}
              </span>
            </div>
          </article>
        </div>
        <p class="affluence-note">CSV produit par le module de vision local.</p>
      </section>
    </div>

    <footer class="agent-footer">
      <span>Banque Claire · Poste conseiller</span>
      <span>Prototype AI &amp; Offline · données fictives</span>
    </footer>
  </main>
</template>

<style scoped>
.agent {
  width: 100%;
  max-width: var(--page-max);
  flex: 1;
  margin: 0 auto;
  padding: 28px var(--page-pad) 40px;
}

.hero {
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding-bottom: 26px;
  border-bottom: 1px solid var(--iron);
}

.hero-copy {
  min-width: 0;
}

.hero .eyebrow {
  margin-bottom: 14px;
}

.hero-title {
  color: var(--cream);
  font-size: clamp(38px, 6vw, 56px);
  font-weight: 300;
  letter-spacing: -0.025em;
  line-height: 1.02;
}

.title-dot {
  color: var(--mint);
}

.hero-lede {
  max-width: 54ch;
  margin-top: 14px;
}

.hero .stack-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 18px;
  color: var(--mercury);
  font-size: 10px;
}

.stack-line .dot {
  width: 5px;
  height: 5px;
}

.hero-actions {
  display: grid;
  gap: 10px;
}

.hero-actions .btn {
  width: 100%;
  min-height: 48px;
}

.error-banner {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid var(--iron);
  border-left: 2px solid var(--ember);
  border-radius: var(--radius-card);
  background: var(--ember-soft);
  color: var(--cream);
  font-size: 13px;
  line-height: 1.5;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 20px;
}

.stat-card {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  background: var(--carbon);
}

.stat-label {
  display: block;
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.08em;
  line-height: 1.4;
  text-transform: uppercase;
}

.stat-value {
  display: block;
  margin: 10px 0 4px;
  color: var(--cream);
  font-size: clamp(44px, 8vw, 52px);
  font-weight: 300;
  letter-spacing: -0.03em;
  line-height: 0.95;
  font-variant-numeric: tabular-nums;
}

.stat-card.is-mint .stat-value {
  color: var(--mint);
}

.stat-card.is-ember .stat-value {
  color: var(--ember);
}

.stat-note {
  display: block;
  color: var(--zinc);
  font-size: 12px;
  line-height: 1.4;
}

.intent-panel {
  margin-top: 14px;
  padding: 16px;
}

.intent-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.intent-total {
  flex: 0 0 auto;
  color: var(--zinc);
  font-size: 10px;
}

.intent-list {
  display: grid;
  gap: 9px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.intent-row {
  display: grid;
  grid-template-columns: minmax(76px, 1.1fr) minmax(0, 1.8fr) 24px;
  align-items: center;
  gap: 9px;
}

.intent-label {
  overflow: hidden;
  color: var(--mercury);
  font-size: 12px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.intent-track {
  height: 6px;
  overflow: hidden;
  border-radius: var(--radius-card);
  background: var(--iron);
}

.intent-bar {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--zinc);
  transition: width 0.3s ease;
}

.tone-mint {
  background: var(--mint);
}

.tone-ember {
  background: var(--ember);
}

.tone-zinc {
  background: var(--zinc);
}

.intent-count {
  color: var(--mercury);
  font-family: var(--font-mono);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.workspace {
  display: grid;
  grid-template-columns: 1fr;
  align-items: start;
  gap: 14px;
  margin-top: 14px;
}

.conversations-panel,
.detail-panel {
  min-width: 0;
  overflow: hidden;
}

.detail-panel {
  min-height: 320px;
}

.panel-head {
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--iron);
}

.panel-head .mono-label {
  color: var(--zinc);
  font-size: 10px;
}

.panel-title {
  margin-top: 4px;
  color: var(--cream);
  font-size: 18px;
  font-weight: 300;
  letter-spacing: -0.01em;
  line-height: 1.15;
}

.count-badge {
  min-width: 26px;
  padding: 4px 8px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  background: var(--slab);
  color: var(--mercury);
  font-family: var(--font-mono);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
  text-align: center;
}

.live-pill {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 6px;
  padding: 4px 8px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  background: var(--slab);
  color: var(--mint);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.08em;
  line-height: 1.2;
  text-transform: uppercase;
}

.live-dot {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--mint);
}

.conversation-list {
  max-height: 300px;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.conversation-item {
  width: 100%;
  min-height: 44px;
  display: grid;
  gap: 5px;
  padding: 13px 14px;
  border: 0;
  border-bottom: 1px solid var(--iron);
  border-left: 2px solid transparent;
  background: transparent;
  color: var(--cream);
  text-align: left;
  transition:
    background-color 0.18s ease,
    border-color 0.18s ease;
}

.conversation-item:last-child {
  border-bottom: 0;
}

.conversation-item:hover {
  background: var(--slab);
}

.conversation-item.active {
  border-left-color: var(--mint);
  background: var(--slab);
}

.conversation-item:focus-visible {
  outline-offset: -3px;
}

.conversation-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.conversation-id {
  color: var(--zinc);
  font-size: 10px;
}

.conversation-intent {
  overflow: hidden;
  color: var(--cream);
  font-size: 15px;
  font-weight: 500;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-preview {
  display: -webkit-box;
  overflow: hidden;
  color: var(--mercury);
  font-size: 13px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.conversation-time {
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  line-height: 1.2;
}

.status-badge,
.priority-badge {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  padding: 3px 7px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  background: var(--slab);
  color: var(--mercury);
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.08em;
  line-height: 1.3;
  text-transform: uppercase;
  white-space: nowrap;
}

.status-badge.bot,
.status-badge.resolu {
  background: var(--mint-soft);
  color: var(--mint);
}

.status-badge.escalated,
.status-badge.ouvert,
.status-badge.haute,
.priority-badge.haute {
  background: var(--ember-soft);
  color: var(--ember);
}

.status-badge.human {
  border-color: var(--steel);
  background: var(--slab);
  color: var(--cream);
}

.priority-badge.normale {
  color: var(--zinc);
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid var(--iron);
}

.detail-heading {
  min-width: 0;
}

.detail-meta {
  overflow: hidden;
  color: var(--zinc);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-title {
  margin-top: 5px;
  font-size: 20px;
}

.transcript {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 320px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 16px;
}

.transcript-row {
  max-width: 92%;
  padding: 10px 12px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  background: var(--slab);
}

.transcript-row.assistant {
  align-self: flex-start;
  background: transparent;
}

.transcript-row.user {
  align-self: flex-end;
}

.transcript-role {
  display: block;
  margin-bottom: 4px;
  color: var(--zinc);
  font-size: 9px;
}

.transcript-row.user .transcript-role {
  color: var(--mint);
}

.transcript-row p {
  color: var(--bone);
  font-size: 14px;
  line-height: 1.55;
}

.ticket-card {
  margin: 0 16px 16px;
  padding: 14px;
  border: 1px solid var(--ember);
  border-radius: var(--radius-card);
  background: var(--carbon);
}

.ticket-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.ticket-label {
  color: var(--ember);
  font-size: 10px;
}

.ticket-summary {
  margin-top: 10px;
  color: var(--bone);
  font-size: 14px;
  line-height: 1.5;
}

.suggested-response {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  background: var(--slab);
  color: var(--mercury);
  font-size: 13px;
  line-height: 1.5;
}

.suggested-label {
  display: block;
  margin-bottom: 4px;
  color: var(--ember);
  font-size: 9px;
}

.resolve-button {
  width: 100%;
  min-height: 44px;
  margin-top: 12px;
}

.empty-note {
  padding: 18px 16px;
  color: var(--zinc);
  font-size: 13px;
  line-height: 1.5;
}

.detail-empty {
  border-top: 1px solid var(--iron);
}

.empty-state {
  min-height: 300px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 10px;
  padding: 28px;
  color: var(--zinc);
  text-align: center;
}

.empty-mark {
  color: var(--steel);
  font-size: 32px;
  line-height: 1;
}

.empty-state p {
  max-width: 240px;
  font-size: 13px;
  line-height: 1.5;
}

.bottom-grid {
  display: grid;
  grid-template-columns: 1fr;
  align-items: start;
  gap: 14px;
  margin-top: 14px;
}

.tickets-panel,
.affluence-panel {
  min-width: 0;
  overflow: hidden;
}

.ticket-list {
  max-height: 380px;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.ticket-row {
  padding: 13px 16px;
  border-bottom: 1px solid var(--iron);
}

.ticket-row:last-child {
  border-bottom: 0;
}

.ticket-row-top {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.ticket-id {
  margin-right: auto;
  color: var(--mercury);
  font-size: 10px;
}

.ticket-row-summary {
  display: -webkit-box;
  overflow: hidden;
  margin: 8px 0;
  color: var(--bone);
  font-size: 14px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.ticket-row-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.ticket-meta {
  color: var(--zinc);
  font-size: 10px;
}

.link-button {
  min-height: 44px;
  flex: 0 0 auto;
  padding: 0 2px;
  color: var(--mint);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.08em;
  line-height: 1;
  text-decoration: underline;
  text-underline-offset: 3px;
  text-transform: uppercase;
  white-space: nowrap;
}

.link-button:hover {
  color: var(--cream);
}

.affluence-list {
  display: grid;
}

.affluence-row {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--iron);
}

.affluence-row:last-child {
  border-bottom: 0;
}

.agency-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.agency-name {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.agency-name strong {
  overflow: hidden;
  color: var(--cream);
  font-size: 15px;
  font-weight: 500;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agency-name span {
  color: var(--zinc);
  font-size: 12px;
}

.agency-count {
  display: flex;
  align-items: baseline;
  flex: 0 0 auto;
  gap: 4px;
}

.agency-count strong {
  color: var(--cream);
  font-size: 34px;
  font-weight: 300;
  letter-spacing: -0.02em;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.agency-count span {
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 9px;
}

.level-bar {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
  height: 5px;
}

.level-seg {
  border-radius: var(--radius-card);
  background: var(--iron);
}

.level-seg.seg-mint.on {
  background: var(--mint);
}

.level-seg.seg-cream.on {
  background: var(--cream);
}

.level-seg.seg-ember.on {
  background: var(--ember);
}

.agency-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.level-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 7px;
  border: 1px solid var(--iron);
  border-radius: var(--radius-card);
  background: var(--slab);
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.08em;
  line-height: 1.3;
  text-transform: uppercase;
}

.level-badge.calme {
  background: var(--mint-soft);
  color: var(--mint);
}

.level-badge.moderee {
  border-color: var(--steel);
  background: var(--slab);
  color: var(--cream);
}

.level-badge.forte {
  background: var(--ember-soft);
  color: var(--ember);
}

.alert-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 7px;
  border: 1px solid var(--ember);
  border-radius: var(--radius-card);
  background: var(--ember);
  color: var(--void);
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.08em;
  line-height: 1.3;
  text-transform: uppercase;
}

.affluence-time {
  margin-left: auto;
  color: var(--zinc);
  font-size: 10px;
}

.affluence-note {
  padding: 12px 16px;
  border-top: 1px solid var(--iron);
  color: var(--zinc);
  font-size: 11px;
  line-height: 1.5;
}

.agent-footer {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 28px;
  padding-top: 18px;
  border-top: 1px solid var(--iron);
  color: var(--zinc);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  line-height: 1.5;
  text-transform: uppercase;
}

@media (max-width: 520px) {
  /* Sur petit écran, le libellé passe au-dessus de sa jauge :
     aucun motif n'est tronqué, même à 320 px. */
  .intent-row {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 5px 10px;
  }

  .intent-label {
    overflow: visible;
    white-space: normal;
  }

  .intent-count {
    grid-column: 2;
    grid-row: 1;
  }

  .intent-track {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .detail-meta {
    overflow: visible;
    white-space: normal;
    line-height: 1.45;
  }

  .ticket-row-foot {
    align-items: flex-start;
    flex-wrap: wrap;
  }
}

@media (min-width: 760px) {
  .hero {
    flex-direction: row;
    align-items: flex-end;
    justify-content: space-between;
    gap: 32px;
    padding-bottom: 30px;
  }

  .hero-copy {
    flex: 1;
  }

  .hero-actions {
    display: flex;
    flex: 0 0 auto;
  }

  .hero-actions .btn {
    width: auto;
    min-height: 44px;
  }

  .stats-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin-top: 24px;
  }

  .stat-card {
    padding: 18px;
  }

  .intent-panel {
    padding: 20px 24px;
  }

  .intent-row {
    grid-template-columns: minmax(120px, 1.1fr) minmax(0, 2.2fr) 32px;
    gap: 12px;
  }

  .intent-label {
    font-size: 12px;
  }

  .workspace {
    grid-template-columns: minmax(260px, 300px) minmax(0, 1fr);
  }

  .panel-head {
    padding: 15px 20px;
  }

  .panel-title {
    font-size: 20px;
  }

  .conversation-list {
    max-height: 540px;
  }

  .conversation-item {
    padding: 14px 18px;
  }

  .detail-panel {
    min-height: 540px;
  }

  .detail-head {
    padding: 18px 20px;
  }

  .detail-title {
    font-size: 22px;
  }

  .transcript {
    max-height: 420px;
    padding: 18px 20px;
  }

  .transcript-row p {
    font-size: 15px;
  }

  .ticket-card {
    margin: 0 20px 20px;
    padding: 16px;
  }

  .resolve-button {
    width: auto;
  }

  .empty-state {
    min-height: 460px;
  }

  .ticket-row {
    padding: 14px 20px;
  }

  .link-button {
    min-height: 36px;
  }

  .affluence-row {
    padding: 16px 20px;
  }

  .affluence-note {
    padding: 14px 20px;
  }

  .agent-footer {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }
}

@media (min-width: 1080px) {
  .agent {
    padding-top: 40px;
  }

  .workspace {
    grid-template-columns: 340px minmax(0, 1fr);
  }

  .bottom-grid {
    grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  }
}
</style>
