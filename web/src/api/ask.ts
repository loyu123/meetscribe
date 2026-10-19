import { postJSON } from './client'

export interface AskMsg {
  role: 'user' | 'assistant'
  content: string
}
export interface AskResponse {
  answer: string
  recordings: string[]
  model: string
}

export const askApi = (question: string, recordingId?: string, history: AskMsg[] = []) =>
  postJSON<AskResponse>('/ask', {
    question,
    recording_id: recordingId || undefined,
    history: history.map((m) => ({ role: m.role, content: m.content })),
  })
