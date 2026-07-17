<script setup>
import { useI18n } from '@/i18n'

defineProps({ title: { type: String, default: '' } })
const emit = defineEmits(['close'])
const { t } = useI18n()
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2 class="mb0">{{ title }}</h2>
        <button class="btn btn-sm" @click="emit('close')" :aria-label="t('modal.close')">✕</button>
      </div>
      <div class="modal-body"><slot /></div>
      <div class="modal-foot"><slot name="footer" /></div>
    </div>
  </div>
</template>
