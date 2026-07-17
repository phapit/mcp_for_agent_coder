<script setup>
import { onMounted, ref } from 'vue'
import { LANGUAGES } from '@/constants/languages'
import { useSettings } from '@/composables/useSettings'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const { settings, ready, setDefaultLanguage } = useSettings()

const selected = ref('')
const saving = ref(false)

onMounted(async () => {
  await ready
  selected.value = settings.defaultLanguage
})

async function save() {
  saving.value = true
  try {
    await setDefaultLanguage(selected.value)
    toast.success('Đã lưu ngôn ngữ mặc định.')
  } catch (e) {
    toast.error(`Không thể lưu cài đặt: ${e}`)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="card">
    <h2 class="mb0">Cài đặt</h2>
    <p class="faint mt0" style="font-size:.85rem">
      Ngôn ngữ mặc định sẽ tự động điền vào các form "Ingest Spreadsheet" và "Xuất tài liệu theo yêu cầu".
      Cài đặt này được lưu trên trình duyệt (IndexedDB), không đồng bộ giữa các máy.
    </p>

    <label class="field" style="max-width:320px">
      <span class="field-label">Ngôn ngữ mặc định</span>
      <select v-model="selected">
        <option v-for="l in LANGUAGES" :key="l.code" :value="l.code">{{ l.label }}</option>
      </select>
    </label>

    <button class="btn btn-primary" :disabled="saving" @click="save">
      <span v-if="saving" class="spinner"></span>
      {{ saving ? 'Đang lưu…' : '💾 Lưu cài đặt' }}
    </button>
  </div>
</template>
