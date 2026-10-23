import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { searchApi, reindexAll, reindexStatus, type SearchResponse, type SearchFilters } from '../api/search'
import { fmtDuration } from '../utils/format'
import { t, type TKey } from '../i18n'

const SUGGS: TKey[] = ['se.sug1', 'se.sug2', 'se.sug3', 'se.sug4', 'se.sug5']

export default function Search() {
  const nav = useNavigate()
  const [sp] = useSearchParams()
  const urlQ = sp.get('q') ?? ''
  const [q, setQ] = useState(urlQ)
  const [submitted, setSubmitted] = useState(false)
  const [filters, setFilters] = useState<SearchFilters>({})
  const [page, setPage] = useState(1)
  const [data, setData] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [indexing, setIndexing] = useState(false)
  const [reindexMsg, setReindexMsg] = useState<string | null>(null)
  const runSeq = useRef(0) // 响应乱序守卫

  const run = async (query: string = q, p = 1) => {
    const text = (query ?? '').trim()
    if (!text) { setErr(t('se.needQuery')); return }
    setLoading(true); setErr(null)
    const seq = ++runSeq.current // 响应乱序守卫：慢的旧响应不得覆盖新结果
    try {
      const d = await searchApi(text, filters, p, 10)
      if (seq !== runSeq.current) return
      setData(d); setPage(p); setSubmitted(true)
    } catch (e) {
      if (seq === runSeq.current) setErr(String(e instanceof Error ? e.message : e))
    } finally {
      if (seq === runSeq.current) setLoading(false)
    }
  }

  // 顶栏搜索带 ?q= 进来时自动检索
  useEffect(() => {
    if (urlQ) { setQ(urlQ); run(urlQ, 1) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQ])

  // P0-2：重建为后台任务，提交后轮询进度直至完成再刷新结果
  const doIndex = async () => {
    setIndexing(true); setReindexMsg(null)
    try {
      await reindexAll()
      for (;;) {
        await new Promise((r) => setTimeout(r, 1500))
        const s = (await reindexStatus()).status
        if (!s.running) {
          setReindexMsg(t('se.reindexDone', { ok: s.done, skip: s.failed }))
          break
        }
      }
    } catch (e) {
      setErr(t('se.reindexFail', { err: String(e instanceof Error ? e.message : e) }))
    } finally {
      setIndexing(false); if (q.trim()) run(q, page)
    }
  }

  const toggleSpeaker = (spk: string) =>
    setFilters((f) => ({ ...f, speaker: f.speaker === spk ? undefined : spk }))

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1
  const unindexed = data?.unindexed ?? 0
  const needsIndex = !!data && (data.facets.indexed_total === 0 || unindexed > 0)

  // ===== 初始态：居中大搜索框 =====
  if (!submitted) {
    return (
      <div className="spage">
        <div className="hero">
          <div className="hlogo">✦</div>
          <h2>{t('se.heroTitle')}</h2>
          <div className="hs">{t('se.heroSub')}</div>
          <div className="bigsearch">
            <input
              autoFocus
              placeholder={t('se.heroPh')}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && run()}
            />
            <button className="go" onClick={() => run()} disabled={loading}>{loading ? t('se.searching') : t('se.btn')}</button>
          </div>
          <div className="chips">
            {SUGGS.map((k) => {
              const s = t(k)
              return <span key={k} onClick={() => { setQ(s); run(s) }}>{s}</span>
            })}
          </div>
          <div className="tip">{t('se.tip')}</div>
          {err && <div className="callout warn" style={{ marginTop: 16, maxWidth: 520 }}>{err}</div>}
        </div>
      </div>
    )
  }

  // ===== 结果态 =====
  return (
    <div className="spage">
      <h1 className="page-head">{t('se.titleGlobal')}</h1>

      <div className="searchbar">
        <input placeholder={t('se.ph2')}
          value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run()} />
        <button className="go" onClick={() => run()} disabled={loading}>{loading ? t('se.searching') : t('se.btn')}</button>
      </div>

      {/* 筛选一行：条件 + 命中数 */}
      <div className="resbar">
        <span className="lb">{t('se.speaker')}</span>
        <select value={filters.speaker ?? ''} onChange={(e) => setFilters({ ...filters, speaker: e.target.value || undefined })}>
          <option value="">{t('se.all')}</option>
          {(data?.facets.speakers ?? []).map((s) => (
            <option key={s.speaker} value={s.speaker}>{s.speaker}（{s.count}）</option>
          ))}
        </select>
        <span className="lb">{t('se.folder')}</span>
        <select
          value={filters.folder === undefined ? '' : filters.folder === '' ? '__none__' : filters.folder}
          onChange={(e) => {
            const v = e.target.value
            setFilters((f) => ({ ...f, folder: v === '' ? undefined : v === '__none__' ? '' : v }))
          }}>
          <option value="">{t('se.allFolders')}</option>
          {(data?.facets.folders ?? []).filter((x) => x.folder !== '').map((x) => (
            <option key={x.folder} value={x.folder}>{x.folder}（{x.count}）</option>
          ))}
          {(data?.facets.folders ?? []).some((x) => x.folder === '') && (
            <option value="__none__">{t('se.unfiled')}（{(data?.facets.folders ?? []).find((x) => x.folder === '')?.count ?? 0}）</option>
          )}
        </select>
        <span className="lb">{t('se.date')}</span>
        <input type="date" value={filters.date_from ?? ''} onChange={(e) => setFilters({ ...filters, date_from: e.target.value || undefined })} />
        <span className="lb">{t('se.to')}</span>
        <input type="date" value={filters.date_to ?? ''} onChange={(e) => setFilters({ ...filters, date_to: e.target.value || undefined })} />
        {(filters.speaker || filters.date_from || filters.date_to) && (
          <span className="chip k" style={{ cursor: 'pointer' }} onClick={() => setFilters({})}>{t('se.clearFilter')}</span>
        )}
        <span className="meta">
          {t('se.hit', { n: data?.total ?? '—' })} · {t('se.indexed', { a: Array.isArray(data?.indexed_recordings) ? data.indexed_recordings.length : '—', b: data?.facets.indexed_total ?? '—' })}
        </span>
      </div>

      {err && <div className="callout warn">{err}</div>}

      {needsIndex && (
        <div className="callout warn">
          {data?.facets.indexed_total === 0 ? t('se.noIndex') : t('se.unindexed', { n: unindexed })}
          <button className="btn-line" style={{ marginLeft: 10 }} disabled={indexing} onClick={doIndex}>
            {indexing ? t('se.indexing') : t('se.indexAll')}
          </button>
          {reindexMsg && <span style={{ marginLeft: 10 }}>{reindexMsg}</span>}
        </div>
      )}

      {data && (
        <>
          <div className="facet">
            {data.facets.speakers.slice(0, 12).map((s) => (
              <span key={s.speaker} className={'chip' + (filters.speaker === s.speaker ? ' on' : '')} onClick={() => toggleSpeaker(s.speaker)}>
                {s.speaker}
              </span>
            ))}
          </div>

          {data.results.map((h, i) => (
            <div key={i} className="sresult" onClick={() => nav('/m/' + h.recording_id + '?tab=transcript')}>
              <div className="r1">
                <span className="nm">{h.filename}</span>
                <span className="spk">{h.speaker}</span>
                <span className="dt">{h.date}</span>
                <span className="score">{t('se.relevance', { p: Math.round(h.score * 100) })}</span>
              </div>
              <div className="snip" dangerouslySetInnerHTML={{ __html: h.snippet }} />
              <div className="sres-ft">
                <span className="jump">▶ {fmtDuration(h.start_ms)} {t('se.jumpTo')}</span>
                <span>{t('se.clickHint')}</span>
              </div>
            </div>
          ))}

          {data.results.length === 0 && (
            <div className="empty">
              {t('se.empty')}
              {(filters.speaker || filters.date_from || filters.date_to || filters.folder !== undefined) && (
                <div style={{ marginTop: 8 }}>
                  <span className="chip k" style={{ cursor: 'pointer' }} onClick={() => setFilters({})}>{t('se.clearFilter')}</span>
                </div>
              )}
              <div className="tip" style={{ marginTop: 8 }}>
                {unindexed > 0 ? t('se.emptyUnindexed', { n: unindexed }) : t('se.emptyHint')}
              </div>
            </div>
          )}

          {totalPages > 1 && (
            <div className="pager">
              <button className="pb" disabled={page <= 1} onClick={() => run(q, page - 1)}>{t('se.prev')}</button>
              <span>{t('se.pageN', { a: page, b: totalPages })}</span>
              <button className="pb" disabled={page >= totalPages} onClick={() => run(q, page + 1)}>{t('se.next')}</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
