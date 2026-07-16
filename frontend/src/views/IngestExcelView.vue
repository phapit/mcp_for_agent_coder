<script setup>
import { reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const opts = reactive({ force: false, use_online_model: 0 })
const scanning = ref(false)
const uploading = ref(false)
const result = ref(null) // kết quả quét thư mục
const uploadResult = ref(null)
const fileInput = ref(null)
const picked = ref(null)

async function scan() {
  scanning.value = true
  try {
    result.value = await api.ingestExcel({
      force: opts.force,
      use_online_model: opts.use_online_model ? 1 : 0,
    })
    const n = result.value?.processed?.length ?? 0
    toast.success(`Quét xong: ${n} file được xử lý.`)
  } catch (e) {
    if (e?.status === 404) toast.error('Không tìm thấy file .xlsx nào trong thư mục nguồn (404).')
    else toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    scanning.value = false
  }
}

function onPick(ev) {
  picked.value = ev.target.files?.[0] || null
}

async function upload() {
  if (!picked.value) {
    toast.error('Chọn 1 file .xlsx trước.')
    return
  }
  uploading.value = true
  try {
    uploadResult.value = await api.ingestExcelUpload(picked.value, opts.use_online_model ? 1 : 0)
    toast.success(`Đã xử lý: ${uploadResult.value?.file || picked.value.name}`)
    picked.value = null
    if (fileInput.value) fileInput.value.value = ''
  } catch (e) {
    if (e?.status === 413) toast.error('File vượt quá giới hạn dung lượng (413).')
    else toast.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    uploading.value = false
  }
}

function len(v) {
  return Array.isArray(v) ? v.length : 0
}
</script>

<template>
  <div class="card">
    <h2>Chuyển Excel → Markdown</h2>
    <p class="faint mt0" style="font-size:.85rem">
      Convert file .xlsx thành Markdown (dùng vision LLM để caption ảnh nhúng), sau đó tự động ingest.
    </p>
    <div class="row wrap" style="gap:1rem;margin:.6rem 0 1rem">
      <label class="row" style="gap:.4rem;width:auto">
        <input type="checkbox" v-model="opts.force" style="width:auto" /> force (bỏ qua content-hash)
      </label>
      <label class="field" style="width:auto;margin:0">
        <span class="field-label">Mô hình refine</span>
        <select v-model.number="opts.use_online_model">
          <option :value="0">Ollama (local)</option>
          <option :value="1">OpenAI gpt-4o-mini (online)</option>
        </select>
      </label>
    </div>
    <button class="btn btn-primary" :disabled="scanning" @click="scan">
      <span v-if="scanning" class="spinner"></span>
      {{ scanning ? 'Đang quét…' : '▶ Quét thư mục nguồn' }}
    </button>
  </div>

  <div class="card mt1">
    <h2>Upload 1 file .xlsx ad-hoc</h2>
    <div class="row wrap" style="gap:.8rem;align-items:center">
      <input ref="fileInput" type="file" accept=".xlsx" @change="onPick" style="width:auto" />
      <button class="btn btn-primary" :disabled="uploading || !picked" @click="upload">
        <span v-if="uploading" class="spinner"></span>
        {{ uploading ? 'Đang xử lý…' : '⬆ Upload & xử lý' }}
      </button>
    </div>
    <div v-if="uploadResult" class="card mt1" style="background:var(--bg)">
      <div class="row spread"><span class="muted">File</span><span class="mono">{{ uploadResult.file }}</span></div>
      <div class="row spread"><span class="muted">Output MD</span><span class="mono">{{ uploadResult.output_md }}</span></div>
      <div class="row spread"><span class="muted">Số ảnh</span><span>{{ uploadResult.image_count ?? '—' }}</span></div>
    </div>
  </div>

  <div v-if="result" class="card mt1">
    <h2>Kết quả quét thư mục</h2>
    <div class="grid cols-3">
      <div class="stat"><span class="stat-label">Đã xử lý</span><span class="stat-value" style="color:var(--ok)">{{ len(result.processed) }}</span></div>
      <div class="stat"><span class="stat-label">Bỏ qua</span><span class="stat-value">{{ len(result.skipped) }}</span></div>
      <div class="stat"><span class="stat-label">Lỗi</span><span class="stat-value" :style="len(result.failed) ? 'color:var(--err)' : ''">{{ len(result.failed) }}</span></div>
    </div>
    <table v-if="len(result.processed)" class="mt1">
      <thead><tr><th>File</th><th>Output MD</th><th>Số ảnh</th></tr></thead>
      <tbody>
        <tr v-for="(p, i) in result.processed" :key="i">
          <td class="mono">{{ p.file }}</td>
          <td class="mono muted">{{ p.output_md }}</td>
          <td>{{ p.image_count ?? '—' }}</td>
        </tr>
      </tbody>
    </table>
    <details class="mt1">
      <summary class="muted" style="cursor:pointer">Xem JSON đầy đủ</summary>
      <pre class="pre mt1">{{ JSON.stringify(result, null, 2) }}</pre>
    </details>
  </div>
</template>
