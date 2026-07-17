<script setup>
import { onMounted, ref } from 'vue'
import { LANGUAGES } from '@/constants/languages'
import { useSettings } from '@/composables/useSettings'
import { useToast } from '@/composables/useToast'
import { useI18n } from '@/i18n'

const toast = useToast()
const { settings, ready, setDefaultLanguage } = useSettings()
const { t } = useI18n()

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
    toast.success(t('settings.saveSuccess'))
  } catch (e) {
    toast.error(t('settings.saveError', { error: e }))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="card">
    <h2 class="mb0">{{ t('settings.title') }}</h2>
    <p class="faint mt0" style="font-size:.85rem">
      {{ t('settings.description') }}
    </p>

    <label class="field" style="max-width:320px">
      <span class="field-label">{{ t('settings.defaultLanguageLabel') }}</span>
      <select v-model="selected">
        <option v-for="l in LANGUAGES" :key="l.code" :value="l.code">{{ l.label }}</option>
      </select>
    </label>

    <button class="btn btn-primary" :disabled="saving" @click="save">
      <span v-if="saving" class="spinner"></span>
      {{ saving ? t('settings.saving') : t('settings.saveButton') }}
    </button>
  </div>
</template>
