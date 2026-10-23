import { useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { getRecording, getSummary, postSummary, editSummary, groupSummary, getTemplates } from '../api/recordings'
import type { RecordingDetailResponse, SummaryStatus, SummaryContentMeeting, SummaryContentMemo, SummaryPoint, SummaryTemplate } from '../api/types'
import { fmtDuration, fmtTime } from '../utils/format'
import TranscriptPane from '../components/TranscriptPane'
import { t } from '../i18n'

type Tpl = string // 模板 id：'meeting' / 'memo' / 自定义模板 id
type Tab = 'transcript' | 'summary'

/** "00:10" / "00:00:10" → 秒 */
function parseTs(ts?: string): number {
  if (!ts) return 0
  const parts = ts.split(':').map((x) => parseInt(x, 10) || 0)
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  return parts[0] ?? 0
}

function PlainText(tpl: Tpl, c: SummaryContentMeeting | SummaryContentMemo | any): string {
  const lines: string[] = []
  // 自定义模板：sections 分组结构
  if (c && c.sections && typeof c.sections === 'object') {
    if (c.one_line) lines.push(c.one_line)
    for (const [title, pts] of Object.entries(c.sections)) {
      lines.push('【' + title + '】')
      ;(pts as SummaryPoint[]).forEach((p) =>
        lines.push('· ' + p.content + (p.speaker ? '（' + p.speaker + (p.timestamp ? ' ' + p.timestamp : '') + '）' : '')))
    }
    ;(c.todos ?? []).forEach((a: any) => lines.push('待办：' + a.task + (a.owner ? ' @' + a.owner : '') + (a.deadline ? ' 截止' + a.deadline : '')))
    return lines.join('\n')
  }
  if (tpl === 'meeting') {
    const m = c as SummaryContentMeeting
    if (m.title) lines.push('【' + m.title + '】')
    if (m.one_line) lines.push(m.one_line)
    if (m.attendees?.length) lines.push('参与人：' + m.attendees.join('、'))
    m.points?.forEach((p) => lines.push('· ' + p.content + (p.speaker ? '（' + p.speaker + (p.timestamp ? ' ' + p.timestamp : '') + '）' : '')))
    m.action_items?.forEach((a) => lines.push('行动项：' + a.task + (a.owner ? ' @' + a.owner : '') + (a.deadline ? ' 截止' + a.deadline : '')))
    m.risks?.forEach((r) => lines.push('风险：' + r.content + (r.level ? ' [' + r.level + ']' : '')))
  } else {
    const m = c as SummaryContentMemo
    if (m.owner) lines.push('备忘人：' + m.owner)
    if (m.one_line) lines.push(m.one_line)
    m.points?.forEach((p) => lines.push('· ' + p.content + (p.speaker ? '（' + p.speaker + (p.timestamp ? ' ' + p.timestamp : '') + '）' : '')))
    m.todos?.forEach((a) => lines.push('待办：' + a.task + (a.owner ? ' @' + a.owner : '') + (a.deadline ? ' 截止' + a.deadline : '')))
  }
  return lines.join('\n')
}

export default function MeetingDetail() {
  const { id = '' } = useParams()
  const [sp] = useSearchParams()
  const qtab = sp.get('tab')
  const [detail, setDetail] = useState<RecordingDetailResponse | null>(null)
  const [tab, setTab] = useState<Tab>(qtab === 'meeting' || qtab === 'memo' || qtab === 'summary' ? 'summary' : 'transcript') // 转写前置：默认打开即转写
  const [tpl, setTpl] = useState<Tpl>(qtab === 'memo' ? 'memo' : 'meeting')
  const [tpls, setTpls] = useState<SummaryTemplate[]>([])
  const [curMs, setCurMs] = useState(0)
  const [locate, setLocate] = useState(0)
  const audioRef = useRef<HTMLAudioElement>(null)

  const [sum, setSum] = useState<SummaryStatus | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [copied, setCopied] = useState(false)
  const [copyTsOk, setCopyTsOk] = useState(false)
  const timer = useRef<number | null>(null)

  const startPoll = (t: Tpl) => {
    if (timer.current) window.clearInterval(timer.current)
    let fails = 0
    timer.current = window.setInterval(() => {
      getSummary(id, t).then((s) => {
        fails = 0
        setSum(s)
        if (s.status !== 'processing' && timer.current) { window.clearInterval(timer.current); timer.current = null }
      }).catch(() => {
        // 后端重启导致内存任务丢失等场景：连续失败则回退可重新生成，避免永久卡「生成中」
        if (++fails >= 6 && timer.current) { window.clearInterval(timer.current); timer.current = null }
        setSum({ status: 'not_started' })
      })
    }, 2500)
  }

  const loadSummary = (t: Tpl) => {
    // 切换模板/录音前先停旧轮询，避免旧模板的响应覆盖新模板内容
    if (timer.current) { window.clearInterval(timer.current); timer.current = null }
    getSummary(id, t)
      .then((s) => { setSum(s); if (s.status === 'processing') startPoll(t) })
      .catch(() => setSum({ status: 'not_started' }))
  }

  const loadTpls = () => getTemplates().then(setTpls).catch(() => {})

  useEffect(() => {
    let alive = true
    let detailTimer: number | null = null
    let tries = 0
    // 首次加载后若转写仍在进行（无 result），轻量轮询直至完成，避免打开详情页永远空白
    const loadDetail = () => {
      getRecording(id).then((d) => {
        if (!alive) return
        setDetail(d)
        if (!d.result && tries++ < 60) {
          detailTimer = window.setTimeout(loadDetail, 5000)
        }
      }).catch(() => {})
    }
    loadDetail()
    loadTpls()
    const onTplChanged = () => loadTpls()
    window.addEventListener('templates-changed', onTplChanged)
    return () => {
      alive = false
      if (detailTimer) window.clearTimeout(detailTimer)
      if (timer.current) window.clearInterval(timer.current)
      window.removeEventListener('templates-changed', onTplChanged)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  useEffect(() => {
    if (tab === 'transcript') {
      if (timer.current) { window.clearInterval(timer.current); timer.current = null }
      return
    }
    setEditing(false)
    loadSummary(tpl)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, tab, tpl])

  const activeTpl = tpl
  const activeTplName = tpls.find((x) => x.id === tpl)?.name ?? t('dt.defaultTpl')

  const regen = () => {
    setSum({ status: 'processing' })
    postSummary(id, activeTpl, true)
      .then(() => startPoll(activeTpl))
      .catch((e) => setSum({ status: 'failed', error: String(e instanceof Error ? e.message : e) }))
  }

  const copy = () => {
    if (sum && sum.status === 'done') {
      navigator.clipboard?.writeText(PlainText(activeTpl, sum.content))
      setCopied(true); setTimeout(() => setCopied(false), 1500)
    }
  }

  // P1-3：一键复制带时间戳的纯文本转写（result.text 即「说话人(时间) 内容」格式）
  const copyTranscript = () => {
    const text = detail?.result?.text
    if (text) {
      navigator.clipboard?.writeText(text)
      setCopyTsOk(true); setTimeout(() => setCopyTsOk(false), 1500)
    }
  }

  const saveEdit = () => {
    if (sum && sum.status === 'done') {
      const before = PlainText(activeTpl, sum.content)
      editSummary(sum.id, before, draft)
        .then((r) => {
          if ((r as any).error) alert(t('c.saveFailed', { err: (r as any).error }))
          else loadSummary(activeTpl) // 保存成功后刷新，展示落库后的新版本
        })
        .catch((e) => alert(t('c.saveFailed', { err: String(e instanceof Error ? e.message : e) })))
    }
    setEditing(false)
  }

  /** 纪要时间戳 → 就地切到转写页签 + 播放器跳播 + 滚动定位（不跳页） */
  const gotoTs = (ts?: string) => {
    if (!ts) return
    const ms = parseTs(ts) * 1000
    setTab('transcript')
    setLocate((x) => x + 1)
    window.setTimeout(() => {
      const a = audioRef.current
      if (a) { a.currentTime = ms / 1000; a.play().catch(() => {}) }
    }, 140)
  }

  const rec = detail?.recording
  const result = detail?.result
  const reviewCount = result?.stats?.review_count ?? 0

  return (
    <div className="doc">
      <div className="detail-head">
        <div style={{ flex: 1 }}>
          <h1>{rec?.filename || t('c.loading')}</h1>
          <div className="byline">
            {fmtTime(rec?.created_at)} · {fmtDuration(rec?.duration_ms)} · {rec?.num_speakers ? t('home.spkN', { n: rec.num_speakers }) : t('home.spkDetecting')}
            {sum && sum.status === 'done' && <> · {sum.model} · v{sum.version}</>}
          </div>
        </div>
      </div>

      {/* 吸顶播放器：三个页签共享，边听边看 */}
      {result && (
        <div className="player stick">
          <audio
            ref={audioRef}
            src={rec?.media_url}
            controls
            preload="metadata"
            onTimeUpdate={(e) => setCurMs(e.currentTarget.currentTime * 1000)}
          />
          <span className="export">
            <a href={`/api/v1/recordings/${id}/subtitle?fmt=srt`} download>{t('dt.exportSrt')}</a>
            <a href={`/api/v1/recordings/${id}/subtitle?fmt=vtt`} download>{t('dt.exportVtt')}</a>
            <a href={`/api/v1/recordings/${id}/export?fmt=txt`} download>{t('dt.exportTxt')}</a>
            <a href={`/api/v1/recordings/${id}/export?fmt=md`} download>{t('dt.exportMd')}</a>
            <span className="lnk" style={{ cursor: 'pointer' }} onClick={copyTranscript}>{copyTsOk ? t('dt.copied') : t('dt.copyTs')}</span>
          </span>
        </div>
      )}

      <div className="tabs">
        <span className={'tb' + (tab === 'transcript' ? ' on' : '')} onClick={() => setTab('transcript')}>
          {t('dt.tabTranscript')}{result?.turns?.length ? <span className="n">（{result.turns.length}）</span> : null}
        </span>
        <span className={'tb' + (tab === 'summary' ? ' on' : '')} onClick={() => setTab('summary')}>{t('dt.tabSummary')}</span>
        {tab === 'summary' && (
          <select className="tplsel" value={tpl} title={t('dt.tplSel')}
            onChange={(e) => setTpl(e.target.value)}>
            {tpls.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        )}
        {tab !== 'transcript' && (
          <span className="act" style={{ marginLeft: 'auto' }}>
            <span onClick={copy}>{copied ? t('dt.copied') : '⧉ ' + t('dt.copy')}</span>
            <span onClick={regen}>⟳ {t('dt.regenerate')}</span>
            {sum?.status === 'done' && (
              <span onClick={() => { setDraft(PlainText(activeTpl, (sum as any).content)); setEditing((e) => !e) }}>
                {editing ? t('c.cancel') : '✎ ' + t('tp.edit')}
              </span>
            )}
          </span>
        )}
      </div>

      {tab === 'transcript' ? (
        detail ? (
          <TranscriptPane
            id={id} detail={detail} audioRef={audioRef} curMs={curMs} locate={locate}
            onSpeakersChanged={() => getRecording(id).then((d) => setDetail(d)).catch(() => {})}
            onTurnEdited={(startMs, text) => setDetail((d) => d ? {
              ...d,
              result: d.result ? {
                ...d.result,
                turns: (d.result.turns ?? []).map((t) => t.start_ms === startMs ? { ...t, text } : t),
              } : d.result,
            } : d)}
          />
        ) : (
          <div className="empty">{t('c.loading')}</div>
        )
      ) : (
        <>
          {sum?.status === 'done' && (sum as any).stale === 1 && (
            <div className="callout stale">{t('dt.stale')}</div>
          )}
          {tpl === 'meeting' && tab === 'summary' && reviewCount > 0 && (
            <div className="callout warn">{t('dt.lowConfWarn', { n: reviewCount })}</div>
          )}

          {editing && (
            <textarea className="sum-edit" value={draft} onChange={(e) => setDraft(e.target.value)} style={{ width: '100%', minHeight: 220, border: '1px solid var(--line)', borderRadius: 12, padding: 12, fontFamily: 'inherit', fontSize: 13 }} />
          )}
          {editing && <button className="btn-primary" onClick={saveEdit} style={{ marginTop: 10 }}>{t('dt.editSave')}</button>}

          {!editing && sum?.status === 'not_started' && (
            <div className="empty">
              <p>{t('dt.notStarted', { tpl: activeTplName })}</p>
              <button className="btn-primary" style={{ marginTop: 12 }} onClick={regen}>{t('dt.generate')}</button>
            </div>
          )}
          {!editing && sum?.status === 'processing' && <div className="empty">{t('dt.generating')}</div>}
          {!editing && sum?.status === 'failed' && <div className="callout warn">{t('dt.failedGen')}：{(sum as any).error}</div>}

          {!editing && sum?.status === 'done' && (
            <SummaryView id={id} tpl={activeTpl} content={sum.content} onGoto={gotoTs} />
          )}
        </>
      )}
    </div>
  )
}

type Group = { title: string; idx: number[] }

/** 会议总结关键词高亮：数字/型号（v2.3、80%、1200）与全大写缩写（API、QPS、SLA）自动着色 */
function hiText(t: string) {
  const parts = t.split(/([A-Za-z]*\d+(?:\.\d+)?[A-Za-z]*%?|[A-Z]{2,}(?:\d+(?:\.\d+)?)?%?)/g)
  return parts.map((p, i) =>
    /^[A-Za-z]*\d/.test(p) || /^[A-Z]{2,}/.test(p)
      ? <b key={i}>{p}</b>
      : <span key={i}>{p}</span>
  )
}

/** 顶部醒目会议总结（概念图 v7 方案 D：白底大字 + 关键词高亮） */
function SumLine({ text, onCopy }: { text: string; onCopy?: () => void }) {
  return (
    <div className="oneline">
      <div className="eyebrow">{t('dt.aiSum')}</div>
      <div className="tx">{hiText(text)}</div>
      {onCopy && <span className="ocopy" onClick={onCopy}>⧉ {t('dt.copy')}</span>}
    </div>
  )
}

function TsJump({ ts, onGoto }: { ts?: string; onGoto: (ts?: string) => void }) {
  if (!ts) return null
  return <span className="src" style={{ cursor: 'pointer' }} onClick={() => onGoto(ts)}>▶ {ts}</span>
}

function PointItem({ p, onGoto }: { p: SummaryPoint; onGoto: (ts?: string) => void }) {
  return (
    <li>
      <span className="tx">{p.content}</span>
      <span className="pmeta">
        {p.speaker && <span>{p.speaker}</span>}
        <TsJump ts={p.timestamp} onGoto={onGoto} />
      </span>
    </li>
  )
}

function MeetingSummary({ id, m, onGoto }: { id: string; m: SummaryContentMeeting; onGoto: (ts?: string) => void }) {
  const points = m.points ?? []
  const items = m.action_items?.length ?? 0
  const risks = m.risks?.length ?? 0
  const [tab, setTab] = useState<'points' | 'tasks' | 'risks'>('points')
  const [groups, setGroups] = useState<Group[] | null>(null)
  const [gfail, setGfail] = useState(false)
  const [open, setOpen] = useState<Record<number, boolean>>({})

  const n = points.length
  useEffect(() => {
    let alive = true
    setGroups(null); setGfail(false); setOpen({})
    if (n < 4) { setGroups([]); return } // 太少不必分组
    groupSummary(id, points.map((p) => ({ content: p.content, speaker: p.speaker, timestamp: p.timestamp })))
      .then((r) => {
        if (!alive) return
        if (r.groups && r.groups.length > 1) {
          setGroups(r.groups)
          setOpen(Object.fromEntries(r.groups.map((_, i) => [i, i === 0])))
        } else {
          setGroups([])
        }
      })
      .catch(() => { if (alive) setGfail(true) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, n])

  const flat = (list: SummaryPoint[]) => <ul>{list.map((p, i) => <PointItem key={i} p={p} onGoto={onGoto} />)}</ul>

  return (
    <>
      {m.one_line && <SumLine text={m.one_line} onCopy={() => navigator.clipboard?.writeText(m.one_line!)} />}
      <div className="kpi">
        <div className="k"><b>{n}</b><span>{t('dt.kpiPoints')}</span></div>
        <div className="k"><b>{items}</b><span>{t('dt.kpiActions')}</span></div>
        <div className="k"><b>{risks}</b><span>{t('dt.risks')}</span></div>
      </div>
      {m.attendees?.length ? <p style={{ marginBottom: 10 }}>{t('dt.attendees')}{m.attendees.join('、')}</p> : null}

      <div className="subtabs">
        <span className={'tb' + (tab === 'points' ? ' on' : '')} onClick={() => setTab('points')}>{t('dt.tabPoints', { n })}</span>
        {items > 0 && <span className={'tb' + (tab === 'tasks' ? ' on' : '')} onClick={() => setTab('tasks')}>{t('dt.tabActions', { n: items })}</span>}
        {risks > 0 && <span className={'tb' + (tab === 'risks' ? ' on' : '')} onClick={() => setTab('risks')}>{t('dt.tabRisks', { n: risks })}</span>}
      </div>

      {tab === 'points' && (
        groups === null && !gfail && n >= 4 ? (
          <>
            <div className="callout" style={{ marginBottom: 10 }}>{t('dt.grouping')}</div>
            {flat(points)}
          </>
        ) : groups && groups.length > 1 ? (
          <div>
            {groups.map((g, gi) => {
              const isOpen = open[gi] ?? gi === 0
              return (
                <div className="grp" key={gi}>
                  <div className="gh" onClick={() => setOpen((o) => ({ ...o, [gi]: !isOpen }))}>
                    <span>{isOpen ? '▾' : '▸'}</span>{g.title}
                    <span className="n">{t('dt.nItems', { n: g.idx.length })}</span>
                  </div>
                  {isOpen && <ul>{g.idx.map((pi) => <PointItem key={pi} p={points[pi]} onGoto={onGoto} />)}</ul>}
                </div>
              )
            })}
            {gfail && <div className="note" style={{ fontSize: 11, color: 'var(--ink-400)' }}>{t('dt.groupNote')}</div>}
          </div>
        ) : (
          <>
            {gfail && <div className="note" style={{ fontSize: 11, color: 'var(--ink-400)', marginBottom: 6 }}>{t('dt.groupUnavailable')}</div>}
            {flat(points)}
          </>
        )
      )}

      {tab === 'tasks' && (
        <table className="tasktbl">
          <thead><tr><th>{t('dt.colTask')}</th><th>{t('dt.colOwner')}</th><th>{t('dt.colDue')}</th></tr></thead>
          <tbody>
            {m.action_items?.map((a, i) => (
              <tr key={i}><td>{a.task}</td><td>{a.owner || '—'}</td><td>{a.deadline || '—'}</td></tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === 'risks' && (
        <div>
          {m.risks?.map((r, i) => (
            <div className="riskli" key={i}>
              {r.level && <span className={'lvl ' + r.level}>{r.level}</span>}
              <span>{r.content}</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function SummaryView({ id, tpl, content, onGoto }: { id: string; tpl: Tpl; content: SummaryContentMeeting | SummaryContentMemo; onGoto: (ts?: string) => void }) {
  const anyC = content as any
  // 自定义模板：sections 分组结构（每章一组，要点带时间戳溯源）
  if (anyC?.sections && typeof anyC.sections === 'object' && Object.keys(anyC.sections).length) {
    return <CustomSummary c={anyC} onGoto={onGoto} />
  }
  if (tpl === 'meeting') return <MeetingSummary id={id} m={content as SummaryContentMeeting} onGoto={onGoto} />
  const m = content as SummaryContentMemo
  return (
    <>
      {m.owner && <p style={{ marginBottom: 6 }}>{t('dt.owner')}{m.owner}</p>}
      {m.one_line && <SumLine text={m.one_line} onCopy={() => navigator.clipboard?.writeText(m.one_line!)} />}
      <div className="kpi"><div className="k"><b>{m.points?.length ?? 0}</b><span>{t('dt.kpiPoints')}</span></div><div className="k"><b>{m.todos?.length ?? 0}</b><span>{t('dt.todos')}</span></div></div>
      <h4>{t('dt.kpiPoints')}</h4>
      <ul>{m.points?.map((p, i) => <PointItem key={i} p={p} onGoto={onGoto} />)}</ul>
      {m.todos?.length ? <><h4>{t('dt.todos')}</h4>{m.todos.map((a, i) => <div className="todo" key={i}><div className="box" /><p>{a.task}{a.owner && <span className="meta">@{a.owner}</span>}{a.deadline && <span className="meta">{t('dt.deadline')} {a.deadline}</span>}</p></div>)}</> : null}
    </>
  )
}

/** 自定义模板渲染：按模板章节分组，复用要点组件与时间戳跳转 */
function CustomSummary({ c, onGoto }: { c: any; onGoto: (ts?: string) => void }) {
  const secs = Object.entries(c.sections ?? {}) as [string, SummaryPoint[]][]
  const total = secs.reduce((a, [, pts]) => a + (pts?.length ?? 0), 0)
  const todos = (c.todos ?? []) as { task: string; owner?: string; deadline?: string }[]
  return (
    <>
      {c.one_line && <SumLine text={c.one_line} onCopy={() => navigator.clipboard?.writeText(c.one_line)} />}
      <div className="kpi">
        <div className="k"><b>{total}</b><span>{t('dt.kpiPoints')}</span></div>
        <div className="k"><b>{todos.length}</b><span>{t('dt.todos')}</span></div>
      </div>
      <div className="csum">
        {secs.map(([title, pts]) => (
          <div className="csec" key={title}>
            <div className="cst">{title}</div>
            {pts?.length ? (
              <ul>{pts.map((p, i) => <PointItem key={i} p={p} onGoto={onGoto} />)}</ul>
            ) : (
              <div className="note" style={{ fontSize: 11.5, color: 'var(--ink-400)' }}>{t('dt.secEmpty')}</div>
            )}
          </div>
        ))}
      </div>
      {todos.length > 0 && (
        <>
          <h4>{t('dt.todos')}</h4>
          {todos.map((a, i) => (
            <div className="todo" key={i}><div className="box" />
              <p>{a.task}{a.owner && <span className="meta">@{a.owner}</span>}{a.deadline && <span className="meta">{t('dt.deadline')} {a.deadline}</span>}</p>
            </div>
          ))}
        </>
      )}
    </>
  )
}
