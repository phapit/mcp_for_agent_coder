<script setup>
import { onMounted, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import StatusBadge from '@/components/StatusBadge.vue'
import ToastHost from '@/components/ToastHost.vue'
import { usePolling } from '@/composables/usePolling'

const route = useRoute()

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

const nav = [
  { to: '/dashboard', label: 'Tổng quan', ico: '◧' },
  { to: '/projects', label: 'Quản lý dự án', ico: '❖' },
  { to: '/tasks', label: 'Tình trạng task', ico: '⟳' },
  { to: '/logs', label: 'Log hoạt động', ico: '☰' },
]
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo">O</div>
        <div>
          <div class="brand-name">Obsidian-Wiki</div>
          <div class="brand-sub">Control Panel</div>
        </div>
      </div>

      <RouterLink v-for="n in nav" :key="n.to" :to="n.to" class="nav-link">
        <span class="ico">{{ n.ico }}</span>{{ n.label }}
      </RouterLink>

      <div class="sidebar-foot">
        <div class="row spread" style="margin-bottom:.3rem">
          <span>knowledge</span><StatusBadge :status="health.knowledge" />
        </div>
        <div class="row spread">
          <span>agent</span><StatusBadge :status="health.agent" />
        </div>
      </div>
    </aside>

    <div class="main">
      <div class="topbar">
        <h1 class="mb0">{{ route.meta.title || 'Obsidian-Wiki' }}</h1>
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
