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
  prompt: '',
  output_name: 'custom-report.md',
  format: 'custom',
  append: '',
  language: '',
})

const FORMATS = computed(() => [
  { value: 'custom', label: t('customReport.formatCustom') },
  { value: 'briefing-doc', label: t('customReport.formatBriefing') },
  { value: 'study-guide', label: t('customReport.formatStudyGuide') },
  { value: 'blog-post', label: t('customReport.formatBlogPost') },
])

const PROMPT_MAX_LENGTH = 1024

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
    toast.error(t('customReport.loadProjectsErrorPrefix', { error: e instanceof ApiError ? e.message : e }))
  } finally {
    loadingProjects.value = false
  }
}

function onProjectChange() {
  if (!envs.value.includes(form.notebook_env)) form.notebook_env = envs.value[0] || ''
}

async function submit() {
  if (!form.project_name || !form.notebook_env || !form.prompt.trim()) {
    toast.error(t('customReport.missingFields'))
    return
  }
  if (form.prompt.trim().length > PROMPT_MAX_LENGTH) {
    toast.error(t('customReport.promptTooLong', { max: PROMPT_MAX_LENGTH, current: form.prompt.trim().length }))
    return
  }
  submitting.value = true
  try {
    const payload = {
      project_name: form.project_name,
      notebook_env: form.notebook_env,
      prompt: form.prompt.trim(),
      output_name: form.output_name.trim() || 'custom-report.md',
      format: form.format,
    }
    if (form.language) payload.language = form.language
    if (form.append.trim() && form.format !== 'custom') payload.append = form.append.trim()
    result.value = await api.generateNotebookReport(payload)
    toast.success(t('customReport.createSuccess'))
  } catch (e) {
    if (e?.status === 429) toast.error(t('customReport.err429'))
    else if (e?.status === 404) toast.error(t('customReport.err404'))
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
      <h2 class="mb0">{{ t('customReport.title') }}</h2>
      <button class="btn btn-sm" @click="loadProjects" :disabled="loadingProjects">{{ t('customReport.reloadProjects') }}</button>
    </div>
    <p class="faint mt0" style="font-size:.85rem">
      {{ t('customReport.description') }}
    </p>

    <div class="row wrap" style="gap:.8rem">
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">{{ t('customReport.projectLabel') }}</span>
        <select v-model="form.project_name" @change="onProjectChange">
          <option value="" disabled>{{ t('customReport.selectProject') }}</option>
          <option v-for="p in projects" :key="p.project_name" :value="p.project_name">{{ p.project_name }}</option>
        </select>
      </label>
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">{{ t('customReport.envLabel') }}</span>
        <select v-model="form.notebook_env" :disabled="!envs.length">
          <option value="" disabled>{{ t('customReport.selectEnv') }}</option>
          <option v-for="e in envs" :key="e" :value="e">{{ e }}</option>
        </select>
      </label>
    </div>

    <label class="field">
      <span class="field-label row spread">
        <span>{{ t('customReport.promptLabel') }}</span>
        <span class="faint">{{ form.prompt.length }}/{{ PROMPT_MAX_LENGTH }}</span>
      </span>
      <textarea
        v-model="form.prompt"
        rows="4"
        maxlength="1024"
        :placeholder="t('customReport.promptPlaceholder')"
        @keydown.ctrl.enter="submit"
      />
    </label>

    <div class="row wrap" style="gap:.8rem">
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">{{ t('customReport.outputNameLabel') }}</span>
        <input v-model="form.output_name" placeholder="custom-report.md" />
      </label>
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">{{ t('customReport.formatLabel') }}</span>
        <select v-model="form.format">
          <option v-for="f in FORMATS" :key="f.value" :value="f.value">{{ f.label }}</option>
        </select>
      </label>
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">{{ t('customReport.languageLabel') }}</span>
        <select v-model="form.language">
          <option v-for="l in LANGUAGES" :key="l.code" :value="l.code">{{ l.label }}</option>
        </select>
      </label>
    </div>

    <label class="field" v-if="form.format !== 'custom'">
      <span class="field-label">{{ t('customReport.appendLabel') }}</span>
      <input v-model="form.append" :placeholder="t('customReport.appendPlaceholder')" />
    </label>
    <p class="faint mt0 mb0" style="font-size:.8rem">
      {{ t('customReport.formatHint') }}
    </p>

    <button class="btn btn-primary" :disabled="submitting" @click="submit">
      <span v-if="submitting" class="spinner"></span>
      {{ submitting ? t('customReport.submitting') : t('customReport.submitButton') }}
    </button>
    <p class="faint mt1 mb0" style="font-size:.8rem">{{ t('customReport.submitHint') }}</p>
  </div>

  <div v-if="result" class="card mt1">
    <h2>{{ t('customReport.result') }}</h2>
    <div class="row spread"><span class="muted">{{ t('customReport.notebookId') }}</span><span class="mono">{{ result.notebook_id }}</span></div>
    <div class="row spread"><span class="muted">{{ t('customReport.artifactId') }}</span><span class="mono">{{ result.artifact_id ?? '—' }}</span></div>
    <div class="row spread"><span class="muted">{{ t('customReport.outputMd') }}</span><span class="mono">{{ result.output_md }}</span></div>
    <div class="row spread"><span class="muted">{{ t('customReport.format') }}</span><span class="mono">{{ result.format }}</span></div>
    <div class="row spread"><span class="muted">{{ t('customReport.language') }}</span><span class="mono">{{ result.language ?? t('customReport.defaultSuffix') }}</span></div>
    <details class="mt1">
      <summary class="muted" style="cursor:pointer">{{ t('common.viewJson') }}</summary>
      <pre class="pre mt1">{{ JSON.stringify(result, null, 2) }}</pre>
    </details>
  </div>
</template>
