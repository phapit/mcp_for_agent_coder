<script setup>
import { reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { useToast } from '@/composables/useToast'
import { useI18n } from '@/i18n'

const toast = useToast()
const { t } = useI18n()

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
    toast.error(t('answer.emptyQuestion'))
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
    if (e?.status === 404) toast.error(t('answer.noContext'))
    else toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="grid cols-2">
    <div class="card">
      <h2>{{ t('answer.title') }}</h2>
      <label class="field">
        <span class="field-label">{{ t('answer.questionLabel') }}</span>
        <textarea v-model="form.question" :placeholder="t('answer.questionPlaceholder')" @keydown.ctrl.enter="ask" />
      </label>
      <div class="row wrap" style="gap:.8rem">
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">{{ t('answer.limitLabel') }}</span>
          <input type="number" min="1" max="20" v-model.number="form.limit" />
        </label>
        <label class="field" style="flex:1;min-width:140px">
          <span class="field-label">{{ t('answer.modelLabel') }}</span>
          <select v-model.number="form.use_online_model">
            <option :value="0">{{ t('answer.modelOllama') }}</option>
            <option :value="1">{{ t('answer.modelOpenAI') }}</option>
          </select>
        </label>
      </div>
      <button class="btn btn-primary" :disabled="loading" @click="ask">
        <span v-if="loading" class="spinner"></span>
        {{ loading ? t('answer.answering') : t('answer.answerButton') }}
      </button>
      <p class="faint mt1 mb0" style="font-size:.8rem">{{ t('answer.answerHint') }}</p>
    </div>

    <div class="card">
      <h2>{{ t('answer.advancedOptions') }}</h2>
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
          <input v-model="form.session_id" :placeholder="t('answer.sessionIdPlaceholder')" />
        </label>
        <label class="field" style="flex:1;min-width:120px">
          <span class="field-label">Prompt version</span>
          <input v-model="form.prompt_version" :placeholder="t('answer.promptVersionPlaceholder')" />
        </label>
      </div>
    </div>
  </div>

  <div v-if="result" class="card mt1">
    <div class="section-head">
      <h2 class="mb0">{{ t('answer.answerTitle') }}</h2>
      <div class="row faint" style="gap:.8rem;font-size:.8rem">
        <span class="badge badge-neutral">{{ result.model_used }}</span>
        <span v-if="result.prompt_version">prompt {{ result.prompt_version }}</span>
        <span v-if="result.context_sanitized" class="badge badge-warn">{{ t('answer.contextSanitized') }}</span>
        <span v-if="elapsed != null">{{ elapsed }} ms</span>
      </div>
    </div>
    <pre class="pre" style="white-space:pre-wrap;font-size:.92rem">{{ result.answer }}</pre>

    <template v-if="result.citations && result.citations.length">
      <h2 class="mt1">{{ t('answer.citations', { count: result.citations.length }) }}</h2>
      <div
        v-for="c in result.citations"
        :key="c.context_id"
        class="row spread"
        style="border-top:1px solid var(--border);padding:.5rem 0"
      >
        <span class="mono">{{ c.source }}<span v-if="c.heading"> › {{ c.heading }}</span></span>
        <span class="faint" style="font-size:.8rem">
          <span v-if="c.start_line">{{ t('answer.lineRange', { start: c.start_line, end: c.end_line }) }} · </span>
          score {{ c.score != null ? Number(c.score).toFixed(3) : '—' }}
        </span>
      </div>
    </template>

    <details class="mt1">
      <summary class="muted" style="cursor:pointer">{{ t('answer.retrievalDetails') }}</summary>
      <pre class="pre mt1">{{ JSON.stringify(result.retrieval ?? {}, null, 2) }}</pre>
    </details>
  </div>
</template>
