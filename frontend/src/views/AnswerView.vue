<script setup>
import { reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const form = reactive({
  question: '',
  limit: 3,
  use_online_model: 0, // 0 = Ollama (local), 1 = OpenAI (online)
  project: '',
  environment: '',
  document_type: '',
  version: '',
  session_id: '',
  prompt_version: '',
})

const loading = ref(false)
const result = ref(null)
const elapsed = ref(null)

function buildFilters() {
  const f = {}
  if (form.project) f.project = form.project
  if (form.environment) f.environment = form.environment
  if (form.document_type) f.document_type = form.document_type
  if (form.version !== '' && form.version != null) f.version = Number(form.version)
  return Object.keys(f).length ? f : null
}

async function ask() {
  if (!form.question.trim()) {
    toast.error('Nhập câu hỏi.')
    return
  }
  loading.value = true
  const t0 = performance.now()
  try {
    const payload = {
      question: form.question.trim(),
      limit: Number(form.limit) || 3,
      use_online_model: form.use_online_model ? 1 : 0,
    }
    const filters = buildFilters()
    if (filters) payload.filters = filters
    if (form.session_id.trim()) payload.session_id = form.session_id.trim()
    if (form.prompt_version.trim()) payload.prompt_version = form.prompt_version.trim()

    result.value = await api.answer(payload)
    elapsed.value = Math.round(performance.now() - t0)
    // Backend có thể trả session_id (giữ để hỏi tiếp nhiều lượt).
    if (result.value?.session_id) form.session_id = result.value.session_id
  } catch (e) {
    result.value = null
    if (e?.status === 404) toast.error('Không tìm được ngữ cảnh liên quan (404) — hệ thống từ chối bịa câu trả lời.')
    else toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="grid cols-2">
    <div class="card">
      <h2>Đặt câu hỏi (RAG)</h2>
      <label class="field">
        <span class="field-label">Câu hỏi</span>
        <textarea v-model="form.question" placeholder="Nhập câu hỏi…" @keydown.ctrl.enter="ask" />
      </label>
      <div class="row wrap" style="gap:.8rem">
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">Số ngữ cảnh (limit)</span>
          <input type="number" min="1" max="20" v-model.number="form.limit" />
        </label>
        <label class="field" style="flex:1;min-width:140px">
          <span class="field-label">Mô hình</span>
          <select v-model.number="form.use_online_model">
            <option :value="0">Ollama (local)</option>
            <option :value="1">OpenAI gpt-4o-mini (online)</option>
          </select>
        </label>
      </div>
      <button class="btn btn-primary" :disabled="loading" @click="ask">
        <span v-if="loading" class="spinner"></span>
        {{ loading ? 'Đang trả lời…' : '✦ Trả lời' }}
      </button>
      <p class="faint mt1 mb0" style="font-size:.8rem">Ctrl+Enter để gửi. Có session_id → hỏi tiếp nhiều lượt.</p>
    </div>

    <div class="card">
      <h2>Tùy chọn nâng cao</h2>
      <div class="row wrap" style="gap:.8rem">
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">Project</span>
          <input v-model="form.project" placeholder="—" />
        </label>
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">Environment</span>
          <input v-model="form.environment" placeholder="—" />
        </label>
      </div>
      <div class="row wrap" style="gap:.8rem">
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">Document type</span>
          <input v-model="form.document_type" placeholder="—" />
        </label>
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">Version</span>
          <input type="number" v-model="form.version" placeholder="—" />
        </label>
      </div>
      <div class="row wrap" style="gap:.8rem">
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">Session ID</span>
          <input v-model="form.session_id" placeholder="tự sinh nếu trống" />
        </label>
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">Prompt version</span>
          <input v-model="form.prompt_version" placeholder="mặc định theo env" />
        </label>
      </div>
    </div>
  </div>

  <div v-if="result" class="card mt1">
    <div class="section-head">
      <h2 class="mb0">Câu trả lời</h2>
      <div class="row faint" style="gap:.8rem;font-size:.8rem">
        <span class="badge badge-neutral">{{ result.model_used }}</span>
        <span v-if="result.prompt_version">prompt {{ result.prompt_version }}</span>
        <span v-if="result.context_sanitized" class="badge badge-warn">context đã lọc</span>
        <span v-if="elapsed != null">{{ elapsed }} ms</span>
      </div>
    </div>
    <pre class="pre" style="white-space:pre-wrap;font-size:.92rem">{{ result.answer }}</pre>

    <template v-if="result.citations && result.citations.length">
      <h2 class="mt1">Trích dẫn ({{ result.citations.length }})</h2>
      <div
        v-for="c in result.citations"
        :key="c.context_id"
        class="row spread"
        style="border-top:1px solid var(--border);padding:.5rem 0"
      >
        <span class="mono">{{ c.source }}<span v-if="c.heading"> › {{ c.heading }}</span></span>
        <span class="faint" style="font-size:.8rem">
          <span v-if="c.start_line">dòng {{ c.start_line }}–{{ c.end_line }} · </span>
          score {{ c.score != null ? Number(c.score).toFixed(3) : '—' }}
        </span>
      </div>
    </template>

    <details class="mt1">
      <summary class="muted" style="cursor:pointer">Chi tiết retrieval / JSON</summary>
      <pre class="pre mt1">{{ JSON.stringify(result.retrieval ?? {}, null, 2) }}</pre>
    </details>
  </div>
</template>
