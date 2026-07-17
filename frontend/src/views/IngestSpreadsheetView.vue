<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { useToast } from '@/composables/useToast'
import { useSettings } from '@/composables/useSettings'
import { LANGUAGES } from '@/constants/languages'
import { useI18n } from '@/i18n'

const toast = useToast()
const { settings, ready: settingsReady } = useSettings()
const { t } = useI18n()

const form = reactive({
  project_name: '',
  notebook_env: '',
  spreadsheet_id: '',
  output_name: 'spreadsheet.md',
  language: '', // '' = dùng mặc định NotebookLM (NOTEBOOKLM_HL/config)
})

const projects = ref([]) // [{ project_name, configs:[{notebook_env,...}] }]
const loadingProjects = ref(false)
const submitting = ref(false)
const result = ref(null)

const envs = computed(() => {
  const p = projects.value.find((x) => x.project_name === form.project_name)
  return p ? (p.configs || []).map((c) => c.notebook_env) : []
})

async function loadProjects() {
  loadingProjects.value = true
  try {
    const list = await api.listAllProjects()
    projects.value = Array.isArray(list) ? list : list?.projects || []
  } catch (e) {
    toast.error(t('ingestSpreadsheet.loadProjectsErrorPrefix', { error: e instanceof ApiError ? e.message : e }))
  } finally {
    loadingProjects.value = false
  }
}

function onProjectChange() {
  // Tự chọn env đầu tiên nếu env hiện tại không còn hợp lệ.
  if (!envs.value.includes(form.notebook_env)) form.notebook_env = envs.value[0] || ''
}

async function submit() {
  if (!form.project_name || !form.notebook_env || !form.spreadsheet_id.trim()) {
    toast.error(t('ingestSpreadsheet.missingFields'))
    return
  }
  submitting.value = true
  try {
    const payload = {
      project_name: form.project_name,
      notebook_env: form.notebook_env,
      spreadsheet_id: form.spreadsheet_id.trim(),
      output_name: form.output_name.trim() || 'spreadsheet.md',
    }
    if (form.language) payload.language = form.language
    result.value = await api.ingestSpreadsheet(payload)
    if (form.language && result.value?.report_reused) {
      toast.info(t('ingestSpreadsheet.reportReusedToast'))
    }
    toast.success(t('ingestSpreadsheet.exportSuccess'))
  } catch (e) {
    if (e?.status === 429) toast.error(t('ingestSpreadsheet.err429'))
    else if (e?.status === 404) toast.error(t('ingestSpreadsheet.err404'))
    else toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  loadProjects()
  await settingsReady
  if (settings.defaultLanguage) form.language = settings.defaultLanguage
})
</script>

<template>
  <div class="card">
    <div class="section-head">
      <h2 class="mb0">{{ t('ingestSpreadsheet.title') }}</h2>
      <button class="btn btn-sm" @click="loadProjects" :disabled="loadingProjects">{{ t('ingestSpreadsheet.reloadProjects') }}</button>
    </div>
    <p class="faint mt0" style="font-size:.85rem">
      {{ t('ingestSpreadsheet.description') }}
    </p>

    <div class="row wrap" style="gap:.8rem">
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">{{ t('ingestSpreadsheet.projectLabel') }}</span>
        <select v-model="form.project_name" @change="onProjectChange">
          <option value="" disabled>{{ t('ingestSpreadsheet.selectProject') }}</option>
          <option v-for="p in projects" :key="p.project_name" :value="p.project_name">{{ p.project_name }}</option>
        </select>
      </label>
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">{{ t('ingestSpreadsheet.envLabel') }}</span>
        <select v-model="form.notebook_env" :disabled="!envs.length">
          <option value="" disabled>{{ t('ingestSpreadsheet.selectEnv') }}</option>
          <option v-for="e in envs" :key="e" :value="e">{{ e }}</option>
        </select>
      </label>
    </div>

    <label class="field">
      <span class="field-label">{{ t('ingestSpreadsheet.spreadsheetIdLabel') }}</span>
      <input v-model="form.spreadsheet_id" placeholder="Google Sheet ID" />
    </label>
    <div class="row wrap" style="gap:.8rem">
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">{{ t('ingestSpreadsheet.outputNameLabel') }}</span>
        <input v-model="form.output_name" placeholder="spreadsheet.md" />
      </label>
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">{{ t('ingestSpreadsheet.languageLabel') }}</span>
        <select v-model="form.language">
          <option v-for="l in LANGUAGES" :key="l.code" :value="l.code">{{ l.label }}</option>
        </select>
      </label>
    </div>
    <p class="faint mt0 mb0" style="font-size:.8rem">
      {{ t('ingestSpreadsheet.languageHint') }}
    </p>

    <button class="btn btn-primary" :disabled="submitting" @click="submit">
      <span v-if="submitting" class="spinner"></span>
      {{ submitting ? t('ingestSpreadsheet.submitting') : t('ingestSpreadsheet.submitButton') }}
    </button>
  </div>

  <div v-if="result" class="card mt1">
    <h2>{{ t('ingestSpreadsheet.result') }}</h2>
    <div class="row spread"><span class="muted">{{ t('ingestSpreadsheet.notebookId') }}</span><span class="mono">{{ result.notebook_id }}</span></div>
    <div class="row spread"><span class="muted">{{ t('ingestSpreadsheet.sourceId') }}</span><span class="mono">{{ result.source_id ?? '—' }}</span></div>
    <div class="row spread"><span class="muted">{{ t('ingestSpreadsheet.artifactId') }}</span><span class="mono">{{ result.artifact_id ?? '—' }}</span></div>
    <div class="row spread"><span class="muted">{{ t('ingestSpreadsheet.outputMd') }}</span><span class="mono">{{ result.output_md }}</span></div>
    <div class="row spread"><span class="muted">{{ t('ingestSpreadsheet.language') }}</span><span class="mono">{{ result.language ?? t('ingestSpreadsheet.defaultSuffix') }}</span></div>
    <div v-if="result.report_reused" class="row spread"><span class="muted">{{ t('ingestSpreadsheet.reportLabel') }}</span><span class="badge badge-warn">{{ t('ingestSpreadsheet.reportReusedBadge') }}</span></div>
    <details class="mt1">
      <summary class="muted" style="cursor:pointer">{{ t('common.viewJson') }}</summary>
      <pre class="pre mt1">{{ JSON.stringify(result, null, 2) }}</pre>
    </details>
  </div>
</template>
