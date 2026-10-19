import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { getJob, retryJob, getRecording } from '../api/recordings'
import type { JobDetailResponse } from '../api/types'
import { fmtDuration, statusLabel, statusClass } from '../utils/format'
import { t, type TKey } from '../i18n'

// 概念图流水线阶段（后端仅暴露整体 stage 文本 + progress，这里用 stage 关键词对齐高亮）
const STEPS: TKey[] = ['job.queue', 'job.decode', 'job.split', 'job.asr', 'job.diarize', 'job.finish']
function stepIndex(stage?: string): number {
  const s = (stage || '').toLowerCase()
  if (s.includes('完成') || s.includes('后处理') || s.includes('标点')) return 5
  if (s.includes('说话人') || s.includes('聚类')) return 4
  if (s.includes('asr') || s.includes('识别') || s.includes('转写')) return 3
  if (s.includes('分段') || s.includes('vad')) return 2
  if (s.includes('解码')) return 1
  return 0
}

export default function JobProgress() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const [data, setData] = useState<JobDetailResponse | null>(null)
  const [filename, setFilename] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const timer = useRef<number | null>(null)

  const load = () => getJob(id).then(setData).catch((e) => setErr(String(e)))
  const poll = () => {
    if (timer.current) window.clearInterval(timer.current)
    let fails = 0
    timer.current = window.setInterval(async () => {
      try {
        const d = await getJob(id)
        fails = 0
        setData(d)
        if (['done', 'partial', 'failed'].includes(d.job.status ?? '') && timer.current) {
          window.clearInterval(timer.current); timer.current = null
        }
      } catch {
        // 后端短暂不可达：连续失败则停止轮询并提示，避免静默卡死
        if (++fails >= 6 && timer.current) {
          window.clearInterval(timer.current); timer.current = null
          setErr(t('job.lostConn'))
        }
      }
    }, 2500)
  }

  useEffect(() => {
    getJob(id).then((d) => {
      setData(d)
      if (d.job.recording_id) {
        getRecording(d.job.recording_id).then((r) => setFilename(r.recording.filename)).catch(() => {})
      }
      if (!['done', 'partial', 'failed'].includes(d.job.status ?? '')) poll()
    }).catch((e) => setErr(String(e)))
    return () => { if (timer.current) window.clearInterval(timer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const onRetry = async () => {
    setRetrying(true)
    await retryJob(id)
    setRetrying(false)
    load(); poll()
  }

  if (err) return <div className="empty">{t('c.loadFailed', { err })}</div>
  if (!data) return <div className="empty">{t('c.loading')}</div>

  const job = data.job
  const chunks = data.chunks
  const cur = stepIndex(job.stage)
  const terminal = ['done', 'partial', 'failed'].includes(job.status ?? '')
  const failed = chunks.filter((c) => c.status === 'failed')
  const pct = Math.round(job.progress ?? 0)

  return (
    <div className="job">
      <div className="detail-head">
        <h1>{filename || job.recording_id}</h1>
        <div className="byline">
          <span className={'st ' + statusClass(job.status)}>{statusLabel(job.status)}</span>
          <span>{job.stage}</span>
          {job.asr_model && <span>· {job.asr_model}</span>}
        </div>
      </div>

      {/* 流水线 */}
      <div className="pipeline">
        {STEPS.map((key, i) => (
          <div key={key} className={'step' + (i < cur ? ' done' : i === cur ? ' cur' : '')}>
            {i > 0 && <span className="bar" />}
            <div className="dot">{i < cur ? '✓' : i + 1}</div>
            <div className="lb">{t(key)}</div>
          </div>
        ))}
      </div>
      <div className={'job-prog' + (job.status === 'partial' ? ' part' : '') + (!terminal && pct === 0 ? ' indet' : '')}>
        <i style={{ width: (pct || 45) + '%' }} />
      </div>
      <div className="meta">{pct > 0 ? t('job.progressN', { p: pct }) : t('job.transcribing')}</div>

      <div className="metarow">
        <div className="m"><b>{job.total_chunks ?? chunks.length}</b><span>{t('job.totalChunks')}</span></div>
        <div className="m"><b>{job.done_chunks ?? chunks.filter((c) => c.status === 'done').length}</b><span>{t('job.doneN')}</span></div>
        <div className="m"><b style={{ color: failed.length ? 'var(--red)' : undefined }}>{job.failed_chunks ?? failed.length}</b><span>{t('job.failedN')}</span></div>
        {job.num_speakers != null && <div className="m"><b>{job.num_speakers}</b><span>{t('job.diarize')}</span></div>}
      </div>

      {!terminal && (
        <div className="callout warn" style={{ marginTop: 4 }}>{t('job.autoRefresh')}</div>
      )}
      {job.status === 'partial' && (
        <div className="callout warn">{t('job.partialWarn', { n: failed.length })}</div>
      )}
      {job.status === 'failed' && (
        <div className="callout warn">{t('job.failedMsg', { err: job.error ? '：' + job.error : '' })}</div>
      )}

      {/* 分片明细 */}
      <table className="ctable">
        <thead>
          <tr><th>{t('job.chunkCol')}</th><th>{t('job.timeCol')}</th><th>{t('job.statusCol')}</th><th>{t('job.attemptsCol')}</th><th>{t('job.errCol')}</th></tr>
        </thead>
        <tbody>
          {chunks.map((c) => (
            <tr key={c.idx} className={c.status === 'failed' ? 'bad' : ''}>
              <td className="ci">#{c.idx + 1}</td>
              <td className="ci">{c.start_ms != null ? fmtDuration(c.start_ms) + ' – ' + fmtDuration(c.end_ms) : '—'}</td>
              <td><span className={'st ' + (c.status === 'done' ? 'done' : c.status === 'failed' ? 'fail' : c.status === 'processing' ? 'run' : 'queued')}>{statusLabel(c.status)}</span></td>
              <td className="ci">{c.attempts ?? 0}</td>
              <td className={c.error ? 'err' : ''}>
                {c.error ? c.error : c.status === 'failed' ? (
                  <span className="retry" onClick={onRetry}>{retrying ? t('job.rerunning') : t('job.retryOne')}</span>
                ) : '—'}
              </td>
            </tr>
          ))}
          {chunks.length === 0 && <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--ink-400)' }}>{t('job.noChunks')}</td></tr>}
        </tbody>
      </table>

      <div style={{ marginTop: 18 }}>
        {terminal && job.recording_id && (
          <Link className="btn-primary" to={'/m/' + job.recording_id}>{t('job.viewDetail')}</Link>
        )}
        {(job.status === 'partial' || job.status === 'failed') && failed.length > 0 && (
          <button className="btn-line" onClick={onRetry} disabled={retrying}>{retrying ? t('job.rerunning') : t('job.retryFailed')}</button>
        )}
        <button className="btn-line" onClick={() => nav('/')}>{t('job.backHome')}</button>
      </div>
    </div>
  )
}
