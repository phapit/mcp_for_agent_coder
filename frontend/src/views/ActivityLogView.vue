<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import StatusBadge from '@/components/StatusBadge.vue'
import { usePolling } from '@/composables/usePolling'
import { useToast } from '@/composables/useToast'

const toast = useToast()

// "Log hoạt động": backend không có API log stdout. Ta dựng nhật ký từ registry tài liệu
// (/ingest/documents), dead-letter và lịch sử ingest — tất cả qua polling.
const docs = ref({ ingested: [], failed: [], dead_letter: [], removed: [] })
const history = ref([])
const loading = ref(false)
const filter = ref('all') // all | ingested | failed | dead_letter | removed
const auto = ref(true)

const LEVEL = { ingested: 'ok', removed: 'neutral', failed: 'err', dead_letter: 'err' }

async function load() {
  loading.value = true
  try {
    const [d, h] = await Promise.allSettled([api.ingestDocuments(), api.ingestHistory(20)])
    if (d.status === 'fulfilled') docs.value = { ingested: [], failed: [], dead_letter: [], removed: [], ...d.value }
    if (h.status === 'fulfilled') history.value = h.value?.runs || []
    if (d.status === 'rejected') throw d.reason
  } catch (e) {
    toast.error(`Log: ${e instanceof ApiError ? e.message : e}`)
  } finally {
    loading.value = false
  }
}

// Gộp thành dòng log thống nhất.
const entries = computed(() => {
  const rows = []
  for (const bucket of ['ingested', 'failed', 'dead_letter', 'removed']) {
    for (const doc of docs.value[bucket] || []) {
      rows.push({
        bucket,
        level: LEVEL[bucket],
        time: doc.updated_at || doc.finished_at || doc.created_at || '',
        document_id: doc.document_id || doc.id || '',
        file: doc.file || doc.source || doc.path || '',
        message: doc.error || doc.action || doc.status || bucket,
        attempt: doc.attempt,
        raw: doc,
      })
    }
  }
  rows.sort((a, b) => String(b.time).localeCompare(String(a.time)))
  return filter.value === 'all' ? rows : rows.filter((r) => r.bucket === filter.value)
})

async function requeue(documentId) {
  try {
    const r = await api.requeueDeadLetter(documentId)
    toast.success(`Đã requeue ${r?.requeued ?? ''} tài liệu`)
    load()
  } catch (e) {
    toast.error(e instanceof ApiError ? e.message : String(e))
  }
}

const { start, stop } = usePolling(load, 6000)
onMounted(() => {
  load()
  if (auto.value) start()
})
function toggleAuto() {
  auto.value = !auto.value
  auto.value ? start() : stop()
}

const counts = computed(() => ({
  ingested: docs.value.ingested?.length || 0,
  failed: docs.value.failed?.length || 0,
  dead_letter: docs.value.dead_letter?.length || 0,
  removed: docs.value.removed?.length || 0,
}))
</script>

<template>
  <div class="card">
    <div class="section-head">
      <div>
        <h2 class="mb0">Nhật ký hoạt động</h2>
        <p class="faint mb0" style="font-size:.8rem">
          Tổng hợp từ registry tài liệu + dead-letter + lịch sử ingest (polling 6s).
          Log stdout của service lấy bằng <span class="mono">docker logs knowledge_service</span>.
        </p>
      </div>
      <div class="row">
        <button class="btn btn-sm" :class="auto ? 'btn-primary' : ''" @click="toggleAuto">
          {{ auto ? '● Auto' : '○ Auto' }}
        </button>
        <button class="btn btn-sm" @click="load" :disabled="loading">
          <span v-if="loading" class="spinner"></span> Làm mới
        </button>
      </div>
    </div>

    <div class="row wrap" style="gap:.4rem">
      <button
        v-for="f in ['all', 'ingested', 'failed', 'dead_letter', 'removed']"
        :key="f"
        class="btn btn-sm"
        :class="filter === f ? 'btn-primary' : ''"
        @click="filter = f"
      >
        {{ f }}<template v-if="f !== 'all'"> ({{ counts[f] }})</template>
      </button>
    </div>
  </div>

  <!-- Dead-letter cần chú ý -->
  <div v-if="counts.dead_letter" class="card mt1" style="border-color:var(--err)">
    <h3 style="color:var(--err)">⚠ Dead-letter ({{ counts.dead_letter }})</h3>
    <table>
      <thead><tr><th>Document</th><th>File</th><th>Lỗi</th><th></th></tr></thead>
      <tbody>
        <tr v-for="d in docs.dead_letter" :key="d.document_id || d.id">
          <td class="mono">{{ d.document_id || d.id }}</td>
          <td class="mono muted">{{ d.file || d.source }}</td>
          <td class="mono" style="color:var(--err)">{{ d.error || '—' }}</td>
          <td><button class="btn btn-sm" @click="requeue(d.document_id || d.id)">Requeue</button></td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- Dòng log -->
  <div class="card mt1">
    <table v-if="entries.length">
      <thead><tr><th>Thời gian</th><th>Mức</th><th>File / Document</th><th>Thông điệp</th></tr></thead>
      <tbody>
        <tr v-for="(e, i) in entries" :key="i">
          <td class="mono faint" style="white-space:nowrap">{{ e.time || '—' }}</td>
          <td><StatusBadge :status="e.bucket" /></td>
          <td>
            <div class="mono">{{ e.file || '—' }}</div>
            <div class="mono faint" style="font-size:.72rem">{{ e.document_id }}</div>
          </td>
          <td class="mono" :style="e.level === 'err' ? 'color:var(--err)' : ''">
            {{ e.message }}<span v-if="e.attempt != null" class="faint"> · attempt {{ e.attempt }}</span>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="loading" class="row"><span class="spinner"></span> Đang tải…</p>
    <p v-else class="empty">Không có mục log nào cho bộ lọc "{{ filter }}".</p>
  </div>
</template>
