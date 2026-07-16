<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const form = reactive({
  project_name: '',
  notebook_env: '',
  prompt: '',
  output_name: 'custom-report.md',
  format: 'custom',
  append: '',
  language: '',
})

const FORMATS = [
  { value: 'custom', label: 'Tùy chỉnh hoàn toàn (custom)' },
  { value: 'briefing-doc', label: 'Briefing doc' },
  { value: 'study-guide', label: 'Study guide' },
  { value: 'blog-post', label: 'Blog post' },
]

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
    toast.error(`Tải danh sách dự án: ${e instanceof ApiError ? e.message : e}`)
  } finally {
    loadingProjects.value = false
  }
}

function onProjectChange() {
  if (!envs.value.includes(form.notebook_env)) form.notebook_env = envs.value[0] || ''
}

async function submit() {
  if (!form.project_name || !form.notebook_env || !form.prompt.trim()) {
    toast.error('Cần chọn dự án, environment và nhập yêu cầu (prompt).')
    return
  }
  if (form.prompt.trim().length > PROMPT_MAX_LENGTH) {
    toast.error(`Yêu cầu (prompt) vượt quá ${PROMPT_MAX_LENGTH} ký tự (hiện ${form.prompt.trim().length}).`)
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
    toast.success('Đã tạo tài liệu theo yêu cầu và kích hoạt ingest.')
  } catch (e) {
    if (e?.status === 429) toast.error('NotebookLM đang bị rate limit (429) — thử lại sau.')
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
      <h2 class="mb0">Xuất tài liệu theo yêu cầu (NotebookLM)</h2>
      <button class="btn btn-sm" @click="loadProjects" :disabled="loadingProjects">Tải lại dự án</button>
    </div>
    <p class="faint mt0" style="font-size:.85rem">
      Nhập yêu cầu tự do (vd: "Mô tả chi tiết logic hoạt động của button A") — NotebookLM tạo tài liệu
      dựa trên các nguồn đã có sẵn trong notebook của dự án, sau đó tự động ingest vào kho tri thức.
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
      <span class="field-label row spread">
        <span>Yêu cầu (prompt)</span>
        <span class="faint">{{ form.prompt.length }}/{{ PROMPT_MAX_LENGTH }}</span>
      </span>
      <textarea
        v-model="form.prompt"
        rows="4"
        maxlength="1024"
        placeholder='vd: "Mô tả chi tiết logic hoạt động của button A"'
        @keydown.ctrl.enter="submit"
      />
    </label>

    <div class="row wrap" style="gap:.8rem">
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">Tên file output</span>
        <input v-model="form.output_name" placeholder="custom-report.md" />
      </label>
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">Định dạng report</span>
        <select v-model="form.format">
          <option v-for="f in FORMATS" :key="f.value" :value="f.value">{{ f.label }}</option>
        </select>
      </label>
      <label class="field" style="flex:1;min-width:160px">
        <span class="field-label">Ngôn ngữ đầu ra (generate)</span>
        <select v-model="form.language">
          <option v-for="l in LANGUAGES" :key="l.code" :value="l.code">{{ l.label }}</option>
        </select>
      </label>
    </div>

    <label class="field" v-if="form.format !== 'custom'">
      <span class="field-label">Ghi chú thêm vào template (append, tùy chọn)</span>
      <input v-model="form.append" placeholder='vd: "Ngắn gọn, dành cho người mới"' />
    </label>
    <p class="faint mt0 mb0" style="font-size:.8rem">
      Chọn "Tùy chỉnh hoàn toàn" để prompt là toàn quyền chỉ dẫn nội dung; các định dạng còn lại dùng
      template có sẵn của NotebookLM, prompt/append chỉ bổ sung chỉ dẫn.
    </p>

    <button class="btn btn-primary" :disabled="submitting" @click="submit">
      <span v-if="submitting" class="spinner"></span>
      {{ submitting ? 'Đang tạo tài liệu…' : '▶ Tạo tài liệu & ingest' }}
    </button>
    <p class="faint mt1 mb0" style="font-size:.8rem">Ctrl+Enter để gửi nhanh.</p>
  </div>

  <div v-if="result" class="card mt1">
    <h2>Kết quả</h2>
    <div class="row spread"><span class="muted">Notebook ID</span><span class="mono">{{ result.notebook_id }}</span></div>
    <div class="row spread"><span class="muted">Artifact ID</span><span class="mono">{{ result.artifact_id ?? '—' }}</span></div>
    <div class="row spread"><span class="muted">Output MD</span><span class="mono">{{ result.output_md }}</span></div>
    <div class="row spread"><span class="muted">Định dạng</span><span class="mono">{{ result.format }}</span></div>
    <div class="row spread"><span class="muted">Ngôn ngữ</span><span class="mono">{{ result.language ?? '— (mặc định)' }}</span></div>
    <details class="mt1">
      <summary class="muted" style="cursor:pointer">Xem JSON đầy đủ</summary>
      <pre class="pre mt1">{{ JSON.stringify(result, null, 2) }}</pre>
    </details>
  </div>
</template>
