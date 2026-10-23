import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { getRecordings } from '../api/recordings'
import type { Recording } from '../api/types'
import { fmtTime, fmtDuration, recStatus, statusLabel, statusClass, folderColor } from '../utils/format'
import TemplateManager from '../components/TemplateManager'
import { t, type TKey } from '../i18n'

const CRUMB: [RegExp, TKey][] = [
  [/^\/$/, 'crumb.workbench'],
  [/^\/new/, 'crumb.newTask'],
  [/^\/job\//, 'crumb.job'],
  [/^\/m\/[^/]+\/transcript$/, 'crumb.transcript'],
  [/^\/m\//, 'crumb.detail'],
  [/^\/search/, 'crumb.search'],
  [/^\/review/, 'crumb.review'],
]

export default function Topbar({ onBurger }: { onBurger?: () => void }) {
  const nav = useNavigate()
  const loc = useLocation()
  const [q, setQ] = useState('')
  const [tplOpen, setTplOpen] = useState(false)
  const [recs, setRecs] = useState<Recording[]>([])
  const [hi, setHi] = useState(0)
  const boxRef = useRef<HTMLDivElement>(null)

  const batch = new URLSearchParams(loc.search).get('batch') === '1'
  const onHome = loc.pathname === '/'
  const label = t(CRUMB.find(([re]) => re.test(loc.pathname))?.[1] ?? 'crumb.workbench')

  // 录音列表缓存：用于文件名即时检索（recordings-changed 时刷新）
  useEffect(() => {
    const load = () => getRecordings().then(setRecs).catch(() => {})
    load()
    window.addEventListener('recordings-changed', load)
    return () => window.removeEventListener('recordings-changed', load)
  }, [])

  const kw = q.trim().toLowerCase()
  const matches = useMemo(() => {
    if (!kw) return []
    return recs
      .filter((r) => !r.deleted_at && r.filename.toLowerCase().includes(kw))
      .slice(0, 8)
  }, [kw, recs])
  const open = kw.length > 0
  useEffect(() => { setHi(0) }, [kw])

  /** 已完成进会议详情，转写中/排队进任务进度页 */
  const openRec = (r: Recording) => {
    const st = r.status ?? ''
    const active = st === 'processing' || st === 'queued'
    if (active && r.job_id) nav('/job/' + r.job_id)
    else nav('/m/' + r.id)
    setQ(''); setHi(0)
  }

  const go = () => {
    const target = matches[hi] ?? matches[0]
    if (target) openRec(target)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || !matches.length) {
      if (e.key === 'Enter') go()
      return
    }
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => (h + 1) % matches.length) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => (h - 1 + matches.length) % matches.length) }
    else if (e.key === 'Enter') { e.preventDefault(); openRec(matches[hi] ?? matches[0]) }
    else if (e.key === 'Escape') { setQ('') }
  }

  /** 文件名匹配段高亮 */
  const hlName = (name: string) => {
    const i = name.toLowerCase().indexOf(kw)
    if (i === -1 || !kw) return name
    return (<>{name.slice(0, i)}<b>{name.slice(i, i + kw.length)}</b>{name.slice(i + kw.length)}</>)
  }

  const toggleBatch = () => {
    if (!onHome) { nav('/?batch=1'); return }
    const n = new URLSearchParams(loc.search)
    if (batch) n.delete('batch'); else n.set('batch', '1')
    nav({ pathname: '/', search: n.toString() })
  }

  return (
    <header className="topbar" ref={boxRef}>
      {/* D3：移动端抽屉开关（桌面端 CSS 隐藏） */}
      <span className="burger" onClick={onBurger}>☰</span>
      <span className="crumb">{t('top.crumbPrefix')} / <b>{label}</b></span>
      <div className="search" style={{ position: 'relative' }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={t('top.searchPh')}
        />
        <span className="go" onClick={go}>{t('top.search')}</span>
        {open && (
          <div className="tsug">
            {matches.length === 0 ? (
              <div className="tempty">{t('top.noMatch', { q: q.trim() })}</div>
            ) : matches.map((r, i) => {
              const fc = r.folder ? folderColor(r.folder) : null
              const st = recStatus(r)
              const active = st === 'processing' || st === 'queued'
              return (
                <div key={r.id} className={'si' + (i === hi ? ' on' : '')}
                  onMouseEnter={() => setHi(i)}
                  onMouseDown={(e) => { e.preventDefault(); openRec(r) }}>
                  <span className="fi">{r.filename.slice(r.filename.lastIndexOf('.') + 1).toUpperCase().slice(0, 4)}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="nm">{hlName(r.filename)}</div>
                    <div className="mt">
                      {r.folder && fc && <><span className="dot" style={{ background: fc }} />{r.folder} · </>}
                      {fmtTime(r.created_at)}
                      {r.duration_ms ? <> · {fmtDuration(r.duration_ms)}</> : null}
                    </div>
                  </div>
                  <span className={'tst ' + statusClass(st)}>{statusLabel(st)}</span>
                  {active && <span className="go-hint">{t('top.progressHint')}</span>}
                </div>
              )
            })}
            {matches.length > 0 && (
              <div className="tft">
                <span>{t('top.matchCount', { n: recs.filter((r) => !r.deleted_at && r.filename.toLowerCase().includes(kw)).length })}</span>
                <span><kbd>↑</kbd><kbd>↓</kbd> {t('top.tipSel')} · <kbd>Enter</kbd> {t('top.tipOpen')} · <kbd>Esc</kbd> {t('top.tipClose')}</span>
              </div>
            )}
          </div>
        )}
      </div>
      <span className="spacer" />
      <span className="tbtn" title={t('top.templates')} onClick={() => setTplOpen(true)}>
        {t('top.templates')}
      </span>
      <span className={'tbtn' + (batch && onHome ? ' on' : '')} onClick={toggleBatch} title={t('top.batch')}>
        {batch && onHome ? t('top.batchExit') : t('top.batch')}
      </span>
      <span className="tbtn primary" onClick={() => nav('/new')}>
        <span className="rec-ico" /> {t('top.newTask')}
      </span>
      {tplOpen && <TemplateManager onClose={() => setTplOpen(false)} />}
    </header>
  )
}
