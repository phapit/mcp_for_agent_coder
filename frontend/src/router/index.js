import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { titleKey: 'nav.dashboard' },
  },
  {
    path: '/projects',
    name: 'projects',
    component: () => import('@/views/ProjectsView.vue'),
    meta: { titleKey: 'nav.projects' },
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: () => import('@/views/TasksView.vue'),
    meta: { titleKey: 'nav.tasks' },
  },
  {
    path: '/client-requests',
    name: 'client-requests',
    component: () => import('@/views/ClientRequestsView.vue'),
    meta: { titleKey: 'nav.clientRequests' },
  },
  {
    path: '/answer',
    name: 'answer',
    component: () => import('@/views/AnswerView.vue'),
    meta: { titleKey: 'nav.answer' },
  },
  {
    path: '/search',
    name: 'search',
    component: () => import('@/views/SearchView.vue'),
    meta: { titleKey: 'nav.search' },
  },
  {
    path: '/ingest-excel',
    name: 'ingest-excel',
    component: () => import('@/views/IngestExcelView.vue'),
    meta: { titleKey: 'nav.ingestExcel' },
  },
  {
    path: '/ingest-spreadsheet',
    name: 'ingest-spreadsheet',
    component: () => import('@/views/IngestSpreadsheetView.vue'),
    meta: { titleKey: 'nav.ingestSpreadsheet' },
  },
  {
    path: '/custom-report',
    name: 'custom-report',
    component: () => import('@/views/CustomReportView.vue'),
    meta: { titleKey: 'nav.customReport' },
  },
  {
    path: '/logs',
    name: 'logs',
    component: () => import('@/views/ActivityLogView.vue'),
    meta: { titleKey: 'nav.activityLog' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { titleKey: 'nav.settings' },
  },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
