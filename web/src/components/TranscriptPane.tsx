import { useEffect, useRef, useState } from 'react'
import { getRecording, postPolish, getPolish, editTurn, renameSpeaker, saveVoiceprint } from '../api/recordings'
import type { RecordingDetailResponse, Result, Turn } from '../api/types'
import { t } from '../i18n'

const PALETTE = ['#2b5cff', '#e0399b', '#0f9d6b', '#d97a06', '#6d4aff', '#e0342b']
type View = 'orig' | 'smooth' | 'polish'

interface Props {
  id: string
  detail: RecordingDetailResponse
  audioRef: { current: HTMLAudioElement | null }
  curMs: number
  locate: number
  onTurnEdited?: (startMs: number, text: string) => void
  onSpeakersChanged?: () => void
}

/** 逐句转写面板：嵌入会议详情页第一个页签（转写前置，见概念图 v6 方案一） */
export default function TranscriptPane({ id, detail, audioRef, curMs, locate, onTurnEdited, onSpeakersChanged }: Props) {
  const [smooth, setSmooth] = useState<Result | null>(null)
  const [view, setView] = useState<View>('orig')
  const [polish, setPolish] = useState<{ status: string; result?: Result; error?: string }>({ status: 'not_started' })
  const [edit, setEdit] = useState<{ i: number; val: string } | null>(null)
  // i：正在编辑的那一句（同一说话人会出现多句，必须按句绑定，否则每句都会弹出编辑面板）
  const [renaming, setRenaming] = useState<{ i: number; spk: string; val: string; vp?: boolean } | null>(null)
  const [renamingBusy, setRenamingBusy] = useState(false)
  const timer = useRef<number | null>(null)

  const result = detail.result
  const spkColors = (result?.speakers ?? []).map((s, i) => ({ spk: s.spk, color: PALETTE[i % PALETTE.length] }))
  const colorOf = (spk: string | number) => spkColors.find((c) => String(c.spk) === String(spk))?.color ?? '#6b7488'

  const badTurn = (t: Turn): boolean => {
    const segs = result?.segments ?? []
    return segs.some((s: any) =>
      s.need_review && s.start_ms >= (t.start_ms ?? 0) && s.start_ms <= (t.end_ms ?? 0))
  }

  useEffect(() => {
    let alive = true
    setSmooth(null) // 切换录音：先清空旧数据，避免旧响应晚到覆盖（竞态）
    getRecording(id, true).then((d) => { if (alive) setSmooth(d.result) }).catch(() => {})
    return () => {
      alive = false
      if (timer.current) window.clearInterval(timer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  // 纪要时间戳跳转：滚动定位到当前播放句并保持高亮
  useEffect(() => {
    if (!locate) return
    const t = window.setTimeout(() => {
      document.querySelector('.turn.cur')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 280)
    return () => window.clearTimeout(t)
  }, [locate])

  const turnsOf = (): Turn[] => {
    if (view === 'smooth') return smooth?.turns ?? []
    if (view === 'polish') return polish.result?.turns ?? []
    return result?.turns ?? []
  }

  const seek = (t: Turn) => {
    const a = audioRef.current
    if (!a) return
    a.currentTime = (t.start_ms ?? 0) / 1000
    a.play().catch(() => {})
  }

  // P1-1：说话人重命名（本会议内生效，后端同步全文与检索索引）
  const labelOf = (spk: string | number): string =>
    result?.speakers?.find((s) => String(s.spk) === String(spk))?.label ?? t('tp.spkUnknown')

  const doRename = async () => {
    if (!renaming) return
    const val = renaming.val.trim()
    if (!val) { setRenaming(null); return }
    const cur = labelOf(renaming.spk)
    // U6：勾选存声纹但没改名 → 保持面板打开并显示内联提示，
    // 避免“看起来存了其实什么都没做”的静默失败。
    if (renaming.vp && val === cur) return
    if (val === cur) { setRenaming(null); return }
    const saveVp = !!renaming.vp
    setRenamingBusy(true)
    try {
      if (val !== cur) {
        const r = await renameSpeaker(id, renaming.spk, val)
        if (r.error) { alert(t('c.saveFailed', { err: r.error })); return }
        onSpeakersChanged?.()
      }
      // P3-3：勾选后把该说话人质心存入声纹库，后续新会议自动识别此人
      if (saveVp) {
        const v = await saveVoiceprint(id, renaming.spk, val)
        if (v.error) alert(t('c.saveFailed', { err: v.error }))
      }
    } catch (e) {
      alert(t('c.saveFailed', { err: String(e instanceof Error ? e.message : e) }))
    } finally {
      setRenamingBusy(false)
      setRenaming(null)
    }
  }

  if (!result) {
    return <div className="empty">{t('tp.empty')}</div>
  }

  const turns = turnsOf()
  const cur = view === 'orig'
    ? turns.findIndex((t) => curMs >= (t.start_ms ?? 0) && curMs < (t.end_ms ?? 0))
    : -1
  const reviewCount = result.stats?.review_count ?? 0

  return (
    <div className="tpane">
      {reviewCount > 0 && (
        <div className="callout warn">{t('tp.lowConfWarn', { n: reviewCount })}</div>
      )}

      <div className="viewtabs">
        <span className={'vt' + (view === 'orig' ? ' on' : '')} onClick={() => setView('orig')}>{t('tp.viewOrig')}</span>
        <span className={'vt' + (view === 'smooth' ? ' on' : '')} onClick={() => setView('smooth')}>{t('tp.viewSmooth')}</span>
        <span className={'vt' + (view === 'polish' ? ' on' : '')} onClick={() => setView('polish')}>{t('tp.viewPolish')}</span>
      </div>

      {view === 'polish' && polish.status !== 'done' && (
        <div className="polish-cta">
          <p>{t('tp.polishHint')}</p>
          {polish.status === 'processing' ? (
            <span className="btn-line">{t('tp.polishDoing')}</span>
          ) : polish.status === 'failed' ? (
            <><div className="callout warn">{t('tp.polishFailMsg', { err: polish.error ?? '' })}</div><span className="btn-primary" onClick={genPolish}>{t('tp.retry')}</span></>
          ) : (
            <span className="btn-primary" onClick={genPolish}>{t('tp.polishBtn')}</span>
          )}
        </div>
      )}

      <div className="turns">
        {turns.map((tu, i) => (
          <div key={i}
            className={'turn' + (view === 'orig' && i === cur ? ' cur' : '')
              + (view === 'orig' && badTurn(tu) ? ' bad' : '')}
            onClick={() => { if (renaming) { setRenaming(null); return } if (edit?.i !== i) seek(tu) }}>
            {/* 重命名面板独立成行（说话人标签列只有 58px，塞进去会压住正文） */}
            {view === 'orig' && renaming && renaming.i === i && (
              <span className="spk-ren" onClick={(e) => e.stopPropagation()}>
                <input
                  autoFocus
                  value={renaming.val}
                  maxLength={30}
                  disabled={renamingBusy}
                  onChange={(e) => setRenaming({ ...renaming, val: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') doRename()
                    if (e.key === 'Escape') setRenaming(null)
                  }}
                />
                <span className={'ok' + (renaming.vp && renaming.val.trim() === labelOf(renaming.spk) ? ' off' : '')}
                  title={t('c.save')} onClick={doRename}>{renamingBusy ? '…' : '✓'}</span>
                <span className="cc" onClick={() => setRenaming(null)}>✕</span>
                <label className="vp-save" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={!!renaming.vp} onChange={(e) => setRenaming({ ...renaming, vp: e.target.checked })} />
                  {t('tp.vpSave')}
                </label>
                {renaming.vp && renaming.val.trim() === labelOf(renaming.spk) && (
                  <span className="vp-hint">{t('tp.vpNeedName', { name: labelOf(renaming.spk) })}</span>
                )}
              </span>
            )}
            <div className="lab" style={{ color: colorOf(tu.spk) }}>
              <span
                className={view === 'orig' ? 'spk-name' : ''}
                title={view === 'orig' ? t('tp.renameTip') : undefined}
                onClick={view === 'orig' ? (e) => { e.stopPropagation(); setRenaming({ i, spk: String(tu.spk), val: labelOf(tu.spk) }) } : undefined}
              >
                {labelOf(tu.spk)}
              </span>
              <span className="ts">{tu.start}</span>
            </div>
            {view === 'orig' && edit?.i === i ? (
              <div className="tx editwrap" onClick={(e) => e.stopPropagation()}>
                <textarea
                  autoFocus
                  value={edit.val}
                  onChange={(e) => setEdit({ i: edit.i, val: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') setEdit(null)
                    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSave() }
                  }}
                />
                <div className="edacts">
                  <span className="sv" onClick={() => doSave()}>{t('c.save')}</span>
                  <span className="cc" onClick={() => setEdit(null)}>{t('c.cancel')}</span>
                </div>
              </div>
            ) : (
              <div className="tx">
                {tu.text}
                {view === 'orig' && badTurn(tu) && <span className="flag">{t('dt.reviewFlag')}</span>}
                {view === 'orig' && (
                  <span className="tedit" title={t('tp.editTip')}
                    onClick={(e) => { e.stopPropagation(); setEdit({ i, val: tu.text }) }}>{t('tp.edit')}</span>
                )}
              </div>
            )}
          </div>
        ))}
        {turns.length === 0 && <div className="empty">{t('dt.noResult')}</div>}
      </div>
    </div>
  )

  async function doSave() {
    if (!edit) return
    const tu = turns[edit.i]
    const val = edit.val.trim()
    if (!val || val === tu.text) { setEdit(null); return }
    try {
      const r = await editTurn(id, tu.start_ms ?? 0, val)
      if (r.error) { alert(t('c.saveFailed', { err: r.error })); return }
      onTurnEdited?.(tu.start_ms ?? 0, val)
      setEdit(null)
    } catch (e) {
      alert(t('c.saveFailed', { err: String(e instanceof Error ? e.message : e) }))
    }
  }

  function genPolish() {
    setPolish((p) => ({ ...p, status: 'processing' }))
    postPolish(id)
    if (timer.current) window.clearInterval(timer.current)
    let fails = 0
    timer.current = window.setInterval(() => {
      getPolish(id).then((p) => {
        fails = 0
        setPolish(p)
        if (p.status !== 'processing' && timer.current) { window.clearInterval(timer.current); timer.current = null }
      }).catch(() => {
        // 连续拉取失败（如后端重启导致任务丢失）→ 停止轮询并回退到可重新生成
        if (++fails >= 6 && timer.current) {
          window.clearInterval(timer.current); timer.current = null
          setPolish({ status: 'not_started' })
        }
      })
    }, 2500)
  }
}
