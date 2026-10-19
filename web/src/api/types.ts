export type RecStatus = 'queued' | 'processing' | 'done' | 'partial' | 'failed' | string

export interface Recording {
  id: string
  filename: string
  ext?: string
  bytes?: number
  duration_ms?: number
  num_speakers?: number | null
  status?: RecStatus
  error?: string | null
  created_at?: string
  tenant_id?: string
  deleted_at?: number | null
  folder?: string
  job_id?: string
  job_status?: RecStatus
  job_progress?: number
  media_url?: string
}

export interface Stats {
  generated_at: string
  recordings: Record<string, number>
  audio_duration_ms_total: number
  jobs: Record<string, number>
  queue: { queued: number; processing: number }
  chunks: Record<string, number>
  segments: { count: number; avg_confidence: number | null; need_review: number }
  jobs_today: { count: number; failed: number; failure_rate: number }
}

export interface Speaker { spk: string | number; label: string }
export interface Turn {
  start?: string
  end?: string
  start_ms?: number
  end_ms?: number
  spk: string | number
  text: string
}
export interface ResultStats {
  sentences?: number
  turns?: number
  chars?: number
  chunks?: number
  failed_chunks?: number
  review_count?: number
}
export interface Result {
  duration_ms?: number
  duration?: string
  num_speakers?: number
  speakers: Speaker[]
  turns?: Turn[]
  segments?: unknown[]
  review?: unknown[]
  text?: string
  stats?: ResultStats
}
export interface Job {
  id: string
  recording_id: string
  status?: string
  stage?: string
  progress?: number
  total_chunks?: number
  done_chunks?: number
  failed_chunks?: number
  num_speakers?: number
  asr_model?: string
  denoise?: number
  error?: string | null
  created_at?: string
  updated_at?: string
}

/** 纪要模板：内置（meeting/memo）+ 自定义（自定义章节与提取指导语） */
export interface TplSection { title: string; hint?: string }
export interface TplOpts { timestamps?: number; todos?: number; formal?: number }
export interface SummaryTemplate {
  id: string
  name: string
  color: string
  description: string
  sections: TplSection[]
  opts: TplOpts
  builtin: boolean
  created_at?: string
}
export interface RecordingDetail extends Recording {
  duration_ms?: number
  num_speakers?: number
  media_url?: string
}
export interface RecordingDetailResponse {
  recording: RecordingDetail
  job: Job | null
  result: Result | null
}

export interface SummaryPoint { content: string; speaker?: string; timestamp?: string }
export interface SummaryTask { task: string; owner?: string; deadline?: string }
export interface SummaryRisk { content: string; level?: string }
export interface SummaryContentMeeting {
  title?: string
  attendees?: string[]
  one_line?: string
  points?: SummaryPoint[]
  action_items?: SummaryTask[]
  risks?: SummaryRisk[]
}
export interface SummaryContentMemo {
  owner?: string
  one_line?: string
  points?: SummaryPoint[]
  todos?: SummaryTask[]
}
export interface Summary {
  id: string
  recording_id: string
  template: string
  model?: string
  version?: string
  stale?: number
  created_at?: string
  content: SummaryContentMeeting | SummaryContentMemo
}
export type SummaryStatus =
  | { status: 'not_started' }
  | { status: 'processing' }
  | { status: 'failed'; error?: string }
  | (Summary & { status: 'done' })

export interface Chunk {
  idx: number
  start_ms?: number
  end_ms?: number
  status: string
  attempts?: number
  error?: string | null
}
export interface JobDetailResponse {
  job: Job
  chunks: Chunk[]
}

export interface ReviewSegment {
  id: string
  job_id?: string
  recording_id: string
  start_ms?: number
  end_ms?: number
  text?: string
  confidence?: number | null
  need_review?: number
  review_reason?: string | null
  asr_model?: string
  global_spk?: number | null
  local_spk?: number | null
}
