<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: '' },
})

// Map trạng thái backend -> loại hiển thị (ok/warn/err/neutral).
const MAP = {
  ok: 'ok', up: 'ok', completed: 'ok', succeeded: 'ok', ingested: 'ok', true: 'ok',
  running: 'warn', queued: 'warn', retrying: 'warn', started: 'warn', pending: 'warn',
  completed_with_errors: 'warn',
  failed: 'err', dead_lettered: 'err', dead_letter: 'err', error: 'err', down: 'err', false: 'err',
  never_run: 'neutral', skipped: 'neutral', removed: 'neutral', unknown: 'neutral',
}

const kind = computed(() => MAP[String(props.status).toLowerCase()] || 'neutral')
const label = computed(() => props.status || '—')
</script>

<template>
  <span class="badge" :class="`badge-${kind}`">
    <span class="dot" :class="`dot-${kind}`"></span>
    {{ label }}
  </span>
</template>
