import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

// -- 待重新映射补转换工作台 --

export type MappingDetailRow = {
  拒收编号: string
  批次编号: string
  记录主键: string
  拒收环节: string
  拒收原因: string
  回执编号: string
  契约编号: string
  源字段: string
  目标字段: string
  数据类型: string
  转换规则: string
  映射版本: string
}

export async function queryRejectionsByReason(
  reason: string,
  batchCode = '',
): Promise<{ reason: string; total: number; items: MappingDetailRow[] }> {
  const query = new URLSearchParams({ reason, batch_code: batchCode }).toString()
  const response = await request(`/api/reject_record/rejections/by-reason?${query}`)
  if (!response.ok) throw new Error('拒收回执筛选失败')
  return await response.json()
}

export async function buildRemapWorklist(
  reason: string,
  batchCode = '',
): Promise<{ worklist_code: string; reason: string; matched: number; items: EntryRow[] }> {
  const response = await request('/api/reject_record/remap-worklist', {
    method: 'POST',
    body: JSON.stringify({ reason, batch_code: batchCode }),
  })
  if (!response.ok) throw new Error('待重新映射清单生成失败')
  return await response.json()
}

export async function receiveCorrections(
  worklistCode: string,
  corrections: { 记录主键: string; values: Record<string, unknown> }[],
): Promise<{ corrected: number; remaining: number; corrected_keys: string[]; remaining_keys: string[] }> {
  const response = await request('/api/remap_worklist/corrections', {
    method: 'POST',
    body: JSON.stringify({ worklist_code: worklistCode, corrections }),
  })
  if (!response.ok) throw new Error('源端补发更正失败')
  return await response.json()
}

export async function claimRemapScope(
  worklistCode: string,
): Promise<{ claimed: number; skipped_converted: string[]; skipped_waiting_correction: string[] }> {
  const response = await request('/api/remap_worklist/claim', {
    method: 'POST',
    body: JSON.stringify({ worklist_code: worklistCode }),
  })
  if (!response.ok) throw new Error('领用失败')
  return await response.json()
}

export async function runReconversion(
  worklistCode: string,
): Promise<{
  converted: number
  duplicates_skipped: number
  remaining_rejected: number
  artifact_written_lines: number
  converted_keys: string[]
  remaining_items: EntryRow[]
}> {
  const response = await request('/api/remap_worklist/reconvert', {
    method: 'POST',
    body: JSON.stringify({ worklist_code: worklistCode }),
  })
  if (!response.ok) throw new Error('补转换执行失败')
  return await response.json()
}

export async function loadWorklist(
  worklistCode: string,
): Promise<{ total: number; items: EntryRow[] }> {
  const query = new URLSearchParams({ worklist_code: worklistCode }).toString()
  const response = await request(`/api/remap_worklist?${query}`)
  if (!response.ok) throw new Error('清单读取失败')
  return await response.json()
}

export async function loadConvertedKeys(
  worklistCode: string,
): Promise<{ total: number; items: { conversion_key: string; worklist_code: string }[] }> {
  const query = new URLSearchParams({ worklist_code: worklistCode }).toString()
  const response = await request(`/api/remap_worklist/converted-keys?${query}`)
  if (!response.ok) throw new Error('转换键索引读取失败')
  return await response.json()
}

export async function loadRemainingRejections(
  worklistCode: string,
): Promise<{ remaining: number; items: EntryRow[] }> {
  const query = new URLSearchParams({ worklist_code: worklistCode }).toString()
  const response = await request(`/api/remap_worklist/remaining?${query}`)
  if (!response.ok) throw new Error('剩余拒收数据读取失败')
  return await response.json()
}
