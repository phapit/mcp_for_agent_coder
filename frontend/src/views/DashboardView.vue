<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import StatusBadge from '@/components/StatusBadge.vue'

const loading = ref(true)
const knowledge = ref(null)
const agent = ref(null)
const git = ref(null)
const docs = reactive({ ingested: 0, failed: 0, dead_letter: 0, removed: 0 })
const lastRun = ref(null)
const errors = ref([])

function pushErr(label, e) {
  errors.value.push(`${label}: ${e instanceof ApiError ? e.message : e}`)
}

async function load() {
  loading.value = true
  errors.value = []
  const tasks = [
    api.knowledgeReady().then((r) => (knowledge.value = r)).catch((e) => pushErr('knowledge readiness', e)),
    api.agentReady().then((r) => (agent.value = r)).catch((e) => pushErr('agent readiness', e)),
    api.gitStatus().then((r) => (git.value = r)).catch((e) => pushErr('git status', e)),
    api.ingestDocuments().then((r) => {
      docs.ingested = (r.ingested || []).length
      docs.failed = (r.failed || []).length
      docs.dead_letter = (r.dead_letter || []).length
      docs.removed = (r.removed || []).length
    }).catch((e) => pushErr('ingest documents', e)),
    api.ingestStatus().then((r) => (lastRun.value = r)).catch((e) => pushErr('ingest status', e)),
  ]
  await Promise.allSettled(tasks)
  loading.value = false
}
onMounted(load)

const checks = computed(() => {
  const out = []
  for (const [svc, data] of [['knowledge', knowledge.value], ['agent', agent.value]]) {
    if (data?.checks) {
      for (const [name, val] of Object.entries(data.checks)) {
        out.push({ svc, name, status: normalizeCheck(val) })
      }
    }
  }
  return out
})

function normalizeCheck(v) {
  if (typeof v === 'string') return v
  if (typeof v === 'boolean') return v ? 'ok' : 'down'
  if (v && typeof v === 'object') return v.status || (v.ok ? 'ok' : 'down')
  return 'unknown'
}
</script>

<template>
  <div v-if="loading" class="row"><span class="spinner"></span> Đang tải…</div>

  <template v-else>
    <div class="grid cols-4">
      <div class="card stat">
        <span class="stat-label">Tài liệu đã ingest</span>
        <span class="stat-value">{{ docs.ingested }}</span>
      </div>
      <div class="card stat">
        <span class="stat-label">Thất bại</span>
        <span class="stat-value" :style="docs.failed ? 'color:var(--err)' : ''">{{ docs.failed }}</span>
      </div>
      <div class="card stat">
        <span class="stat-label">Dead-letter</span>
        <span class="stat-value" :style="docs.dead_letter ? 'color:var(--err)' : ''">{{ docs.dead_letter }}</span>
      </div>
      <div class="card stat">
        <span class="stat-label">Lần ingest gần nhất</span>
        <span style="margin-top:.4rem"><StatusBadge :status="lastRun?.status || 'unknown'" /></span>
      </div>
    </div>

    <div class="grid cols-2 mt1">
      <div class="card">
        <div class="section-head">
          <h2 class="mb0">Sức khỏe hệ thống</h2>
          <button class="btn btn-sm" @click="load">Làm mới</button>
        </div>
        <table v-if="checks.length">
          <thead><tr><th>Service</th><th>Thành phần</th><th>Trạng thái</th></tr></thead>
          <tbody>
            <tr v-for="c in checks" :key="c.svc + c.name">
              <td class="muted">{{ c.svc }}</td>
              <td class="mono">{{ c.name }}</td>
              <td><StatusBadge :status="c.status" /></td>
            </tr>
          </tbody>
        </table>
        <p v-else class="faint">Không lấy được chi tiết readiness.</p>
      </div>

      <div class="card">
        <h2>Git repository</h2>
        <template v-if="git">
          <div class="row spread"><span class="muted">Branch</span><span class="mono">{{ git.active_branch }}</span></div>
          <div class="row spread"><span class="muted">Dirty</span><StatusBadge :status="git.is_dirty ? 'warn' : 'ok'" /></div>
          <div class="row spread"><span class="muted">Đã đổi</span><span>{{ (git.changed_files || []).length }}</span></div>
          <div class="row spread"><span class="muted">Staged</span><span>{{ (git.staged_files || []).length }}</span></div>
          <div class="row spread"><span class="muted">Untracked</span><span>{{ (git.untracked_files || []).length }}</span></div>
        </template>
        <p v-else class="faint">agent_service không phản hồi git status.</p>
      </div>
    </div>

    <div v-if="errors.length" class="card mt1" style="border-color:var(--err)">
      <h3 style="color:var(--err)">Cảnh báo kết nối</h3>
      <ul class="mono" style="margin:0;padding-left:1.2rem">
        <li v-for="(e, i) in errors" :key="i">{{ e }}</li>
      </ul>
    </div>
  </template>
</template>
