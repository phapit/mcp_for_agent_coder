<script setup>
import { reactive, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { useToast } from '@/composables/useToast'
import { useI18n } from '@/i18n'

const toast = useToast()
const { t } = useI18n()

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
    toast.success(t('ingestExcel.scanDone', { count: n }))
  } catch (e) {
    if (e?.status === 404) toast.error(t('ingestExcel.noXlsx'))
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
    toast.error(t('ingestExcel.pickFileFirst'))
    return
  }
  uploading.value = true
  try {
    uploadResult.value = await api.ingestExcelUpload(picked.value, opts.use_online_model ? 1 : 0)
    toast.success(t('ingestExcel.uploadDone', { file: uploadResult.value?.file || picked.value.name }))
    picked.value = null
    if (fileInput.value) fileInput.value.value = ''
  } catch (e) {
    if (e?.status === 413) toast.error(t('ingestExcel.fileTooLarge'))
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
    <h2>{{ t('ingestExcel.title') }}</h2>
    <p class="faint mt0" style="font-size:.85rem">
      {{ t('ingestExcel.description') }}
    </p>
    <div class="row wrap" style="gap:1rem;margin:.6rem 0 1rem">
      <label class="row" style="gap:.4rem;width:auto">
        <input type="checkbox" v-model="opts.force" style="width:auto" /> {{ t('ingestExcel.forceLabel') }}
      </label>
      <label class="field" style="width:auto;margin:0">
        <span class="field-label">{{ t('ingestExcel.refineModelLabel') }}</span>
        <select v-model.number="opts.use_online_model">
          <option :value="0">{{ t('answer.modelOllama') }}</option>
          <option :value="1">{{ t('answer.modelOpenAI') }}</option>
        </select>
      </label>
    </div>
    <button class="btn btn-primary" :disabled="scanning" @click="scan">
      <span v-if="scanning" class="spinner"></span>
      {{ scanning ? t('ingestExcel.scanning') : t('ingestExcel.scanButton') }}
    </button>
  </div>

  <div class="card mt1">
    <h2>{{ t('ingestExcel.uploadTitle') }}</h2>
    <div class="row wrap" style="gap:.8rem;align-items:center">
      <input ref="fileInput" type="file" accept=".xlsx" @change="onPick" style="width:auto" />
      <button class="btn btn-primary" :disabled="uploading || !picked" @click="upload">
        <span v-if="uploading" class="spinner"></span>
        {{ uploading ? t('ingestExcel.uploading') : t('ingestExcel.uploadButton') }}
      </button>
    </div>
    <div v-if="uploadResult" class="card mt1" style="background:var(--bg)">
      <div class="row spread"><span class="muted">{{ t('ingestExcel.file') }}</span><span class="mono">{{ uploadResult.file }}</span></div>
      <div class="row spread"><span class="muted">{{ t('ingestExcel.outputMd') }}</span><span class="mono">{{ uploadResult.output_md }}</span></div>
      <div class="row spread"><span class="muted">{{ t('ingestExcel.imageCount') }}</span><span>{{ uploadResult.image_count ?? '—' }}</span></div>
    </div>
  </div>

  <div v-if="result" class="card mt1">
    <h2>{{ t('ingestExcel.scanResult') }}</h2>
    <div class="grid cols-3">
      <div class="stat"><span class="stat-label">{{ t('ingestExcel.processed') }}</span><span class="stat-value" style="color:var(--ok)">{{ len(result.processed) }}</span></div>
      <div class="stat"><span class="stat-label">{{ t('ingestExcel.skipped') }}</span><span class="stat-value">{{ len(result.skipped) }}</span></div>
      <div class="stat"><span class="stat-label">{{ t('ingestExcel.errors') }}</span><span class="stat-value" :style="len(result.failed) ? 'color:var(--err)' : ''">{{ len(result.failed) }}</span></div>
    </div>
    <table v-if="len(result.processed)" class="mt1">
      <thead><tr><th>{{ t('ingestExcel.file') }}</th><th>{{ t('ingestExcel.outputMd') }}</th><th>{{ t('ingestExcel.imageCount') }}</th></tr></thead>
      <tbody>
        <tr v-for="(p, i) in result.processed" :key="i">
          <td class="mono">{{ p.file }}</td>
          <td class="mono muted">{{ p.output_md }}</td>
          <td>{{ p.image_count ?? '—' }}</td>
        </tr>
      </tbody>
    </table>
    <details class="mt1">
      <summary class="muted" style="cursor:pointer">{{ t('common.viewJson') }}</summary>
      <pre class="pre mt1">{{ JSON.stringify(result, null, 2) }}</pre>
    </details>
  </div>
</template>
