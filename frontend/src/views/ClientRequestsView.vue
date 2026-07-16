<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const form = reactive({
  title: '',
  description: '',
  request_type: 'feature',
  project: '',
  requester: '',
})

const ROLES = [
  { key: 'pm', label: 'PM' },
  { key: 'coder', label: 'Coder' },
  { key: 'tester', label: 'Tester' },
]

const submitting = ref(false)
const requests = ref([])
const selected = ref(null) // record đầy đủ (kèm context)
const activeRole = ref('coder')
const roleContext = ref(null) // { markdown, ... } theo role đang chọn
const loadingContext = ref(false)
const reanalyzing = ref(false)

async function refreshList() {
  try {
    requests.value = await api.listClientRequests()
  } catch (e) {
    toast.error(e instanceof ApiError ? e.message : String(e))
  }
}

async function submit() {
  if (!form.title.trim() || !form.description.trim()) {
    toast.error('Nhập tiêu đề và mô tả yêu cầu.')
    return
  }
  submitting.value = true
  try {
    const payload = {
      title: form.title.trim(),
      description: form.description.trim(),
      request_type: form.request_type,
    }
    if (form.project.trim()) payload.project = form.project.trim()
    if (form.requester.trim()) payload.requester = form.requester.trim()
    const record = await api.createClientRequest(payload)
    toast.success(
      record.context.has_related_specs
        ? `Đã tìm thấy ${record.context.excerpts.length} trích đoạn đặc tả liên quan.`
        : 'Không có đặc tả liên quan — gói ngữ cảnh sẽ cảnh báo agent.',
    )
    form.title = ''
    form.description = ''
    await refreshList()
    await select(record.request_id)
  } catch (e) {
    toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    submitting.value = false
  }
}

async function select(requestId) {
  try {
    selected.value = await api.getClientRequest(requestId)
    roleContext.value = null
    await loadRole(activeRole.value)
  } catch (e) {
    toast.error(e instanceof ApiError ? e.message : String(e))
  }
}

async function loadRole(role) {
  activeRole.value = role
  if (!selected.value?.context) {
    roleContext.value = null
    return
  }
  loadingContext.value = true
  try {
    roleContext.value = await api.getClientRequestContext(selected.value.request_id, role)
  } catch (e) {
    roleContext.value = null
    toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    loadingContext.value = false
  }
}

async function copyMarkdown() {
  if (!roleContext.value?.markdown) return
  try {
    await navigator.clipboard.writeText(roleContext.value.markdown)
    toast.success(`Đã sao chép ngữ cảnh cho agent ${activeRole.value}.`)
  } catch {
    toast.error('Không sao chép được (clipboard bị chặn).')
  }
}

async function reanalyze() {
  if (!selected.value) return
  reanalyzing.value = true
  try {
    selected.value = await api.reanalyzeClientRequest(selected.value.request_id)
    await loadRole(activeRole.value)
    toast.success('Đã phân tích lại trên kho đặc tả hiện tại.')
  } catch (e) {
    toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    reanalyzing.value = false
  }
}

function fmt(n) {
  return n == null ? '—' : Number(n).toFixed(3)
}

onMounted(refreshList)
</script>

<template>
  <div class="grid cols-2">
    <div class="card">
      <h2>Gửi yêu cầu từ khách hàng</h2>
      <label class="field">
        <span class="field-label">Tiêu đề</span>
        <input v-model="form.title" placeholder="vd: Session tự gia hạn khi còn hoạt động" />
      </label>
      <label class="field">
        <span class="field-label">Mô tả chi tiết</span>
        <textarea
          v-model="form.description"
          rows="5"
          placeholder="Mô tả tính năng mới hoặc lỗi phát sinh mà khách cung cấp…"
          @keydown.ctrl.enter="submit"
        />
      </label>
      <div class="row wrap" style="gap:.8rem">
        <label class="field" style="flex:1;min-width:140px">
          <span class="field-label">Loại yêu cầu</span>
          <select v-model="form.request_type">
            <option value="feature">Thêm/thay đổi tính năng</option>
            <option value="bug">Sửa lỗi</option>
          </select>
        </label>
        <label class="field" style="flex:1;min-width:140px">
          <span class="field-label">Dự án (tùy chọn)</span>
          <input v-model="form.project" placeholder="lọc đặc tả theo dự án" />
        </label>
        <label class="field" style="flex:1;min-width:140px">
          <span class="field-label">Người yêu cầu (tùy chọn)</span>
          <input v-model="form.requester" placeholder="tên khách / đầu mối" />
        </label>
      </div>
      <button class="btn btn-primary" :disabled="submitting" @click="submit">
        <span v-if="submitting" class="spinner"></span>
        {{ submitting ? 'Đang phân tích…' : '✉ Gửi & truy xuất đặc tả liên quan' }}
      </button>
      <p class="faint mt1 mb0" style="font-size:.8rem">
        Hệ thống truy xuất đặc tả hiện có liên quan và đóng gói ngữ cảnh có trích dẫn cho agent
        PM/Coder/Tester. Ctrl+Enter để gửi nhanh.
      </p>
    </div>

    <div class="card">
      <h2>Danh sách yêu cầu ({{ requests.length }})</h2>
      <p v-if="!requests.length" class="faint">Chưa có yêu cầu nào.</p>
      <div
        v-for="r in requests"
        :key="r.request_id"
        class="card"
        style="background:var(--bg);margin-bottom:.6rem;cursor:pointer"
        @click="select(r.request_id)"
      >
        <div class="row spread">
          <strong>{{ r.title }}</strong>
          <span class="badge" :class="r.request_type === 'bug' ? 'badge-warn' : 'badge-ok'">
            {{ r.request_type === 'bug' ? 'Sửa lỗi' : 'Tính năng' }}
          </span>
        </div>
        <div class="row wrap faint" style="gap:1rem;font-size:.78rem;margin-top:.3rem">
          <span class="mono">{{ r.request_id }}</span>
          <span v-if="r.project">dự án: {{ r.project }}</span>
          <span v-if="r.context">
            {{ r.context.has_related_specs ? 'có đặc tả liên quan' : '⚠️ chưa có đặc tả' }}
          </span>
        </div>
      </div>
    </div>
  </div>

  <div v-if="selected" class="card mt1">
    <div class="section-head">
      <h2 class="mb0">{{ selected.title }}</h2>
      <button class="btn" :disabled="reanalyzing" @click="reanalyze">
        <span v-if="reanalyzing" class="spinner"></span>
        {{ reanalyzing ? 'Đang phân tích…' : '⟳ Phân tích lại' }}
      </button>
    </div>
    <p style="white-space:pre-wrap">{{ selected.description }}</p>

    <div v-if="selected.context && !selected.context.has_related_specs" class="card" style="background:var(--bg)">
      ⚠️ {{ selected.context.warning }}
    </div>

    <template v-if="selected.context && selected.context.has_related_specs">
      <h3>Tài liệu đặc tả bị ảnh hưởng ({{ selected.context.related_documents.length }})</h3>
      <div class="row wrap" style="gap:.5rem;margin-bottom:.8rem">
        <span v-for="d in selected.context.related_documents" :key="d.source" class="badge badge-ok mono">
          {{ d.source }} ({{ d.excerpt_count }} đoạn, score {{ fmt(d.best_score) }})
        </span>
      </div>

      <h3>Trích đoạn đặc tả liên quan ({{ selected.context.excerpts.length }})</h3>
      <div
        v-for="(e, i) in selected.context.excerpts"
        :key="i"
        class="card"
        style="background:var(--bg);margin-bottom:.8rem"
      >
        <div class="row spread">
          <span class="mono">[{{ i + 1 }}] {{ e.source }}<span v-if="e.heading"> › {{ e.heading }}</span></span>
          <span class="badge badge-ok">score {{ fmt(e.score) }}</span>
        </div>
        <div v-if="e.start_line" class="faint" style="font-size:.78rem;margin:.3rem 0 .5rem">
          dòng {{ e.start_line }}–{{ e.end_line }}
        </div>
        <pre class="pre" style="white-space:pre-wrap">{{ e.text }}</pre>
      </div>
    </template>

    <div class="section-head mt1">
      <h3 class="mb0">Ngữ cảnh cho agent</h3>
      <div class="row" style="gap:.4rem">
        <button
          v-for="r in ROLES"
          :key="r.key"
          class="btn"
          :class="{ 'btn-primary': activeRole === r.key }"
          @click="loadRole(r.key)"
        >
          {{ r.label }}
        </button>
        <button class="btn" :disabled="!roleContext" @click="copyMarkdown">📋 Sao chép Markdown</button>
      </div>
    </div>
    <p class="faint" style="font-size:.8rem">
      Dán markdown này vào prompt của agent {{ activeRole }} — gồm yêu cầu, quy tắc chống ảo giác và
      trích đoạn đặc tả có nguồn.
    </p>
    <div v-if="loadingContext" class="faint"><span class="spinner"></span> Đang tải…</div>
    <pre v-else-if="roleContext" class="pre" style="white-space:pre-wrap;max-height:420px;overflow:auto">{{
      roleContext.markdown
    }}</pre>
  </div>
</template>
