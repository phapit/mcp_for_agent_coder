<script setup>
import { computed, onMounted, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import StatusBadge from '@/components/StatusBadge.vue'
import ToastHost from '@/components/ToastHost.vue'
import { usePolling } from '@/composables/usePolling'
import { useI18n } from '@/i18n'

const route = useRoute()
const { t, locale, setLocale } = useI18n()

const health = reactive({
  knowledge: 'unknown',
  agent: 'unknown',
})

async function refreshHealth() {
  const [k, a] = await Promise.allSettled([api.knowledgeReady(), api.agentReady()])
  health.knowledge = k.status === 'fulfilled' ? (k.value?.status || 'ok') : 'down'
  health.agent = a.status === 'fulfilled' ? (a.value?.status || 'ok') : 'down'
}

const { start } = usePolling(refreshHealth, 15000)
onMounted(() => {
  refreshHealth()
  start()
})

const nav = computed(() => [
  { to: '/dashboard', label: t('nav.dashboard'), ico: '◧' },
  { to: '/projects', label: t('nav.projects'), ico: '❖' },
  { to: '/tasks', label: t('nav.tasks'), ico: '⟳' },
  { to: '/client-requests', label: t('nav.clientRequests'), ico: '✉' },
  { to: '/answer', label: t('nav.answer'), ico: '✦' },
  { to: '/search', label: t('nav.search'), ico: '🔍' },
  { to: '/ingest-excel', label: t('nav.ingestExcel'), ico: '▤' },
  { to: '/ingest-spreadsheet', label: t('nav.ingestSpreadsheet'), ico: '▦' },
  { to: '/custom-report', label: t('nav.customReport'), ico: '✎' },
  { to: '/logs', label: t('nav.activityLog'), ico: '☰' },
  { to: '/settings', label: t('nav.settings'), ico: '⚙' },
])
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo">O</div>
        <div>
          <div class="brand-name">{{ t('app.brandName') }}</div>
          <div class="brand-sub">{{ t('app.brandSub') }}</div>
        </div>
      </div>

      <RouterLink v-for="n in nav" :key="n.to" :to="n.to" class="nav-link">
        <span class="ico">{{ n.ico }}</span>{{ n.label }}
      </RouterLink>

      <div class="sidebar-foot">
        <div class="row spread" style="margin-bottom:.3rem">
          <span>knowledge</span><StatusBadge :status="health.knowledge" />
        </div>
        <div class="row spread" style="margin-bottom:.6rem">
          <span>agent</span><StatusBadge :status="health.agent" />
        </div>
        <div class="row spread" :title="t('app.uiLanguage')">
          <button
            class="btn btn-sm"
            :class="{ 'btn-primary': locale === 'vi' }"
            style="flex:1"
            @click="setLocale('vi')"
          >VI</button>
          <button
            class="btn btn-sm"
            :class="{ 'btn-primary': locale === 'ja' }"
            style="flex:1"
            @click="setLocale('ja')"
          >日本語</button>
        </div>
      </div>
    </aside>

    <div class="main">
      <div class="topbar">
        <h1 class="mb0">{{ route.meta.titleKey ? t(route.meta.titleKey) : t('app.defaultTitle') }}</h1>
        <div class="row">
          <StatusBadge :status="health.knowledge" />
          <StatusBadge :status="health.agent" />
        </div>
      </div>
      <div class="content">
        <RouterView />
      </div>
    </div>

    <ToastHost />
  </div>
</template>
