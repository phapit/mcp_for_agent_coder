import { reactive } from 'vue'

const state = reactive({ items: [] })
let seq = 0

export function useToast() {
  function push(message, type = 'info', timeout = 4000) {
    const id = ++seq
    state.items.push({ id, message, type })
    if (timeout) setTimeout(() => dismiss(id), timeout)
    return id
  }
  function dismiss(id) {
    const i = state.items.findIndex((t) => t.id === id)
    if (i !== -1) state.items.splice(i, 1)
  }
  return {
    toasts: state.items,
    dismiss,
    info: (m) => push(m, 'info'),
    success: (m) => push(m, 'success'),
    error: (m) => push(m, 'error', 6000),
  }
}
