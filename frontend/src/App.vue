<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">跨系统数据交换与批量传输平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向异构系统间批量数据交换的字段契约、增量窗口抽取、暂存落地、校验和对账、断点续传与到达核对平台。</span>
        <span class="head-user">当前值班：数据工程组</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "源端登记", path: "/source_register" }, { label: "目标端登记", path: "/target_register" }, { label: "字段契约", path: "/field_contract" }, { label: "增量窗口", path: "/extract_window" }, { label: "传输批次", path: "/transfer_batch" }, { label: "暂存落地", path: "/staging_area" }, { label: "校验核对", path: "/checksum_verify" }, { label: "到达对账", path: "/arrival_reconcile" }, { label: "字段冲突", path: "/conflict_resolve" }, { label: "断点续传", path: "/resume_point" }, { label: "速率整形", path: "/speed_control" }, { label: "拒收回执", path: "/reject_record" }, { label: "待重新映射清单", path: "/remap_worklist" }, { label: "格式适配", path: "/format_adapt" }, { label: "传输血缘", path: "/transfer_lineage" }, { label: "批次归档", path: "/history_archive" }, { label: "历史重放", path: "/exchange_replay" }, { label: "时效监控", path: "/sla_monitor" }, { label: "通道配置", path: "/channel_config" }]
</script>
