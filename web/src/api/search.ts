import { getJSON, postJSON } from './client'

export interface SearchHit {
  recording_id: string
  filename: string
  speaker: string
  date: string
  start_ms: number
  end_ms: number
  snippet: string
  score: number
}
export interface SearchFacets {
  speakers: { speaker: string; count: number }[]
  recordings: { id: string; filename: string }[]
  folders?: { folder: string; count: number }[] // P1-4 文件夹 facet（'' = 未归档）
  indexed_total: number
}
export interface SearchMeta {
  tokenize_version: number // 当前程序的分词口径版本
  index_tokenize_version: number | null // 现有索引的分词口径版本（未知为 null）
  needs_reindex: boolean // 索引版本落后 → 建议重建
  indexed_at: string | null
}
export interface SearchResponse {
  results: SearchHit[]
  total: number
  page: number
  page_size: number
  facets: SearchFacets
  indexed_recordings: string[] // 已建索引的录音 id 列表（UI 显示其数量）
  unindexed?: number // 尚未完成索引的已完成录音数（P0-2 异步索引）
  meta?: SearchMeta // U2：分词版本一致性信息
}

export interface ReindexStatus {
  running: boolean
  done: number
  failed: number
  total: number
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface SearchFilters {
  date_from?: string
  date_to?: string
  speaker?: string
  recording_id?: string
  folder?: string // P1-4 文件夹过滤（'' = 未归档）
}

export const searchApi = (q: string, filters: SearchFilters = {}, page = 1, size = 10) =>
  postJSON<SearchResponse>('/search', { query: q, ...filters, page, page_size: size })

export const reindexAll = () =>
  postJSON<{ ok: boolean; started: boolean; status: ReindexStatus }>('/search/reindex', {})

export const reindexStatus = () =>
  getJSON<{ status: ReindexStatus }>('/search/reindex/status')

export const indexRecording = (rid: string) =>
  postJSON<{ ok: boolean; indexed: number }>(`/recordings/${rid}/index`, {})
