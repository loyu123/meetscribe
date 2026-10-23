import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { loadSettings } from '../constants'
import { t } from '../i18n'

const ALLOWED = ['.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.amr', '.wma', '.mp4', '.mkv']
const PART_SIZE = 4 * 1024 * 1024
const MAX_BYTES = 4096 * 1024 * 1024
const FILE_CONCURRENCY = 2 // 同时上传的文件数（概念图 v9）

type ItemStatus = 'pending' | 'uploading' | 'done' | 'failed'
type Item = {
  key: string
  file: File
  status: ItemStatus
  progress: number
  partDone: number
  totalParts: number
  recordingId?: string
  jobId?: string
  error?: string
}

const totalPartsOf = (f: File) => Math.ceil(f.size / PART_SIZE) || 1

export default function NewTask() {
  const nav = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [items, setItems] = useState<Item[]>([])
  const [fileErr, setFileErr] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const [running, setRunning] = useState(false)
  const [p, setP] = useState(() => {
    // 以「设置」中保存的默认值预填（模型 / 热词 / 说话人数）
    const s = loadSettings()
    return { hotword: s.hotwords, spk: s.speakers, model: s.model || 'paraformer', denoise: false, cb: '' }
  })

  const upd = (key: string, patch: Partial<Item>) =>
    setItems((list) => list.map((x) => (x.key === key ? { ...x, ...patch } : x)))

  /** 追加文件：格式 / 大小校验，同名同大小去重 */
  const pick = (files: FileList | null) => {
    if (!files?.length) return
    setFileErr(null)
    const add: Item[] = []
    for (const f of Array.from(files)) {
      const ext = (f.name.slice(f.name.lastIndexOf('.')) || '').toLowerCase()
      if (!ALLOWED.includes(ext)) { setFileErr(t('new.errFormat', { name: f.name, ext })); continue }
      if (f.size > MAX_BYTES) { setFileErr(t('new.errTooLarge', { name: f.name })); continue }
      if (items.some((i) => i.file.name === f.name && i.file.size === f.size) ||
          add.some((i) => i.file.name === f.name && i.file.size === f.size)) {
        setFileErr(t('new.errDup', { name: f.name })); continue
      }
      add.push({
        key: f.name + ':' + f.size + ':' + f.lastModified,
        file: f, status: 'pending', progress: 0,
        partDone: 0, totalParts: totalPartsOf(f),
      })
    }
    if (add.length) setItems((list) => [...list, ...add])
    if (inputRef.current) inputRef.current.value = ''
  }

  const removeItem = (key: string) => {
    if (running) return
    setItems((list) => list.filter((x) => x.key !== key))
  }

  /** 单文件完整上传流程：init → 分片（3 路并发 + 重试）→ complete */
  const uploadOne = async (item: Item) => {
    const { file } = item
    upd(item.key, { status: 'uploading', progress: 0, partDone: 0, error: undefined })
    try {
      const init = await (await fetch('/api/v1/uploads/init', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name }),
      })).json()
      if (init.error) throw new Error(init.error)
      const uid: string = init.upload_id
      const parts = totalPartsOf(file)

      let cursor = 0
      let okCount = 0
      const worker = async () => {
        while (true) {
          const i = cursor++
          if (i >= parts) break
          const blob = file.slice(i * PART_SIZE, Math.min((i + 1) * PART_SIZE, file.size))
          // 单分片失败自动重试（瞬时断连抖动），最多 3 次
          let lastErr: unknown = null
          for (let attempt = 0; attempt < 3; attempt++) {
            try {
              const fd = new FormData()
              fd.append('file', blob, 'part')
              fd.append('index', String(i))
              const r = await fetch(`/api/v1/uploads/${uid}/part`, { method: 'POST', body: fd })
              if (!r.ok) throw new Error('HTTP ' + r.status)
              lastErr = null
              break
            } catch (e) {
              lastErr = e
              await new Promise((res) => setTimeout(res, 800 * (attempt + 1)))
            }
          }
          if (lastErr) throw new Error(t('new.partFail', { n: i + 1, err: String(lastErr) }))
          okCount++
          upd(item.key, { partDone: okCount, progress: Math.round((okCount / parts) * 100) })
        }
      }
      await Promise.all(Array.from({ length: Math.min(3, parts) }, worker))

      const comp = await (await fetch(`/api/v1/uploads/${uid}/complete`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          hotword: p.hotword,
          preset_spk_num: p.spk ? parseInt(p.spk, 10) : null,
          asr_model: p.model,
          denoise: p.denoise ? 1 : 0,
          callback_url: p.cb || undefined,
        }),
      })).json()
      if (comp.error) throw new Error(comp.error + (comp.code ? ' (' + comp.code + ')' : ''))
      upd(item.key, {
        status: 'done', progress: 100,
        recordingId: comp.recording_id, jobId: comp.job_id,
      })
      window.dispatchEvent(new Event('recordings-changed'))
    } catch (e) {
      upd(item.key, { status: 'failed', error: String(e instanceof Error ? e.message : e) })
    }
  }

  /** 批量上传：队列并发 2，单个失败不影响其他 */
  const startAll = async () => {
    const queue = items.filter((i) => i.status === 'pending' || i.status === 'failed')
    if (!queue.length) return
    setRunning(true)
    let idx = 0
    const workers = Array.from({ length: Math.min(FILE_CONCURRENCY, queue.length) }, async () => {
      while (true) {
        const i = idx++
        if (i >= queue.length) break
        await uploadOne(queue[i])
      }
    })
    await Promise.all(workers)
    setRunning(false)
  }

  const retryOne = (item: Item) => {
    if (running) return
    setRunning(true)
    uploadOne(item).finally(() => setRunning(false))
  }

  const doneN = items.filter((i) => i.status === 'done').length
  const failN = items.filter((i) => i.status === 'failed').length
  const finished = !running && items.length > 0 && items.every((i) => i.status === 'done' || i.status === 'failed')
  const totalBytes = items.reduce((a, i) => a + i.file.size, 0)
  const totalParts = items.reduce((a, i) => a + i.totalParts, 0)

  return (
    <div className="newtask">
      <h1 className="page-head">{t('new.title')}</h1>

      {/* ① 拖拽 / 多选 */}
      <div className={'drop' + (drag ? ' on' : '')}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files) }}>
        <div className="ic">⬆</div>
        <div className="t1">{t('new.drop')}</div>
        <div className="t2">{t('new.formats')} {ALLOWED.join(' / ')} · {t('new.maxSize')}</div>
        <input ref={inputRef} type="file" accept={ALLOWED.join(',')} multiple hidden
          onChange={(e) => pick(e.target.files)} />
      </div>

      {fileErr && <div className="callout warn" style={{ marginTop: 12 }}>{fileErr}</div>}

      {/* ② 文件列表（选择 / 上传进度 / 结果 三态一体） */}
      {items.length > 0 && (
        <div className="flist">
          {items.map((it) => (
            <div className="fitem" key={it.key}>
              <span className="fi">{it.file.name.slice(it.file.name.lastIndexOf('.') + 1).toUpperCase().slice(0, 4)}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="fn">{it.file.name}</div>
                <div className="fs">
                  {fmtSize(it.file.size)} · {t('new.chunks', { n: it.totalParts })}
                  {it.status === 'uploading' && ` · ${t('new.uploadedN', { a: it.partDone, b: it.totalParts })}`}
                  {it.status === 'done' && ` · ${t('new.ids', { rid: it.recordingId?.slice(0, 8) + '…', jid: it.jobId?.slice(0, 8) + '…' })}`}
                </div>
                {it.status === 'failed' && <div className="ferr">✕ {it.error}</div>}
              </div>
              <span className={
                'fst ' + (it.status === 'done' ? 'ok' : it.status === 'failed' ? 'fail' : it.status === 'uploading' ? 'run' : 'wait')
              }>
                {it.status === 'pending' && (running ? t('new.queued') : t('new.waitUpload'))}
                {it.status === 'uploading' && t('new.uploadingN', { p: it.progress })}
                {it.status === 'done' && t('new.uploaded')}
                {it.status === 'failed' && t('new.uploadFailed')}
              </span>
              <div className="bar" style={{ flex: 1.2 }}>
                <i style={{
                  width: it.status === 'done' ? '100%' : it.progress + '%',
                  background: it.status === 'done' ? 'var(--green)' : it.status === 'failed' ? 'var(--red)' : 'var(--primary)',
                }} />
              </div>
              {!running && it.status === 'pending' && <span className="x" title={t('new.remove')} onClick={() => removeItem(it.key)}>✕</span>}
              {!running && it.status === 'failed' && (
                <span className="retry" onClick={() => retryOne(it)}>{t('new.reUpload')}</span>
              )}
              {it.status === 'done' && (
                <span className="retry" onClick={() => nav('/job/' + it.jobId)}>{t('new.viewProgress')}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ③ 统一参数 */}
      <div className="params">
        <h4>{t('new.params', { multi: items.length > 1 ? t('new.paramsMulti') : t('new.paramsOpt') })}</h4>
        <div className="row2">
          <div className="field">
            <label>{t('new.asrModel')}</label>
            <select value={p.model} onChange={(e) => setP({ ...p, model: e.target.value })}>
              <option value="paraformer">{t('new.modelPara')}</option>
              <option value="sensevoice">{t('new.modelSv')}</option>
            </select>
          </div>
          <div className="field">
            <label>{t('new.speakers')}</label>
            <input type="text" inputMode="numeric" placeholder={t('new.speakersPh')} value={p.spk}
              onChange={(e) => setP({ ...p, spk: e.target.value.replace(/[^\d]/g, '') })} />
          </div>
        </div>
        <div className="field">
          <label>{t('new.hotword')}</label>
          <textarea placeholder={t('new.hotwordPh')} value={p.hotword}
            onChange={(e) => setP({ ...p, hotword: e.target.value })} />
          {p.hotword.trim().length > 100 && <div className="hot-hint">{t('new.hotLong')}</div>}
        </div>
        <div className="field">
          <div className="switch" onClick={() => setP({ ...p, denoise: !p.denoise })}>
            <span className={'track' + (p.denoise ? ' on' : '')}><i /></span>
            {t('new.denoise')}
          </div>
        </div>
        <div className="field">
          <label>{t('new.callback')}</label>
          <input type="text" placeholder="https://..." value={p.cb} onChange={(e) => setP({ ...p, cb: e.target.value })} />
        </div>
      </div>

      {/* ④ 汇总 + 操作 */}
      {finished && (
        <div className="sumup">
          <div className="s ok"><b>{doneN}</b><span>{t('new.done')}</span></div>
          {failN > 0 && <div className="s fail"><b>{failN}</b><span>{t('new.failedN')}</span></div>}
          {doneN > 0 && (
            <div className="s"><b>{doneN}</b><span>{t('new.running')}</span></div>
          )}
        </div>
      )}

      <div className="footrow">
        <button className="btn-primary" disabled={running || !items.some((i) => i.status === 'pending' || i.status === 'failed')}
          onClick={startAll} style={{ opacity: running ? 0.5 : 1 }}>
          {running ? t('new.uploading') : items.length > 1 ? t('new.startBatch', { n: items.filter((i) => i.status === 'pending' || i.status === 'failed').length }) : t('new.start')}
        </button>
        {!running && items.length > 0 && (
          <button className="btn-line" onClick={() => { setItems([]); setFileErr(null) }}>{t('new.clear')}</button>
        )}
        {items.length > 0 && (
          <span className="meta" style={{ fontSize: 11.5, color: 'var(--ink-400)' }}>
            {t('new.totalInfo', { size: fmtSize(totalBytes), n: totalParts })}
          </span>
        )}
      </div>
      {finished && doneN > 0 && (
        <div style={{ marginTop: 12 }}>
          <button className="btn-primary" onClick={() => nav('/')}>{t('new.viewWorkbench')}</button>
        </div>
      )}
    </div>
  )
}

function fmtSize(b: number): string {
  if (b < 1024 * 1024) return Math.round(b / 1024) + ' KB'
  if (b < 1024 * 1024 * 1024) return (b / 1024 / 1024).toFixed(1) + ' MB'
  return (b / 1024 / 1024 / 1024).toFixed(2) + ' GB'
}
