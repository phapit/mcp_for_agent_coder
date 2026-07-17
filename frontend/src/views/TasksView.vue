<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import StatusBadge from '@/components/StatusBadge.vue'
import { usePolling } from '@/composables/usePolling'
import { useToast } from '@/composables/useToast'
import { useI18n } from '@/i18n'

const toast = useToast()
const { t } = useI18n()

const opts = reactive({ force: false, prune: true, background: false })
const triggering = ref(false)

const status = ref(null) // /ingest/status
const activeJob = ref(null) // /ingest/jobs/{id}
const activeJobId = ref(null)
const history = ref([])
const historyLoading = ref(false)

const TERMINAL = ['succeeded', 'failed', 'dead_lettered', 'completed', 'completed_with_errors', 'never_run']

const isRunning = computed(() => {
  const s = status.value?.status
  const j = activeJob.value?.status
  return ['running', 'started', 'queued', 'retrying', 'pending'].includes(s) ||
    (j && !TERMINAL.includes(j))
})

async function refresh() {
  try {
    status.value = await api.ingestStatus()
  } catch (e) {
    // giữ giá trị cũ, không spam toast trong vòng poll
  }
  if (activeJobId.value) {
    try {
      activeJob.value = await api.ingestJob(activeJobId.value)
      if (TERMINAL.includes(activeJob.value?.status)) {
        const done = activeJobId.value
        activeJobId.value = null
        toast.info(t('tasks.jobNotify', { id: done.slice(0, 8), status: activeJob.value.status }))
        loadHistory()
      }
    } catch {
      /* job có thể chưa kịp ghi */
    }
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const r = await api.ingestHistory(20)
    history.value = r?.runs || []
  } catch (e) {
    toast.error(t('tasks.historyErrorPrefix', { error: e instanceof ApiError ? e.message : e }))
  } finally {
    historyLoading.value = false
  }
}

async function trigger() {
  triggering.value = true
  try {
    const res = await api.ingest({ ...opts })
    // 3 nhánh: kafka queued | background started | synchronous summary
    if (res?.job_id) {
      activeJobId.value = res.job_id
      activeJob.value = { status: res.status || 'queued', job_id: res.job_id }
      toast.success(t('tasks.kafkaQueued', { id: res.job_id.slice(0, 8), count: res.total_files ?? '?' }))
    } else if (res?.status === 'started') {
      toast.success(t('tasks.bgStarted', { count: res.total_files ?? '?' }))
    } else {
      status.value = res
      toast.success(t('tasks.ingestDone', { status: res?.status }))
      loadHistory()
    }
    refresh()
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : String(e)
    if (e?.status === 409) toast.error(t('tasks.err409'))
    else if (e?.status === 404) toast.error(t('tasks.err404'))
    else toast.error(msg)
  } finally {
    triggering.value = false
  }
}

const { start } = usePolling(refresh, 4000)
onMounted(() => {
  refresh()
  loadHistory()
  start()
})

function count(obj, key) {
  return Array.isArray(obj?.[key]) ? obj[key].length : 0
}
</script>

<template>
  <div class="grid cols-2">
    <!-- Điều khiển ingest -->
    <div class="card">
      <h2>{{ t('tasks.runTitle') }}</h2>
      <div class="row wrap" style="gap:1rem;margin:.6rem 0 1rem">
        <label class="row" style="gap:.4rem;width:auto"><input type="checkbox" v-model="opts.force" style="width:auto" /> {{ t('tasks.forceLabel') }}</label>
        <label class="row" style="gap:.4rem;width:auto"><input type="checkbox" v-model="opts.prune" style="width:auto" /> {{ t('tasks.pruneLabel') }}</label>
        <label class="row" style="gap:.4rem;width:auto"><input type="checkbox" v-model="opts.background" style="width:auto" /> {{ t('tasks.backgroundLabel') }}</label>
      </div>
      <button class="btn btn-primary" :disabled="triggering || isRunning" @click="trigger">
        <span v-if="triggering" class="spinner"></span>
        {{ isRunning ? t('tasks.running') : t('tasks.runButton') }}
      </button>
      <p class="faint mt1 mb0" style="font-size:.8rem">
        {{ t('tasks.runHint') }}
      </p>
    </div>

    <!-- Trạng thái hiện tại -->
    <div class="card">
      <div class="section-head">
        <h2 class="mb0">{{ t('tasks.currentStatus') }}</h2>
        <span v-if="isRunning" class="row faint"><span class="spinner"></span> live</span>
      </div>

      <div class="row spread"><span class="muted">{{ t('tasks.ingestStatus') }}</span><StatusBadge :status="status?.status || 'unknown'" /></div>
      <div v-if="status?.started_at" class="row spread"><span class="muted">{{ t('tasks.started') }}</span><span class="mono">{{ status.started_at }}</span></div>
      <div v-if="status?.finished_at" class="row spread"><span class="muted">{{ t('tasks.finished') }}</span><span class="mono">{{ status.finished_at }}</span></div>

      <template v-if="activeJob">
        <hr style="border-color:var(--border);margin:.8rem 0" />
        <div class="row spread"><span class="muted">{{ t('tasks.kafkaJob') }}</span><StatusBadge :status="activeJob.status" /></div>
        <div v-if="activeJob.job_id" class="row spread"><span class="muted">{{ t('tasks.jobId') }}</span><span class="mono">{{ activeJob.job_id }}</span></div>
        <div v-if="activeJob.attempt != null" class="row spread"><span class="muted">{{ t('tasks.attempt') }}</span><span>{{ activeJob.attempt }}</span></div>
        <div v-if="activeJob.error" class="row spread"><span class="muted">{{ t('tasks.error') }}</span><span class="mono" style="color:var(--err)">{{ activeJob.error }}</span></div>
      </template>
    </div>
  </div>

  <!-- Kết quả lần gần nhất -->
  <div v-if="status && status.status && status.status !== 'never_run'" class="card mt1">
    <h2>{{ t('tasks.latestResult') }}</h2>
    <div class="grid cols-4">
      <div class="stat"><span class="stat-label">{{ t('tasks.totalFiles') }}</span><span class="stat-value">{{ status.total_files ?? '—' }}</span></div>
      <div class="stat"><span class="stat-label">{{ t('tasks.ingested') }}</span><span class="stat-value" style="color:var(--ok)">{{ count(status, 'ingested') }}</span></div>
      <div class="stat"><span class="stat-label">{{ t('tasks.skipped') }}</span><span class="stat-value">{{ count(status, 'skipped') }}</span></div>
      <div class="stat"><span class="stat-label">{{ t('tasks.failed') }}</span><span class="stat-value" :style="count(status,'failed') ? 'color:var(--err)' : ''">{{ count(status, 'failed') }}</span></div>
    </div>
    <details class="mt1">
      <summary class="muted" style="cursor:pointer">{{ t('common.viewJson') }}</summary>
      <pre class="pre mt1">{{ JSON.stringify(status, null, 2) }}</pre>
    </details>
  </div>

  <!-- Lịch sử -->
  <div class="card mt1">
    <div class="section-head">
      <h2 class="mb0">{{ t('tasks.history') }}</h2>
      <button class="btn btn-sm" @click="loadHistory" :disabled="historyLoading">{{ t('common.refresh') }}</button>
    </div>
    <table v-if="history.length">
      <thead><tr><th>{{ t('tasks.colStart') }}</th><th>{{ t('tasks.colEnd') }}</th><th>{{ t('tasks.colStatus') }}</th><th>{{ t('tasks.colTotal') }}</th><th>{{ t('tasks.colOk') }}</th><th>{{ t('tasks.colFail') }}</th></tr></thead>
      <tbody>
        <tr v-for="(run, i) in history" :key="i">
          <td class="mono">{{ run.started_at || '—' }}</td>
          <td class="mono muted">{{ run.finished_at || '—' }}</td>
          <td><StatusBadge :status="run.status" /></td>
          <td>{{ run.total_files ?? '—' }}</td>
          <td style="color:var(--ok)">{{ count(run, 'ingested') }}</td>
          <td :style="count(run,'failed') ? 'color:var(--err)' : ''">{{ count(run, 'failed') }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="faint">{{ t('tasks.noHistory') }}</p>
  </div>
</template>
