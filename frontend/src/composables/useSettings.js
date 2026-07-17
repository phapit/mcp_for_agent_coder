import { reactive } from 'vue'

const DB_NAME = 'obsidian-wiki-settings'
const DB_VERSION = 1
const STORE_NAME = 'settings'
const DEFAULT_LANGUAGE_KEY = 'defaultLanguage'

const state = reactive({
  defaultLanguage: '',
  loaded: false,
})

let dbPromise = null
function openDb() {
  if (dbPromise) return dbPromise
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE_NAME)) {
        req.result.createObjectStore(STORE_NAME)
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
  return dbPromise
}

async function getValue(key) {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly')
    const req = tx.objectStore(STORE_NAME).get(key)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function setValue(key, value) {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).put(value, key)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

let loadPromise = null
function loadSettings() {
  if (loadPromise) return loadPromise
  loadPromise = (async () => {
    try {
      const lang = await getValue(DEFAULT_LANGUAGE_KEY)
      if (lang) state.defaultLanguage = lang
    } catch (e) {
      console.error('Không thể đọc cài đặt từ IndexedDB:', e)
    } finally {
      state.loaded = true
    }
  })()
  return loadPromise
}

export function useSettings() {
  const ready = loadSettings()

  async function setDefaultLanguage(lang) {
    state.defaultLanguage = lang
    try {
      await setValue(DEFAULT_LANGUAGE_KEY, lang)
    } catch (e) {
      console.error('Không thể lưu cài đặt vào IndexedDB:', e)
      throw e
    }
  }

  return {
    settings: state,
    ready,
    setDefaultLanguage,
  }
}
