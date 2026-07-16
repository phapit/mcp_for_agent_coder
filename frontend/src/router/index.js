import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { title: 'Tổng quan' },
  },
  {
    path: '/projects',
    name: 'projects',
    component: () => import('@/views/ProjectsView.vue'),
    meta: { title: 'Quản lý dự án' },
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: () => import('@/views/TasksView.vue'),
    meta: { title: 'Tình trạng task' },
  },
  {
    path: '/answer',
    name: 'answer',
    component: () => import('@/views/AnswerView.vue'),
    meta: { title: 'Hỏi đáp (RAG)' },
  },
  {
    path: '/search',
    name: 'search',
    component: () => import('@/views/SearchView.vue'),
    meta: { title: 'Tìm kiếm ngữ cảnh' },
  },
  {
    path: '/ingest-excel',
    name: 'ingest-excel',
    component: () => import('@/views/IngestExcelView.vue'),
    meta: { title: 'Ingest Excel' },
  },
  {
    path: '/ingest-spreadsheet',
    name: 'ingest-spreadsheet',
    component: () => import('@/views/IngestSpreadsheetView.vue'),
    meta: { title: 'Ingest Spreadsheet' },
  },
  {
    path: '/logs',
    name: 'logs',
    component: () => import('@/views/ActivityLogView.vue'),
    meta: { title: 'Log hoạt động' },
  },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
