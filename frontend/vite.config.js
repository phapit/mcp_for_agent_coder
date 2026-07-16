import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// Proxy dev: forward /api/knowledge -> knowledge_service, /api/agent -> agent_service.
// X-API-Key được inject Ở PHÍA SERVER (node dev process), KHÔNG lọt vào bundle browser.
export default defineConfig(({ mode }) => {
  // prefix '' => nạp cả biến không có tiền tố VITE_ (vd SERVICE_API_KEY) để dùng trong config.
  const env = loadEnv(mode, process.cwd(), '')

  const KNOWLEDGE_TARGET = env.VITE_KNOWLEDGE_TARGET || 'http://localhost:8002'
  const AGENT_TARGET = env.VITE_AGENT_TARGET || 'http://localhost:8003'
  const API_KEY = env.SERVICE_API_KEY || ''

  const withApiKey = (proxyOptions) => ({
    changeOrigin: true,
    configure: (proxy) => {
      proxy.on('proxyReq', (proxyReq) => {
        if (API_KEY) proxyReq.setHeader('X-API-Key', API_KEY)
      })
    },
    ...proxyOptions,
  })

  return {
    plugins: [vue()],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: {
      port: Number(env.VITE_PORT) || 5173,
      proxy: {
        '/api/knowledge': withApiKey({
          target: KNOWLEDGE_TARGET,
          rewrite: (p) => p.replace(/^\/api\/knowledge/, ''),
        }),
        '/api/agent': withApiKey({
          target: AGENT_TARGET,
          rewrite: (p) => p.replace(/^\/api\/agent/, ''),
        }),
      },
    },
  }
})
