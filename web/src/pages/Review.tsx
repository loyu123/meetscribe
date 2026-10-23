import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getReview, getStats, getRecordings, confirmReview } from '../api/recordings'
import type { ReviewSegment, Stats, Recording } from '../api/types'
import { fmtDuration } from '../utils/format'
import { t } from '../i18n'

// P2-4 复核原因选项（与 engine.review_flag 输出一致，后端 LIKE 模糊匹配）
const REASONS = ['', '低置信度', '过短', '重复字/异常标点', '疑似漏字']

export default function Review() {
  const nav = useNavigate()
  const [segs, setSegs] = useState<ReviewSegment[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<Stats | null>(null)
  const [names, setNames] = useState<Record<string, string>>({})
  const [err, setErr] = useState<string | null>(null)
  const [sel, setSel] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  // P2-4 筛选：录音 / 原因 / 置信度上限
  const [fRec, setFRec] = useState('')
  const [fReason, setFReason] = useState('')
  const [fConf, setFConf] = useState('')

  const load = () => {
    getReview({
      recording_id: fRec || undefined,
      reason: fReason || undefined,
      conf_max: fConf ? Number(fConf) : undefined,
    }).then((d) => { setSegs(d.segments); setTotal(d.total) }).catch((e) => setErr(String(e)))
    getStats().then(setStats).catch(() => {})
  }

  useEffect(() => {
    load()
    getRecordings().then((rs: Recording[]) =>
      setNames(Object.fromEntries(rs.map((r) => [r.id, r.filename])))
    ).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fRec, fReason, fConf])

  const confClass = (c?: number | null) => {
    if (c == null) return ''
    if (c < 0.6) return 'low'
    if (c < 0.8) return 'warn'
    return ''
  }
  const confText = (c?: number | null) => (c == null ? '—' : Math.round(c * 100) + '%')

  const toggle = (id: string) =>
    setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  const allOn = segs.length > 0 && segs.every((s) => sel.includes(s.id))

  const doConfirm = async (ids: string[]) => {
    if (!ids.length || busy) return
    setBusy(true)
    try {
      const r = await confirmReview(ids)
      if (r.ok) {
        setSegs((list) => list.filter((s) => !ids.includes(s.id)))
        setSel((s) => s.filter((x) => !ids.includes(x)))
        getStats().then(setStats).catch(() => {})
        // 广播给侧栏等：待复核角标数量立即同步
        window.dispatchEvent(new Event('recordings-changed'))
      } else {
        alert(t('rv.confirmFail', { err: (r as any).error || t('st.unknown') }))
      }
    } catch (e) {
      setErr(t('rv.confirmFail', { err: String(e instanceof Error ? e.message : e) }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="review">
      <h1 className="page-head">{t('rv.title')}</h1>

      {err && <div className="callout warn">{err}</div>}

      <div className="confbar">
        <div>
          <div className="big" style={{ color: stats && (stats.segments.avg_confidence ?? 0) < 0.8 ? 'var(--orange)' : 'var(--green)' }}>
            {stats ? Math.round((stats.segments.avg_confidence ?? 0) * 100) + '%' : '—'}
          </div>
          <div className="lab">{t('rv.avgConf')}</div>
        </div>
        <div>
          <div className="big">{stats ? stats.segments.need_review : '—'}</div>
          <div className="lab">{t('rv.pending')}</div>
        </div>
        <div>
          <div className="big">{stats ? stats.segments.count : '—'}</div>
          <div className="lab">{t('rv.totalSegs')}</div>
        </div>
        <div className="sub">
          {t('rv.today', { n: stats ? stats.jobs_today.count : '—', p: stats ? Math.round(stats.jobs_today.failure_rate * 100) : '—' })}<br />
          {t('rv.queue', { a: stats ? stats.queue.processing : '—', b: stats ? (stats.jobs.failed ?? 0) : '—' })}
        </div>
      </div>

      {/* P2-4 筛选条：录音 / 复核原因 / 置信度上限 */}
      <div className="resbar" style={{ marginBottom: 12 }}>
        <span className="lb">{t('rv.fRec')}</span>
        <select value={fRec} onChange={(e) => { setSel([]); setFRec(e.target.value) }}>
          <option value="">{t('se.all')}</option>
          {Object.entries(names).map(([id, name]) => (
            <option key={id} value={id}>{name}</option>
          ))}
        </select>
        <span className="lb">{t('rv.fReason')}</span>
        <select value={fReason} onChange={(e) => { setSel([]); setFReason(e.target.value) }}>
          {REASONS.map((r) => (
            <option key={r} value={r}>{r ? r : t('se.all')}</option>
          ))}
        </select>
        <span className="lb">{t('rv.fConf')}</span>
        <select value={fConf} onChange={(e) => { setSel([]); setFConf(e.target.value) }}>
          <option value="">{t('se.all')}</option>
          <option value="0.6">&lt; 60%</option>
          <option value="0.8">&lt; 80%</option>
        </select>
        {(fRec || fReason || fConf) && (
          <span className="chip k" style={{ cursor: 'pointer' }}
            onClick={() => { setSel([]); setFRec(''); setFReason(''); setFConf('') }}>{t('se.clearFilter')}</span>
        )}
        <span className="meta">
          {t('rv.showing', { a: segs.length, b: total })}
        </span>
      </div>

      {segs.length > 0 && (
        <div className="rvbar">
          <span className={'cbx' + (allOn ? ' on' : '')} onClick={() => setSel(allOn ? [] : segs.map((s) => s.id))} />
          <span style={{ color: 'var(--ink-500)' }}>{t('home.selectAllN', { n: segs.length })}</span>
          {sel.length > 0 && <span className="pill b">{t('rv.selectedN', { n: sel.length })}</span>}
          <span className="meta" style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--ink-400)' }}>
            {t('rv.hint')}
          </span>
        </div>
      )}

      {segs.map((s) => {
        const selected = sel.includes(s.id)
        return (
          <div key={s.id} className={'rseg' + (selected ? ' sel' : '')} style={{ display: 'flex', gap: 10 }}>
            <span className={'cbx' + (selected ? ' on' : '')} style={{ marginTop: 3 }}
              onClick={() => toggle(s.id)} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="r1">
                <span className="nm" onClick={() => nav('/m/' + s.recording_id + '?tab=transcript')}>
                  {names[s.recording_id] || s.recording_id.slice(0, 8)}
                </span>
                <span className="spk">{t('rv.spkN', { n: s.global_spk ?? s.local_spk ?? '?' })}</span>
                <span>{fmtDuration(s.start_ms)}</span>
                {s.asr_model && <span>· {s.asr_model}</span>}
                <span className={'conf ' + confClass(s.confidence)}>{t('rv.conf', { c: confText(s.confidence) })}</span>
              </div>
              <div className="txt">{s.text}</div>
              {s.review_reason && <span className="reason">{s.review_reason}</span>}
            </div>
            <span className="chip k" style={{ cursor: 'pointer', flexShrink: 0, alignSelf: 'center' }}
              onClick={() => doConfirm([s.id])}>{t('rv.iConfirm')}</span>
          </div>
        )
      })}

      {segs.length === 0 && !err && <div className="empty">{t('rv.empty')}</div>}

      {sel.length > 0 && (
        <div className="batchbar">
          <span className="n">{t('rv.selectedN', { n: sel.length })}</span>
          <div className="b">
            <button onClick={() => setSel([])}>{t('c.cancel')}</button>
            <button className="dg" disabled={busy} onClick={() => doConfirm(sel)}>
              {busy ? t('rv.confirming') : t('rv.confirm')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
