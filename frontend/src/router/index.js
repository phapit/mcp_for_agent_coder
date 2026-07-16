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
