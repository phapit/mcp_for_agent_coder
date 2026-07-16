<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import ModalDialog from '@/components/ModalDialog.vue'
import { useToast } from '@/composables/useToast'

const toast = useToast()

// Backend không có endpoint "list tất cả project" → lưu tên project đã biết ở localStorage.
const LS_KEY = 'ow.knownProjects'
const knownNames = ref(loadKnown())
const projects = reactive({}) // { [name]: { loading, error, configs: [] } }
const loading = ref(false)

function loadKnown() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || '[]')
  } catch {
    return []
  }
}
function saveKnown() {
  localStorage.setItem(LS_KEY, JSON.stringify(knownNames.value))
}
function rememberName(name) {
  if (!knownNames.value.includes(name)) {
    knownNames.value.push(name)
    knownNames.value.sort()
    saveKnown()
  }
}
function forgetName(name) {
  knownNames.value = knownNames.value.filter((n) => n !== name)
  saveKnown()
  delete projects[name]
}

async function loadProject(name) {
  projects[name] = projects[name] || { loading: false, error: null, configs: [] }
  projects[name].loading = true
  projects[name].error = null
  try {
    const list = await api.listProjectConfigs(name)
    projects[name].configs = Array.isArray(list) ? list : []
  } catch (e) {
    projects[name].configs = []
    projects[name].error = e instanceof ApiError ? e.message : String(e)
  } finally {
    projects[name].loading = false
  }
}

async function loadAll() {
  loading.value = true
  try {
    const list = await api.listAllProjects()
    for (const p of list || []) {
      projects[p.project_name] = { loading: false, error: null, configs: p.configs || [] }
      rememberName(p.project_name)
    }
    // Tên chỉ tồn tại ở localStorage (vừa thêm, chưa có cấu hình) → hiển thị rỗng.
    for (const name of knownNames.value) {
      if (!projects[name]) projects[name] = { loading: false, error: null, configs: [] }
    }
  } catch (e) {
    toast.error(`Danh sách dự án: ${e instanceof ApiError ? e.message : e}`)
    await Promise.allSettled(knownNames.value.map(loadProject)) // fallback theo localStorage
  } finally {
    loading.value = false
  }
}
onMounted(loadAll)

// ---- Thêm project (chỉ ghi nhớ tên, chưa có config) ----
const newProjectName = ref('')
function addProject() {
  const name = newProjectName.value.trim()
  if (!name) return
  if (!/^[a-zA-Z0-9._-]+$/.test(name)) {
    toast.error('Tên project chỉ gồm chữ, số, . _ -')
    return
  }
  rememberName(name)
  newProjectName.value = ''
  loadProject(name)
  toast.success(`Đã thêm dự án "${name}". Tạo cấu hình notebook cho nó bên dưới.`)
}

// ---- Modal cấu hình notebook ----
const modalOpen = ref(false)
const editMode = ref(false)
const saving = ref(false)
const form = reactive({
  project_name: '',
  notebook_env: '',
  notebook_id: '',
  notebooklm_auth_name: '',
})

function openCreate(projectName) {
  editMode.value = false
  Object.assign(form, {
    project_name: projectName || '',
    notebook_env: '',
    notebook_id: '',
    notebooklm_auth_name: '',
  })
  modalOpen.value = true
}
function openEdit(cfg) {
  editMode.value = true
  Object.assign(form, {
    project_name: cfg.project_name,
    notebook_env: cfg.notebook_env,
    notebook_id: cfg.notebook_id,
    notebooklm_auth_name: cfg.notebooklm_auth_name,
  })
  modalOpen.value = true
}

async function submit() {
  for (const [k, v] of Object.entries(form)) {
    if (!String(v).trim()) {
      toast.error(`Thiếu trường "${k}"`)
      return
    }
  }
  saving.value = true
  try {
    if (editMode.value) {
      await api.updateProjectConfig(form.project_name, form.notebook_env, { ...form })
      toast.success('Đã cập nhật cấu hình')
    } else {
      await api.upsertProjectConfig({ ...form })
      toast.success('Đã tạo cấu hình')
    }
    rememberName(form.project_name)
    modalOpen.value = false
    await loadProject(form.project_name)
  } catch (e) {
    toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    saving.value = false
  }
}

async function removeConfig(cfg) {
  if (!confirm(`Xóa cấu hình ${cfg.project_name} / ${cfg.notebook_env}?`)) return
  try {
    await api.deleteProjectConfig(cfg.project_name, cfg.notebook_env)
    toast.success('Đã xóa cấu hình')
    await loadProject(cfg.project_name)
  } catch (e) {
    toast.error(e instanceof ApiError ? e.message : String(e))
  }
}
</script>

<template>
  <div class="card">
    <div class="section-head">
      <div>
        <h2 class="mb0">Dự án & cấu hình NotebookLM</h2>
        <p class="faint mb0" style="font-size:.8rem">
          Mỗi dự án gồm nhiều môi trường (notebook_env). Danh sách lấy từ backend
          (<span class="mono">GET /project-notebook-configs</span>); tên vừa thêm nhưng chưa có cấu hình được giữ tạm ở trình duyệt.
        </p>
      </div>
      <button class="btn btn-sm" @click="loadAll" :disabled="loading">Làm mới</button>
    </div>

    <div class="row wrap">
      <input
        v-model="newProjectName"
        placeholder="Tên dự án mới (vd: obsidian-wiki)"
        style="max-width:320px"
        @keyup.enter="addProject"
      />
      <button class="btn btn-primary" @click="addProject">+ Thêm dự án</button>
    </div>
  </div>

  <div v-if="!knownNames.length" class="card mt1 empty">
    Chưa có dự án nào. Thêm một dự án ở trên để bắt đầu.
  </div>

  <div v-for="name in knownNames" :key="name" class="card mt1">
    <div class="section-head">
      <h2 class="mb0">❖ {{ name }}</h2>
      <div class="row">
        <button class="btn btn-sm btn-primary" @click="openCreate(name)">+ Cấu hình</button>
        <button class="btn btn-sm" @click="loadProject(name)">↻</button>
        <button class="btn btn-sm btn-danger" @click="forgetName(name)" title="Bỏ khỏi danh sách cục bộ">Ẩn</button>
      </div>
    </div>

    <div v-if="projects[name]?.loading" class="row"><span class="spinner"></span> Đang tải…</div>
    <p v-else-if="projects[name]?.error" class="faint mono">{{ projects[name].error }}</p>

    <table v-else-if="projects[name]?.configs?.length">
      <thead>
        <tr><th>Môi trường</th><th>Notebook ID</th><th>Auth</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="cfg in projects[name].configs" :key="cfg.notebook_env">
          <td><span class="badge badge-neutral">{{ cfg.notebook_env }}</span></td>
          <td class="mono">{{ cfg.notebook_id }}</td>
          <td class="mono muted">{{ cfg.notebooklm_auth_name }}</td>
          <td>
            <div class="row" style="justify-content:flex-end">
              <button class="btn btn-sm" @click="openEdit(cfg)">Sửa</button>
              <button class="btn btn-sm btn-danger" @click="removeConfig(cfg)">Xóa</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else class="faint">Chưa có cấu hình notebook nào cho dự án này.</p>
  </div>

  <ModalDialog
    v-if="modalOpen"
    :title="editMode ? 'Sửa cấu hình notebook' : 'Tạo cấu hình notebook'"
    @close="modalOpen = false"
  >
    <label class="field">
      <span class="field-label">Tên dự án</span>
      <input v-model="form.project_name" :disabled="editMode" />
    </label>
    <label class="field">
      <span class="field-label">Môi trường (notebook_env)</span>
      <input v-model="form.notebook_env" :disabled="editMode" placeholder="vd: prod, staging" />
    </label>
    <label class="field">
      <span class="field-label">Notebook ID</span>
      <input v-model="form.notebook_id" />
    </label>
    <label class="field">
      <span class="field-label">Tên auth NotebookLM (notebooklm_auth_name)</span>
      <input v-model="form.notebooklm_auth_name" placeholder="tên file auth trong notebooklm_auth/" />
    </label>

    <template #footer>
      <button class="btn" @click="modalOpen = false">Hủy</button>
      <button class="btn btn-primary" :disabled="saving" @click="submit">
        <span v-if="saving" class="spinner"></span>
        {{ editMode ? 'Lưu' : 'Tạo' }}
      </button>
    </template>
  </ModalDialog>
</template>
