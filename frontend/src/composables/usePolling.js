import { onUnmounted, ref } from 'vue'

// Poll một hàm async theo interval. Tự dừng khi component unmount.
// Backend không có realtime (WebSocket/SSE) nên polling là cơ chế duy nhất.
export function usePolling(fn, intervalMs = 3000) {
  const active = ref(false)
  let timer = null
  let stopped = false

  async function tick() {
    if (stopped) return
    try {
      await fn()
    } catch {
      /* lỗi được xử lý trong fn */
    } finally {
      if (!stopped && active.value) timer = setTimeout(tick, intervalMs)
    }
  }

  function start() {
    if (active.value) return
    active.value = true
    stopped = false
    tick()
  }
  function stop() {
    active.value = false
    stopped = true
    if (timer) clearTimeout(timer)
    timer = null
  }

  onUnmounted(stop)
  return { active, start, stop }
}
