import { postJSON } from './client'

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
  indexed_total: number
}
export interface SearchResponse {
  results: SearchHit[]
  total: number
  page: number
  page_size: number
  facets: SearchFacets
  indexed_recordings: string[] // 已建索引的录音 id 列表（UI 显示其数量）
}

export interface SearchFilters {
  date_from?: string
  date_to?: string
  speaker?: string
  recording_id?: string
}

export const searchApi = (q: string, filters: SearchFilters = {}, page = 1, size = 10) =>
  postJSON<SearchResponse>('/search', { query: q, ...filters, page, page_size: size })

export const reindexAll = () =>
  postJSON<{ ok: boolean; indexed_recordings: number; skipped: number }>('/search/reindex', {})

export const indexRecording = (rid: string) =>
  postJSON<{ ok: boolean; indexed: number }>(`/recordings/${rid}/index`, {})
