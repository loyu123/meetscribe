import { getJSON } from './client'
import type { Recording, Stats, RecordingDetailResponse, SummaryStatus, Summary, JobDetailResponse, Result, ReviewSegment, SummaryTemplate, TplSection, TplOpts } from './types'

// 纪要模板：列表 / 创建 / 编辑 / 删除
export const getTemplates = () =>
  getJSON<{ templates: SummaryTemplate[] }>('/templates').then((d) => d.templates)

export async function createTemplate(body: { name: string; color?: string; description?: string; sections?: TplSection[]; opts?: TplOpts }): Promise<{ ok: boolean; id?: string; error?: string }> {
  const r = await fetch('/api/v1/templates', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  return (await r.json()) as { ok: boolean; id?: string; error?: string }
}

export async function updateTemplate(id: string, body: { name?: string; color?: string; description?: string; sections?: TplSection[]; opts?: TplOpts }): Promise<{ ok: boolean; error?: string }> {
  const r = await fetch(`/api/v1/templates/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  return (await r.json()) as { ok: boolean; error?: string }
}

export async function deleteTemplate(id: string): Promise<{ ok: boolean; error?: string }> {
  const r = await fetch(`/api/v1/templates/${id}`, { method: 'DELETE' })
  return (await r.json()) as { ok: boolean; error?: string }
}

export const getRecordings = (opts?: { deleted?: boolean }) =>
  getJSON<{ recordings: Recording[] }>(`/recordings${opts?.deleted ? '?deleted=1' : ''}`).then((d) => d.recordings)

// 删除：默认移入回收站（7 天可恢复），forever=true 彻底删除
export async function deleteRecording(id: string, forever = false): Promise<{ ok: boolean }> {
  const r = await fetch(`/api/v1/recordings/${id}${forever ? '?forever=1' : ''}`, { method: 'DELETE' })
  return (await r.json()) as { ok: boolean }
}

export async function restoreRecording(id: string): Promise<{ ok: boolean }> {
  const r = await fetch(`/api/v1/recordings/${id}/restore`, { method: 'POST' })
  return (await r.json()) as { ok: boolean }
}

export async function setRecordingFolder(id: string, folder: string): Promise<{ ok: boolean }> {
  const r = await fetch(`/api/v1/recordings/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder }),
  })
  return (await r.json()) as { ok: boolean }
}

export async function batchDelete(ids: string[], forever = false): Promise<{ deleted: number }> {
  const r = await fetch('/api/v1/recordings/batch-delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, forever }),
  })
  return (await r.json()) as { deleted: number }
}

export async function batchMoveFolder(ids: string[], folder: string): Promise<{ ok: boolean; moved: number }> {
  const r = await fetch('/api/v1/recordings/batch-folder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, folder }),
  })
  return (await r.json()) as { ok: boolean; moved: number }
}

export const getStats = () => getJSON<Stats>('/stats')

// 动态文件夹：列表（含未删除录音数）/ 新建 / 删除（其中录音移至未归类）
export interface FolderItem { name: string; count: number }

export const getFolders = () =>
  getJSON<{ folders: FolderItem[] }>('/folders').then((d) => d.folders)

export async function createFolder(name: string): Promise<{ ok: boolean; name?: string; error?: string }> {
  const r = await fetch('/api/v1/folders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  return (await r.json()) as { ok: boolean; name?: string; error?: string }
}

export async function deleteFolder(name: string): Promise<{ ok: boolean; moved_to_inbox: number }> {
  const r = await fetch(`/api/v1/folders/${encodeURIComponent(name)}`, { method: 'DELETE' })
  return (await r.json()) as { ok: boolean; moved_to_inbox: number }
}

export const getReview = () =>
  getJSON<{ segments: ReviewSegment[] }>('/review').then((d) => d.segments)

// 批量人工复核确认：确认后句子从复核队列消失
export async function confirmReview(ids: (string | number)[]): Promise<{ ok: boolean; confirmed: number }> {
  const r = await fetch('/api/v1/review/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  })
  return (await r.json()) as { ok: boolean; confirmed: number }
}

// 纪要要点按主题智能分组（LLM，按 summary_id 服务端缓存）
export async function groupSummary(summaryId: string, points: unknown[]): Promise<{ groups: { title: string; idx: number[] }[]; error?: string }> {
  const r = await fetch('/api/v1/summaries/group', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ summary_id: summaryId, points }),
  })
  return (await r.json()) as { groups: { title: string; idx: number[] }[]; error?: string }
}

export const getRecording = (id: string, clean = false) =>
  getJSON<RecordingDetailResponse>(`/recordings/${id}${clean ? '?clean=1' : ''}`)

// 人工修正某一句转写原文（同步展示与检索索引）
export async function editTurn(rid: string, startMs: number, text: string): Promise<{ ok: boolean; error?: string }> {
  const r = await fetch(`/api/v1/recordings/${rid}/turns/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ start_ms: startMs, text }),
  })
  return (await r.json()) as { ok: boolean; error?: string }
}

export const getJob = (jid: string) =>
  getJSON<JobDetailResponse>(`/jobs/${jid}`)

export async function postPolish(id: string): Promise<{ ok?: boolean }> {
  const r = await fetch(`/api/v1/recordings/${id}/polish`, { method: 'POST' })
  return (await r.json()) as { ok?: boolean }
}
export const getPolish = (id: string) =>
  getJSON<{ status: string; result?: Result; error?: string }>(`/recordings/${id}/polish`)

export async function retryJob(jid: string): Promise<{ ok: boolean; requeued: number }> {
  const r = await fetch(`/api/v1/jobs/${jid}/retry`, { method: 'POST' })
  return (await r.json()) as { ok: boolean; requeued: number }
}

export const getSummary = (id: string, template: string) =>
  getJSON<SummaryStatus>(`/recordings/${id}/summary?template=${template}`)

export async function postSummary(id: string, template: string, force = true): Promise<{ status: string }> {
  const r = await fetch(`/api/v1/recordings/${id}/summary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template, force }),
  })
  return (await r.json()) as { status: string }
}

export async function editSummary(sid: string, before: string, after: string): Promise<void> {
  await fetch(`/api/v1/summaries/${sid}/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ before, after }),
  })
}

export type { Summary }
