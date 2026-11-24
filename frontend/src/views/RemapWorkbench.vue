<template>
  <section class="page" data-module="remap_worklist">
    <header class="page-head">
      <div>
        <h2>待重新映射清单（补转换工作台）</h2>
        <p class="page-desc">
          拒收回执与字段契约共享：按拒收原因筛选回执与字段映射明细，生成待重新映射记录清单；
          源端补发更正后领用并补转换，转换键幂等，同一条记录不会被重复转换。
        </p>
      </div>
    </header>

    <!-- 第一步：按原因查询拒收回执 + 字段映射明细 -->
    <form class="filter-bar" @submit.prevent="searchRejections">
      <label class="filter-item">
        <span>拒收原因</span>
        <input v-model="reason" data-testid="filter-reason" placeholder="如：数值错误" />
      </label>
      <label class="filter-item">
        <span>批次编号</span>
        <input v-model="batchCode" data-testid="filter-batch" placeholder="可选，按批次过滤" />
      </label>
      <button class="btn" data-testid="query-reason" type="submit">查询拒收与映射明细</button>
      <button class="btn primary" data-testid="build-worklist" type="button" @click="buildWorklist">
        生成待重新映射清单
      </button>
    </form>

    <p v-if="message" class="page-foot">
      <span :class="message.error ? 'error-text' : ''">{{ message.text }}</span>
    </p>

    <h3>筛选结果（原拒收原因 + 实际映射版本）</h3>
    <table class="data-table" data-testid="rejection-table">
      <thead>
        <tr>
          <th>记录主键</th><th>批次编号</th><th>拒收原因</th><th>拒收环节</th>
          <th>契约编号</th><th>源字段</th><th>目标字段</th><th>映射版本</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rejections" :key="row.拒收编号">
          <td>{{ row.记录主键 }}</td>
          <td>{{ row.批次编号 }}</td>
          <td>{{ row.拒收原因 }}</td>
          <td>{{ row.拒收环节 }}</td>
          <td>{{ row.契约编号 }}</td>
          <td>{{ row.源字段 }}</td>
          <td>{{ row.目标字段 }}</td>
          <td>{{ row.映射版本 }}</td>
        </tr>
        <tr v-if="!rejections.length">
          <td colspan="8" class="empty-state">先输入拒收原因查询待处置回执</td>
        </tr>
      </tbody>
    </table>

    <!-- 第二步：源端补发更正 -->
    <h3>源端补发更正（JSON 数组，按记录主键回填）</h3>
    <form class="analysis-form" @submit.prevent="sendCorrections">
      <textarea
        v-model="correctionText"
        data-testid="correction-input"
        rows="6"
        style="width: 100%; font-family: monospace"
      ></textarea>
      <div class="page-actions">
        <button class="btn" type="submit" data-testid="send-corrections" :disabled="!worklistCode">
          补发更正
        </button>
      </div>
    </form>

    <!-- 第三步：领用与补转换 -->
    <div class="page-actions" style="margin: 12px 0">
      <button class="btn" data-testid="claim" type="button" :disabled="!worklistCode" @click="claim">
        领用清单范围
      </button>
      <button class="btn primary" data-testid="reconvert" type="button" :disabled="!worklistCode" @click="reconvert">
        启动补转换
      </button>
      <button class="btn ghost" data-testid="refresh" type="button" :disabled="!worklistCode" @click="refreshWorklist">
        刷新清单
      </button>
      <button class="btn ghost" type="button" :disabled="!worklistCode" @click="showConvertedKeys">
        核对转换键
      </button>
      <button class="btn ghost" type="button" :disabled="!worklistCode" @click="showRemaining">
        查看剩余拒收
      </button>
    </div>

    <p class="status-legend">
      当前清单：<strong>{{ worklistCode || '尚未生成' }}</strong>
      <span v-if="lastResult" style="margin-left: 16px">
        补转 {{ lastResult.converted }} 条 ｜ 重复跳过 {{ lastResult.duplicates_skipped }} 条
        ｜ 剩余拒收 {{ lastResult.remaining_rejected }} 条 ｜ 产物新增 {{ lastResult.artifact_written_lines }} 行
      </span>
    </p>

    <h3>待重新映射记录清单</h3>
    <table class="data-table" data-testid="worklist-table">
      <thead>
        <tr>
          <th>记录主键</th><th>拒收原因</th><th>契约编号</th><th>原映射版本</th>
          <th>转换键</th><th>是否补发</th><th>清单状态</th><th>补转版本</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in worklistRows" :key="String(row.id)" :data-status="String(row.清单状态)">
          <td>{{ row.记录主键 }}</td>
          <td>{{ row.拒收原因 }}</td>
          <td>{{ row.契约编号 }}</td>
          <td>{{ row.映射版本 }}</td>
          <td>{{ row.转换键 }}</td>
          <td>{{ row.补发数据 ? '已补发' : '未补发' }}</td>
          <td>{{ row.清单状态 }}</td>
          <td>{{ row.补转版本 || '—' }}</td>
        </tr>
        <tr v-if="!worklistRows.length">
          <td colspan="8" class="empty-state">生成清单后在此查看条目状态</td>
        </tr>
      </tbody>
    </table>

    <div v-if="convertedKeys.length" class="analysis-summary">
      <h3>已补转换键索引（实际转换键与版本）</h3>
      <ul>
        <li v-for="key in convertedKeys" :key="key.conversion_key">
          <code>{{ key.conversion_key }}</code>
        </li>
      </ul>
    </div>

    <div v-if="remainingRows.length" class="analysis-summary">
      <h3>剩余拒收数据（退回源端继续处理）</h3>
      <table class="data-table">
        <thead>
          <tr><th>记录主键</th><th>拒收原因</th><th>契约编号</th><th>映射版本</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in remainingRows" :key="String(row.记录主键)">
            <td>{{ row.记录主键 }}</td>
            <td>{{ row.拒收原因 }}</td>
            <td>{{ row.契约编号 }}</td>
            <td>{{ row.映射版本 }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import {
  buildRemapWorklist,
  claimRemapScope,
  loadConvertedKeys,
  loadRemainingRejections,
  loadWorklist,
  queryRejectionsByReason,
  receiveCorrections,
  runReconversion,
  type MappingDetailRow,
} from '@/api/backend-service'
import type { EntryRow } from '@/data/types'

const reason = ref('数值错误')
const batchCode = ref('')
const correctionText = ref(JSON.stringify([
  { 记录主键: 'PK-R01', values: { amount: '88.50', qty: '3' } },
  { 记录主键: 'PK-R02', values: { amount: '120.00', qty: '6' } },
], null, 2))

const rejections = ref<MappingDetailRow[]>([])
const worklistRows = ref<EntryRow[]>([])
const convertedKeys = ref<{ conversion_key: string; worklist_code: string }[]>([])
const remainingRows = ref<EntryRow[]>([])
const worklistCode = ref('')
const message = ref<{ text: string; error: boolean } | null>(null)
const lastResult = ref<{
  converted: number
  duplicates_skipped: number
  remaining_rejected: number
  artifact_written_lines: number
} | null>(null)

function notify(text: string, error = false) {
  message.value = { text, error }
}

async function searchRejections() {
  try {
    const payload = await queryRejectionsByReason(reason.value, batchCode.value)
    rejections.value = payload.items
    notify(`筛选到 ${payload.total} 条待处置拒收记录`)
  } catch (error) {
    notify(error instanceof Error ? error.message : '查询失败', true)
  }
}

async function buildWorklist() {
  try {
    const payload = await buildRemapWorklist(reason.value, batchCode.value)
    worklistCode.value = payload.worklist_code
    worklistRows.value = payload.items
    notify(`清单 ${payload.worklist_code} 已生成，共 ${payload.matched} 条待重新映射记录`)
  } catch (error) {
    notify(error instanceof Error ? error.message : '清单生成失败', true)
  }
}

async function sendCorrections() {
  if (!worklistCode.value) return
  try {
    const corrections = JSON.parse(correctionText.value) as {
      记录主键: string
      values: Record<string, unknown>
    }[]
    const result = await receiveCorrections(worklistCode.value, corrections)
    notify(`补发 ${result.corrected} 条，仍有 ${result.remaining} 条等待源端修正`)
    await refreshWorklist()
  } catch (error) {
    notify(error instanceof Error ? error.message : '补发失败，请检查 JSON', true)
  }
}

async function claim() {
  if (!worklistCode.value) return
  try {
    const result = await claimRemapScope(worklistCode.value)
    notify(`领用 ${result.claimed} 条；已补转跳过 ${result.skipped_converted.length} 条；`
      + `未补发跳过 ${result.skipped_waiting_correction.length} 条`)
    await refreshWorklist()
  } catch (error) {
    notify(error instanceof Error ? error.message : '领用失败', true)
  }
}

async function reconvert() {
  if (!worklistCode.value) return
  try {
    const result = await runReconversion(worklistCode.value)
    lastResult.value = result
    notify(`补转换完成：${result.converted} 条成功，${result.duplicates_skipped} 条重复跳过，`
      + `${result.remaining_rejected} 条剩余拒收`)
    await refreshWorklist()
  } catch (error) {
    notify(error instanceof Error ? error.message : '补转换失败', true)
  }
}

async function refreshWorklist() {
  if (!worklistCode.value) return
  const payload = await loadWorklist(worklistCode.value)
  worklistRows.value = payload.items
}

async function showConvertedKeys() {
  if (!worklistCode.value) return
  const payload = await loadConvertedKeys(worklistCode.value)
  convertedKeys.value = payload.items
}

async function showRemaining() {
  if (!worklistCode.value) return
  const payload = await loadRemainingRejections(worklistCode.value)
  remainingRows.value = payload.items
}
</script>
