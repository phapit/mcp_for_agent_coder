<script setup>
import { reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const form = reactive({
  query: '',
  limit: 3,
  project: '',
  environment: '',
  document_type: '',
  version: '',
})

const loading = ref(false)
const results = ref(null) // mảng match | null (chưa tìm)
const elapsed = ref(null)

function buildFilters() {
  const f = {}
  if (form.project) f.project = form.project
  if (form.environment) f.environment = form.environment
  if (form.document_type) f.document_type = form.document_type
  if (form.version !== '' && form.version != null) f.version = Number(form.version)
  return Object.keys(f).length ? f : null
}

async function run() {
  if (!form.query.trim()) {
    toast.error('Nhập nội dung cần tìm.')
    return
  }
  loading.value = true
  const t0 = performance.now()
  try {
    const payload = { query: form.query.trim(), limit: Number(form.limit) || 3 }
    const filters = buildFilters()
    if (filters) payload.filters = filters
    results.value = await api.search(payload)
    elapsed.value = Math.round(performance.now() - t0)
  } catch (e) {
    results.value = null
    toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

function fmt(n) {
  return n == null ? '—' : Number(n).toFixed(3)
}
</script>

<template>
  <div class="grid cols-2">
    <div class="card">
      <h2>Tìm kiếm ngữ cảnh (retrieval)</h2>
      <label class="field">
        <span class="field-label">Câu truy vấn</span>
        <textarea v-model="form.query" placeholder="Nhập câu hỏi hoặc từ khóa…" @keydown.ctrl.enter="run" />
      </label>
      <div class="row wrap" style="gap:.8rem">
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">Số kết quả (limit)</span>
          <input type="number" min="1" max="20" v-model.number="form.limit" />
        </label>
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">Version (tùy chọn)</span>
          <input type="number" v-model="form.version" placeholder="—" />
        </label>
      </div>
      <button class="btn btn-primary" :disabled="loading" @click="run">
        <span v-if="loading" class="spinner"></span>
        {{ loading ? 'Đang tìm…' : '🔍 Tìm kiếm' }}
      </button>
      <p class="faint mt1 mb0" style="font-size:.8rem">Ctrl+Enter để tìm nhanh.</p>
    </div>

    <div class="card">
      <h2>Bộ lọc (filters)</h2>
      <label class="field">
        <span class="field-label">Project</span>
        <input v-model="form.project" placeholder="vd: obsidian-wiki" />
      </label>
      <label class="field">
        <span class="field-label">Environment</span>
        <input v-model="form.environment" placeholder="vd: prod / dev" />
      </label>
      <label class="field">
        <span class="field-label">Document type</span>
        <input v-model="form.document_type" placeholder="vd: markdown" />
      </label>
      <p class="faint mb0" style="font-size:.8rem">Để trống nghĩa là không lọc theo trường đó.</p>
    </div>
  </div>

  <div v-if="results" class="card mt1">
    <div class="section-head">
      <h2 class="mb0">Kết quả ({{ results.length }})</h2>
      <span v-if="elapsed != null" class="faint">{{ elapsed }} ms</span>
    </div>
    <p v-if="!results.length" class="faint">Không có đoạn nào vượt ngưỡng liên quan.</p>
    <div v-for="(m, i) in results" :key="i" class="card" style="background:var(--bg);margin-bottom:.8rem">
      <div class="row spread">
        <span class="mono">{{ m.source }}<span v-if="m.heading"> › {{ m.heading }}</span></span>
        <span class="badge badge-ok">score {{ fmt(m.score) }}</span>
      </div>
      <div class="row wrap faint" style="gap:1rem;font-size:.78rem;margin:.3rem 0 .5rem">
        <span v-if="m.start_line">dòng {{ m.start_line }}–{{ m.end_line }}</span>
        <span>vector {{ fmt(m.vector_score) }}</span>
        <span>keyword {{ fmt(m.keyword_score) }}</span>
        <span>rerank {{ fmt(m.rerank_score) }}</span>
      </div>
      <pre class="pre" style="white-space:pre-wrap">{{ m.text }}</pre>
    </div>
  </div>
</template>
