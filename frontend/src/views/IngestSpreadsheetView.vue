<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const form = reactive({
  project_name: '',
  notebook_env: '',
  spreadsheet_id: '',
  output_name: 'spreadsheet.md',
  language: '', // '' = dùng mặc định NotebookLM (NOTEBOOKLM_HL/config)
})

// Mã ngôn ngữ phổ biến cho generate report (per-command --language).
const LANGUAGES = [
  { code: '', label: 'Mặc định (theo cấu hình NotebookLM)' },
  { code: 'vi', label: 'Tiếng Việt (vi)' },
  { code: 'en', label: 'English (en)' },
  { code: 'ja', label: '日本語 (ja)' },
  { code: 'zh_Hans', label: '简体中文 (zh_Hans)' },
  { code: 'ko', label: '한국어 (ko)' },
  { code: 'fr', label: 'Français (fr)' },
]

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
    toast.error(`Tải danh sách dự án: ${e instanceof ApiError ? e.message : e}`)
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
    toast.error('Cần chọn dự án, environment và nhập spreadsheet_id.')
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
      toast.info('Report đã tồn tại nên được tái dùng — ngôn ngữ đã chọn KHÔNG được áp dụng. Đổi tên output để tạo report mới.')
    }
    toast.success('Đã export spreadsheet và kích hoạt ingest.')
  } catch (e) {
    if (e?.status === 429) toast.error('NotebookLM đang bị rate limit (429) — có thể chạy lại sau, không tạo bản trùng.')
    else if (e?.status === 404) toast.error('Không tìm thấy cấu hình dự án/environment (404).')
    else toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    submitting.value = false
  }
}

onMounted(loadProjects)
</script>

<template>
  <div class="card">
    <div class="section-head">
      <h2 class="mb0">Ingest Spreadsheet (NotebookLM)</h2>
      <button class="btn btn-sm" @click="loadProjects" :disabled="loadingProjects">Tải lại dự án</button>
    </div>
    <p class="faint mt0" style="font-size:.85rem">
      Resolve cấu hình NotebookLM theo dự án/environment rồi export Markdown, sau đó tự động ingest.
    </p>

    <div class="row wrap" style="gap:.8rem">
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">Dự án</span>
        <select v-model="form.project_name" @change="onProjectChange">
          <option value="" disabled>— chọn dự án —</option>
          <option v-for="p in projects" :key="p.project_name" :value="p.project_name">{{ p.project_name }}</option>
        </select>
      </label>
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">Environment</span>
        <select v-model="form.notebook_env" :disabled="!envs.length">
          <option value="" disabled>— chọn env —</option>
          <option v-for="e in envs" :key="e" :value="e">{{ e }}</option>
        </select>
      </label>
    </div>

    <label class="field">
      <span class="field-label">Spreadsheet ID</span>
      <input v-model="form.spreadsheet_id" placeholder="Google Sheet ID" />
    </label>
    <div class="row wrap" style="gap:.8rem">
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">Tên file output</span>
        <input v-model="form.output_name" placeholder="spreadsheet.md" />
      </label>
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">Ngôn ngữ đầu ra (generate)</span>
        <select v-model="form.language">
          <option v-for="l in LANGUAGES" :key="l.code" :value="l.code">{{ l.label }}</option>
        </select>
      </label>
    </div>
    <p class="faint mt0 mb0" style="font-size:.8rem">
      Ngôn ngữ chỉ áp dụng khi tạo report mới. Nếu report cho spreadsheet này đã tồn tại, hệ thống tái
      dùng và bỏ qua ngôn ngữ — đổi tên file output để buộc tạo report mới.
    </p>

    <button class="btn btn-primary" :disabled="submitting" @click="submit">
      <span v-if="submitting" class="spinner"></span>
      {{ submitting ? 'Đang export…' : '▶ Export & ingest' }}
    </button>
  </div>

  <div v-if="result" class="card mt1">
    <h2>Kết quả</h2>
    <div class="row spread"><span class="muted">Notebook ID</span><span class="mono">{{ result.notebook_id }}</span></div>
    <div class="row spread"><span class="muted">Source ID</span><span class="mono">{{ result.source_id ?? '—' }}</span></div>
    <div class="row spread"><span class="muted">Artifact ID</span><span class="mono">{{ result.artifact_id ?? '—' }}</span></div>
    <div class="row spread"><span class="muted">Output MD</span><span class="mono">{{ result.output_md }}</span></div>
    <div class="row spread"><span class="muted">Ngôn ngữ</span><span class="mono">{{ result.language ?? '— (mặc định)' }}</span></div>
    <div v-if="result.report_reused" class="row spread"><span class="muted">Report</span><span class="badge badge-warn">tái dùng (ngôn ngữ không áp dụng)</span></div>
    <details class="mt1">
      <summary class="muted" style="cursor:pointer">Xem JSON đầy đủ</summary>
      <pre class="pre mt1">{{ JSON.stringify(result, null, 2) }}</pre>
    </details>
  </div>
</template>
