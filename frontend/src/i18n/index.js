import { reactive, computed } from 'vue'
import vi from './locales/vi'
import ja from './locales/ja'

// Ngôn ngữ HIỂN THỊ giao diện (UI chrome). Khác với `useSettings().defaultLanguage`
// (composables/useSettings.js) vốn là ngôn ngữ ĐẦU RA report NotebookLM — hai khái niệm
// tách biệt hoàn toàn, không dùng chung storage key.
const STORAGE_KEY = 'uiLocale'
const LOCALES = { vi, ja }
const FALLBACK = 'vi'

function readInitialLocale() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && LOCALES[saved]) return saved
  } catch {
    // localStorage không khả dụng (vd SSR/private mode) → dùng mặc định
  }
  return FALLBACK
}

const state = reactive({ locale: readInitialLocale() })

function setLocale(code) {
  if (!LOCALES[code]) return
  state.locale = code
  try {
    localStorage.setItem(STORAGE_KEY, code)
  } catch {
    // bỏ qua nếu không lưu được
  }
}

function lookup(dict, key) {
  return key.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), dict)
}

function translate(key, params) {
  let msg = lookup(LOCALES[state.locale], key)
  if (msg == null) msg = lookup(LOCALES[FALLBACK], key)
  if (msg == null) return key
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      msg = msg.replaceAll(`{${k}}`, v)
    }
  }
  return msg
}

export function useI18n() {
  return {
    locale: computed(() => state.locale),
    setLocale,
    t: translate,
    availableLocales: Object.keys(LOCALES),
  }
}
