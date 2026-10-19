import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { askApi, type AskMsg } from '../api/ask'
import { ASK_FOLD_KEY } from '../constants'
import { t } from '../i18n'

/** 清理 LLM 输出里的 Markdown 符号（**加粗、-/* 列表符、# 标题、` 代码引号），纯文本展示 */
function stripMd(s: string): string {
  return s
    .replace(/^#{1,6}\s+/gm, '')          // 标题符
    .replace(/\*\*([^*]+)\*\*/g, '$1')    // **加粗**
    .replace(/\*([^*\n]+)\*/g, '$1')      // *斜体*
    .replace(/^\s*[-*•]\s+/gm, '')        // 行首列表符
    .replace(/`([^`]+)`/g, '$1')          // `代码`
}

export default function AskPanel() {
  const loc = useLocation()
  const m = loc.pathname.match(/^\/m\/([^/]+)/)
  const recordingId = m ? m[1] : undefined

  const [msgs, setMsgs] = useState<AskMsg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [folded, setFolded] = useState(() => localStorage.getItem(ASK_FOLD_KEY) === '1')

  const toggleFold = () =>
    setFolded((f) => {
      localStorage.setItem(ASK_FOLD_KEY, f ? '0' : '1')
      return !f
    })

  const send = async (text: string) => {
    const q = text.trim()
    if (!q || busy) return
    setErr(null)
    const history = msgs.map((x) => ({ role: x.role, content: x.content }))
    const next = [...msgs, { role: 'user' as const, content: q }]
    setMsgs(next); setInput(''); setBusy(true)
    try {
      const r = await askApi(q, recordingId, history)
      setMsgs([...next, { role: 'assistant' as const, content: r.answer }])
    } catch (e) {
      setErr(t('ask.fail', { err: String(e instanceof Error ? e.message : e) }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className={'askrail' + (folded ? ' folded' : '')}>
      <div className="hd">
        <span className="dotk" /> <span className="tt">{t('ask.title')}</span>
        <span className="scope">{recordingId ? t('ask.scopeMeeting') : t('ask.scopeCross')}</span>
        <button className="fold" title={folded ? t('ask.expand') : t('ask.fold')} onClick={toggleFold}>
          {folded ? '»' : '«'}
        </button>
      </div>

      <div className="body">
        {msgs.length === 0 && (
          <div className="hint" style={{ textAlign: 'center', marginTop: 30 }}>
            {t('ask.ph')}
          </div>
        )}

        {msgs.map((x, i) => (
          <div key={i} className={'msg ' + x.role}>
            <div className="who">{x.role === 'user' ? t('ask.me') : t('ask.ai')}</div>
            <div className="bub">{x.role === 'assistant' ? stripMd(x.content) : x.content}</div>
          </div>
        ))}

        {busy && (
          <div className="msg assistant">
            <div className="who">{t('ask.ai')}</div>
            <div className="bub thinking"><i></i><i></i><i></i> {t('ask.thinking')}</div>
          </div>
        )}
        {err && <div className="callout warn">{err}</div>}
      </div>

      <div className="ft">
        <textarea
          placeholder={t('ask.phEnter')}
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
        />
        <button className="send" disabled={busy || !input.trim()} onClick={() => send(input)}>
          {busy ? t('ask.sending') : t('ask.send')}
        </button>
      </div>
    </aside>
  )
}
