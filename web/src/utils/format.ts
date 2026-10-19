import type { Recording, RecStatus } from '../api/types'
import { t, type TKey } from '../i18n'

/** 文件夹专属色：按名称稳定映射，工作台标签与侧栏图标同色，便于区分（概念 v11） */
const FOLDER_COLORS = ['#2b5cff', '#0f9d6b', '#d97a06', '#e0399b', '#6d4aff', '#38405a']

export function folderColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return FOLDER_COLORS[h % FOLDER_COLORS.length]
}

export function fmtDuration(ms?: number): string {
  if (!ms || ms <= 0) return '00:00'
  const s = Math.round(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

export function fmtBytes(b?: number): string {
  if (!b) return ''
  if (b < 1024 * 1024) return Math.round(b / 1024) + ' KB'
  if (b < 1024 * 1024 * 1024) return (b / 1024 / 1024).toFixed(1) + ' MB'
  return (b / 1024 / 1024 / 1024).toFixed(2) + ' GB'
}

export function fmtTime(dt?: string): string {
  if (!dt) return ''
  // 后端格式 "YYYY-MM-DD HH:MM:SS"
  return dt.slice(5).replace('-', '/')
}

// 状态标签走 i18n（st.* 词条），未知状态回退显示原始值
export function statusLabel(s?: string): string {
  if (!s) return t('st.unknown')
  const key = ('st.' + s) as TKey
  const v = t(key)
  return v !== key ? v : s
}

// 映射概念图状态色：done/partial(run? no, partial=part)/processing=run/queued/failed=fail
export function statusClass(s?: string): string {
  switch (s) {
    case 'done': return 'done'
    case 'partial': return 'part'
    case 'processing': return 'run'
    case 'queued': return 'queued'
    case 'failed': return 'fail'
    default: return 'queued'
  }
}

export function recStatus(r: Recording): RecStatus {
  return (r.job_status || r.status || 'queued') as RecStatus
}

export function recProgress(r: Recording): number {
  const p = r.job_progress != null
    ? Math.round(r.job_progress)
    : (r.status === 'done' || r.status === 'partial' ? 100 : 0)
  return Math.max(0, Math.min(100, p))
}
