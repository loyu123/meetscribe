import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  getRecordings, getStats, deleteRecording, restoreRecording,
  batchDelete, batchMoveFolder, getFolders,
} from '../api/recordings'
import type { Recording, Stats } from '../api/types'
import type { FolderItem } from '../api/recordings'
import { fmtDuration, fmtBytes, fmtTime, statusLabel, statusClass, recStatus, recProgress, folderColor } from '../utils/format'
import { t } from '../i18n'

// 删除/恢复/移动后广播，侧栏计数即时刷新
const notify = () => window.dispatchEvent(new Event('recordings-changed'))

const TRASH_DAYS = 7

export default function Home() {
  const [sp, setSp] = useSearchParams()
  const folder = sp.get('folder')
  const trash = sp.get('trash') === '1'
  const batch = sp.get('batch') === '1'

  const [recs, setRecs] = useState<Recording[] | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [folders, setFolders] = useState<FolderItem[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [sel, setSel] = useState<string[]>([])
  const [confirm, setConfirm] = useState<{ ids: string[]; forever: boolean } | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => {
    setErr(null)
    getRecordings({ deleted: trash })
      .then(setRecs)
      .catch((e) => setErr(String(e instanceof Error ? e.message : e)))
    if (!trash) {
      getStats().then(setStats).catch(() => {})
      getFolders().then(setFolders).catch(() => {})
    }
  }

  useEffect(() => { setSel([]); load() }, [trash])

  const shown = useMemo(
    () => (recs ?? []).filter((r) => !folder || (r.folder ?? '') === folder),
    [recs, folder],
  )

  const title = trash ? t('home.trashTitle') : folder ? t('home.folderTitle', { n: folder }) : t('nav.workbench')

  const remainDays = (r: Recording) => {
    if (!r.deleted_at) return TRASH_DAYS
    const used = Math.floor((Date.now() / 1000 - r.deleted_at) / 86400)
    return Math.max(0, TRASH_DAYS - used)
  }

  const doConfirm = async () => {
    if (!confirm || busy) return
    setBusy(true)
    try {
      if (confirm.ids.length === 1) await deleteRecording(confirm.ids[0], confirm.forever)
      else await batchDelete(confirm.ids, confirm.forever)
      setConfirm(null); setSel([]); notify(); load()
    } catch (e) {
      setErr(t('home.delFailed', { err: String(e instanceof Error ? e.message : e) }))
    } finally {
      setBusy(false)
    }
  }

  const doRestore = async (rid: string) => {
    await restoreRecording(rid); notify(); load()
  }

  const doMove = async (f: string) => {
    if (!sel.length) return
    setBusy(true)
    try {
      await batchMoveFolder(sel, f)
      setSel([]); notify(); load()
      if (f && folder && f !== folder) setSp({}) // 移出当前文件夹后回到全部
    } finally {
      setBusy(false)
    }
  }

  const toggle = (rid: string) =>
    setSel((s) => (s.includes(rid) ? s.filter((x) => x !== rid) : [...s, rid]))

  const allOn = shown.length > 0 && shown.every((r) => sel.includes(r.id))
  const toggleAll = () => setSel(allOn ? [] : shown.map((r) => r.id))

  const exitBatch = () => {
    const n = new URLSearchParams(sp)
    n.delete('batch')
    setSp(n)
    setSel([])
  }

  const name = (rid: string) => recs?.find((r) => r.id === rid)?.filename ?? t('home.thisRec')

  return (
    <div>
      <h1 className="page-head">{title}{batch && !trash ? <span className="st part" style={{ marginLeft: 10 }}>{t('top.batch')}</span> : null}</h1>

      {err && (
        <div className="callout warn" style={{ background: 'var(--red-50)', borderColor: '#f6c9c5', color: '#b02a22' }}>
          {t('home.errBackend', { err })}
        </div>
      )}

      {!trash && (
        <div className="stats">
          <div className="stat"><b>{stats ? Object.values(stats.recordings).reduce((a, b) => a + b, 0) : '—'}</b><span>{t('home.statTotal')}</span></div>
          <div className="stat warn"><b>{stats ? stats.queue.processing + stats.queue.queued : '—'}</b><span>{t('home.statQueue')}</span></div>
          <div className="stat warn"><b>{stats?.recordings['partial'] ?? 0}</b><span>{t('st.partial')}</span></div>
          <div className="stat"><b>{stats?.segments.avg_confidence != null ? (stats.segments.avg_confidence * 100).toFixed(1) + '%' : '—'}</b><span>{t('home.statConf')}</span></div>
          <div className="stat warn"><b>{stats?.segments.need_review ?? '—'}</b><span>{t('rv.pending')}</span></div>
        </div>
      )}

      {batch && !trash && shown.length > 0 && (
        <div className="selall">
          <span className={'cbx' + (allOn ? ' on' : '')} onClick={toggleAll} />
          <span style={{ fontSize: 12, color: 'var(--ink-500)' }}>{t('home.selectAllN', { n: shown.length })}</span>
        </div>
      )}

      {trash && <div className="callout" style={{ marginBottom: 12 }}>{t('home.trashNote', { n: TRASH_DAYS })}</div>}

      {!recs && !err && <div className="rc">{t('c.loading')}</div>}

      {recs && shown.length === 0 && (
        <div className="empty">{trash ? t('home.trashEmpty') : folder ? t('home.emptyFolder') : t('home.empty')}</div>
      )}

      {shown.map((r) => {
        const st = recStatus(r)
        const pct = recProgress(r)
        const active = st === 'processing' || st === 'queued'
        const selected = sel.includes(r.id)
        const fc = r.folder ? folderColor(r.folder) : null
        const inner = (
          <>
            {batch && (
              <span className={'cbx' + (selected ? ' on' : '')} style={{ marginRight: 10, marginTop: 2 }} />
            )}
            <div style={{ flex: 1, minWidth: 0 }}>
              <h3>
                {r.filename} <span className={'st ' + statusClass(st)}>{statusLabel(st)}</span>
                {st === 'partial' && <span className="st part" style={{ marginLeft: 6 }}>{pct}%</span>}
                {r.folder && fc && (
                  <span className="st" style={{ marginLeft: 6, background: fc + '14', color: fc, borderColor: fc + '2e' }}>
                    ● {r.folder}
                  </span>
                )}
              </h3>
              <div className="meta">
                {fmtTime(r.created_at)} · {fmtDuration(r.duration_ms)} · {r.num_speakers ? t('home.spkN', { n: r.num_speakers }) : t('home.spkDetecting')} · {fmtBytes(r.bytes)}
              </div>
              {active && <div className="mbar"><i style={{ width: pct + '%' }} /></div>}
            </div>
          </>
        )

        if (trash) {
          return (
            <div key={r.id} className={'rc' + (selected ? ' sel' : '')} style={{ display: 'flex' }}>
              {inner}
              <div className="rc-acts" style={{ flexDirection: 'column', alignItems: 'stretch', justifyContent: 'center' }}>
                <span className="trash-days">{t('home.daysLeft', { n: remainDays(r) })}</span>
                <div style={{ display: 'flex', gap: 7, marginTop: 6 }}>
                  <button onClick={() => doRestore(r.id)}>{t('home.restore')}</button>
                  <button className="dg" onClick={() => setConfirm({ ids: [r.id], forever: true })}>{t('home.deleteForever')}</button>
                </div>
              </div>
            </div>
          )
        }

        if (batch) {
          return (
            <div key={r.id} className={'rc' + (selected ? ' sel' : '')} style={{ display: 'flex', cursor: 'pointer' }} onClick={() => toggle(r.id)}>
              {inner}
            </div>
          )
        }

        return (
          <div key={r.id} className="rc-wrap">
            {/* 进行中跳任务进度页，完成后跳会议详情 */}
            <Link to={active && r.job_id ? '/job/' + r.job_id : '/m/' + r.id} className="rc" style={{ textDecoration: 'none', color: 'inherit', display: 'block' }}>
              {inner}
            </Link>
            {!active && (
              <button className="rc-del" title={t('home.delTitle')} onClick={() => setConfirm({ ids: [r.id], forever: false })}>🗑</button>
            )}
          </div>
        )
      })}

      {batch && !trash && (
        <div className="batchbar">
          <span className="n">{t('home.selected', { n: sel.length })}</span>
          <select
            value=""
            disabled={!sel.length || busy}
            onChange={(e) => { const v = e.target.value; if (v) doMove(v === '__none__' ? '' : v) }}
          >
            <option value="">{t('home.moveTo')}</option>
            {folders.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
            <option value="__none__">{t('home.unfiled')}</option>
          </select>
          <div className="b">
            <button disabled={!sel.length || busy} onClick={() => setConfirm({ ids: sel, forever: false })}>{t('home.delete')}</button>
            <button onClick={exitBatch}>{t('home.cancel')}</button>
          </div>
        </div>
      )}

      {confirm && (
        <div className="modal-mask" onClick={() => !busy && setConfirm(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="m-hd">{confirm.forever ? t('home.delForeverQ') : t('home.delQ')}</div>
            <div className="m-bd">
              <b>{confirm.ids.length > 1 ? t('home.nRecordings', { n: confirm.ids.length }) : name(confirm.ids[0])}</b>
              {confirm.forever
                ? t('home.delForeverBody')
                : t('home.delTrashBody', { n: TRASH_DAYS })}
            </div>
            <div className="m-ft">
              <button className="btn" disabled={busy} onClick={() => setConfirm(null)}>{t('home.cancel')}</button>
              {!confirm.forever && (
                <button className="btn lk" disabled={busy} onClick={() => setConfirm({ ...confirm, forever: true })}>{t('home.deleteForever')}</button>
              )}
              <button className="btn dg" disabled={busy} onClick={doConfirm}>{busy ? t('home.processing') : confirm.forever ? t('home.deleteForever') : t('home.moveTrash')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
