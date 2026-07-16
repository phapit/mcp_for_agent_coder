// Lớp gọi API mỏng. Mọi request đi qua Vite proxy (/api/knowledge, /api/agent),
// proxy tự gắn X-API-Key nên client-side KHÔNG giữ secret.

class ApiError extends Error {
  constructor(message, { status, detail, url } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.url = url
  }
}

async function request(base, path, { method = 'GET', body, query, headers } = {}) {
  let url = base + path
  if (query) {
    const qs = new URLSearchParams(
      Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== ''),
    ).toString()
    if (qs) url += `?${qs}`
  }

  const opts = { method, headers: { ...(headers || {}) } }
  if (body !== undefined) {
    if (body instanceof FormData) {
      opts.body = body
    } else {
      opts.headers['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    }
  }

  let res
  try {
    res = await fetch(url, opts)
  } catch (e) {
    throw new ApiError(`Không kết nối được backend (${url}). Kiểm tra dev server / VITE_*_TARGET.`, { url })
  }

  const text = await res.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!res.ok) {
    const detail = data && typeof data === 'object' ? data.detail ?? data : data
    const msg = typeof detail === 'string' ? detail : `HTTP ${res.status}`
    throw new ApiError(msg, { status: res.status, detail, url })
  }
  return data
}

const KNOWLEDGE = '/api/knowledge'
const AGENT = '/api/agent'

const kn = (path, opts) => request(KNOWLEDGE, path, opts)
const ag = (path, opts) => request(AGENT, path, opts)

export const api = {
  // ---- Health ----
  knowledgeReady: () => kn('/health/ready'),
  agentReady: () => ag('/health/ready'),

  // ---- Quản lý dự án (project notebook configs) ----
  // Liệt kê TẤT CẢ dự án (gom nhóm theo project_name) — nguồn sự thật từ backend.
  listAllProjects: () => kn('/project-notebook-configs'),
  listProjectConfigs: (projectName) =>
    kn(`/project-notebook-configs/${encodeURIComponent(projectName)}`),
  getProjectConfig: (projectName, env) =>
    kn(`/project-notebook-configs/${encodeURIComponent(projectName)}/${encodeURIComponent(env)}`),
  upsertProjectConfig: (payload) =>
    kn('/project-notebook-configs', { method: 'POST', body: payload }),
  updateProjectConfig: (projectName, env, payload) =>
    kn(`/project-notebook-configs/${encodeURIComponent(projectName)}/${encodeURIComponent(env)}`, {
      method: 'PUT',
      body: payload,
    }),
  deleteProjectConfig: (projectName, env) =>
    kn(`/project-notebook-configs/${encodeURIComponent(projectName)}/${encodeURIComponent(env)}`, {
      method: 'DELETE',
    }),

  // ---- Task / Ingest ----
  ingest: (payload) => kn('/ingest', { method: 'POST', body: payload }),
  ingestStatus: () => kn('/ingest/status'),
  ingestJob: (jobId) => kn(`/ingest/jobs/${encodeURIComponent(jobId)}`),
  ingestHistory: (limit = 20) => kn('/ingest/history', { query: { limit } }),
  ingestDocuments: (status) => kn('/ingest/documents', { query: { status } }),
  deadLetter: () => kn('/ingest/dead-letter'),
  requeueDeadLetter: (documentId) =>
    kn('/ingest/dead-letter/requeue', { method: 'POST', query: { document_id: documentId } }),

  // ---- Q&A / Search ----
  search: (payload) => kn('/search', { method: 'POST', body: payload }),
  answer: (payload) => kn('/answer', { method: 'POST', body: payload }),

  // ---- Ingest chuyên biệt (Excel / Spreadsheet) ----
  ingestExcel: (payload) => kn('/ingest-excel', { method: 'POST', body: payload }),
  ingestExcelUpload: (file, useOnlineModel = 0) => {
    const fd = new FormData()
    fd.append('file', file)
    return kn('/ingest-excel/upload', {
      method: 'POST',
      body: fd,
      query: { use_online_model: useOnlineModel },
    })
  },
  ingestSpreadsheet: (payload) => kn('/ingest-spreadsheet', { method: 'POST', body: payload }),

  // ---- Yêu cầu khách hàng (client requests) ----
  createClientRequest: (payload) => kn('/client-requests', { method: 'POST', body: payload }),
  listClientRequests: (limit = 50) => kn('/client-requests', { query: { limit } }),
  getClientRequest: (id) => kn(`/client-requests/${encodeURIComponent(id)}`),
  getClientRequestContext: (id, role) =>
    kn(`/client-requests/${encodeURIComponent(id)}/context`, { query: { role } }),
  reanalyzeClientRequest: (id) =>
    kn(`/client-requests/${encodeURIComponent(id)}/reanalyze`, { method: 'POST' }),

  // ---- Git (agent_service) ----
  gitStatus: () => ag('/git/status'),
  createBranch: (name) => ag('/git/branch', { method: 'POST', body: { name } }),
}

export { ApiError }
