import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import RemapWorkbench from '@/views/RemapWorkbench.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 补转换工作台有专用操作（筛选/补发/领用/补转换），需排在动态模块路由之前
    { path: '/remap_worklist', name: 'remap-workbench', component: RemapWorkbench },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
