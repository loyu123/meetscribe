import { useEffect, useState } from 'react'
import { getTemplates, createTemplate, updateTemplate, deleteTemplate } from '../api/recordings'
import type { SummaryTemplate, TplSection, TplOpts } from '../api/types'
import { t } from '../i18n'

const COLORS = ['#2b5cff', '#6d4aff', '#0f9d6b', '#d97a06', '#e0399b', '#38405a']

type Draft = {
  id?: string
  name: string
  color: string
  description: string
  sections: TplSection[]
  opts: TplOpts
  builtin?: boolean
}

const emptyDraft = (): Draft => ({
  name: '',
  color: COLORS[0],
  description: '',
  sections: [{ title: '', hint: '' }],
  opts: { timestamps: 1, todos: 1, formal: 1 },
})

/** 纪要模板管理（顶栏「纪要模板」入口）：模板库 + 编辑器。保存后广播 templates-changed。 */
export default function TemplateManager({ onClose }: { onClose: () => void }) {
  const [list, setList] = useState<SummaryTemplate[] | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => getTemplates().then(setList).catch(() => setList([]))
  useEffect(() => { load() }, [])

  const notify = () => window.dispatchEvent(new Event('templates-changed'))

  const startEdit = (t: SummaryTemplate) => {
    setErr(null)
    setDraft({
      id: t.id, name: t.name, color: t.color, description: t.description,
      sections: t.sections.length ? t.sections.map((s) => ({ ...s })) : [{ title: '', hint: '' }],
      opts: { ...t.opts }, builtin: t.builtin,
    })
  }

  const doCopy = async (tpl: SummaryTemplate) => {
    setBusy(true); setErr(null)
    try {
      const r = await createTemplate({
        name: tpl.name + t('tp2.copySuffix'), color: tpl.color, description: tpl.description,
        sections: tpl.sections, opts: tpl.opts,
      })
      if (r.error) setErr(r.error)
      load(); notify()
    } finally { setBusy(false) }
  }

  const doDelete = async (tpl: SummaryTemplate) => {
    if (!window.confirm(t('tp2.delConfirm', { name: tpl.name }))) return
    setBusy(true); setErr(null)
    try {
      const r = await deleteTemplate(tpl.id)
      if (r.error) setErr(r.error)
      load(); notify()
    } finally { setBusy(false) }
  }

  const doSave = async () => {
    if (!draft || busy) return
    setBusy(true); setErr(null)
    try {
      const secs = draft.sections.filter((s) => s.title.trim())
      const body = { name: draft.name.trim(), color: draft.color, description: draft.description, sections: secs, opts: draft.opts }
      const r = draft.id
        ? await updateTemplate(draft.id, body)
        : await createTemplate(body)
      if (r.error) { setErr(r.error); return }
      setDraft(null); load(); notify()
    } finally { setBusy(false) }
  }

  const moveSec = (i: number, d: -1 | 1) => {
    if (!draft) return
    const secs = [...draft.sections]
    const j = i + d
    if (j < 0 || j >= secs.length) return
    ;[secs[i], secs[j]] = [secs[j], secs[i]]
    setDraft({ ...draft, sections: secs })
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal tplmodal" onClick={(e) => e.stopPropagation()}>
        {draft ? (
          <>
            <div className="m-hd">{draft.id ? t('tp2.edit') + (draft.builtin ? t('tp2.builtinNote') : '') : t('tp2.new')}</div>
            <div className="m-bd tpled">
              <div className="erow two">
                <div className="efield" style={{ flex: 1 }}>
                  <label>{t('tp2.name')}</label>
                  <input value={draft.name} maxLength={30} disabled={draft.builtin}
                    placeholder={t('tp2.namePh')}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                </div>
                <div className="efield" style={{ width: 150 }}>
                  <label>{t('tp2.color')}</label>
                  <div className="colorrow">
                    {COLORS.map((c) => (
                      <span key={c} style={{ background: c }} className={draft.color === c ? 'on' : ''}
                        onClick={() => setDraft({ ...draft, color: c })} />
                    ))}
                  </div>
                </div>
              </div>
              <div className="erow">
                <div className="efield">
                  <label>{t('tp2.desc')}</label>
                  <input value={draft.description} maxLength={60}
                    placeholder={t('tp2.descPh')}
                    onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
                </div>
              </div>
              <div className="erow">
                <label>{t('tp2.sections')}</label>
                {draft.sections.map((s, i) => (
                  <div className="secrow" key={i}>
                    <span className="mv" title="▴/▾">
                      <b onClick={() => moveSec(i, -1)}>▴</b>
                      <b onClick={() => moveSec(i, 1)}>▾</b>
                    </span>
                    <div className="f">
                      <input value={s.title} placeholder={t('tp2.secTitle')}
                        onChange={(e) => {
                          const secs = [...draft.sections]
                          secs[i] = { ...secs[i], title: e.target.value }
                          setDraft({ ...draft, sections: secs })
                        }} />
                      <textarea rows={2} value={s.hint ?? ''} placeholder={t('tp2.secHint')}
                        onChange={(e) => {
                          const secs = [...draft.sections]
                          secs[i] = { ...secs[i], hint: e.target.value }
                          setDraft({ ...draft, sections: secs })
                        }} />
                    </div>
                    {!draft.builtin && (
                      <span className="del" title={t('tp2.delSec')} onClick={() => {
                        if (draft.sections.length <= 1) { setErr(t('tp2.minSec')); return }
                        setDraft({ ...draft, sections: draft.sections.filter((_, j) => j !== i) })
                      }}>✕</span>
                    )}
                  </div>
                ))}
                {!draft.builtin && (
                  <span className="addsec" onClick={() => setDraft({ ...draft, sections: [...draft.sections, { title: '', hint: '' }] })}>
                    {t('tp2.addSec')}
                  </span>
                )}
              </div>
              <div className="erow">
                <label>{t('tp2.opts')}</label>
                <div className="optrow">
                  <label className="chk"><input type="checkbox" checked={!!draft.opts.timestamps} disabled={draft.builtin}
                    onChange={(e) => setDraft({ ...draft, opts: { ...draft.opts, timestamps: e.target.checked ? 1 : 0 } })} />{t('tp2.optTs')}</label>
                  <label className="chk"><input type="checkbox" checked={!!draft.opts.todos} disabled={draft.builtin}
                    onChange={(e) => setDraft({ ...draft, opts: { ...draft.opts, todos: e.target.checked ? 1 : 0 } })} />{t('tp2.optTodos')}</label>
                  <label className="chk"><input type="checkbox" checked={!!draft.opts.formal} disabled={draft.builtin}
                    onChange={(e) => setDraft({ ...draft, opts: { ...draft.opts, formal: e.target.checked ? 1 : 0 } })} />{t('tp2.optFormal')}</label>
                </div>
              </div>
              {err && <div className="callout warn" style={{ marginTop: 8 }}>{err}</div>}
            </div>
            <div className="m-ft">
              <button className="btn" onClick={() => setDraft(null)}>{t('c.cancel')}</button>
              <button className="btn dg" disabled={busy} onClick={doSave}>{busy ? t('tp2.saving') : t('tp2.save')}</button>
            </div>
          </>
        ) : (
          <>
            <div className="m-hd">{t('tp2.lib')}</div>
            <div className="m-bd">
              {list === null && <div className="empty">{t('c.loading')}</div>}
              {list && (
                <div className="tplcards">
                  {list.map((tpl) => (
                    <div className="tcard" key={tpl.id}>
                      <div className="hd">
                        <span className="ic" style={{ background: tpl.color }}>{tpl.name.slice(0, 1)}</span>
                        <div>
                          <div className="nm">{tpl.name}{tpl.builtin && <span className="pill grey">{t('tp2.builtin')}</span>}</div>
                          <div className="tp">{t('tp2.usedIn', { n: tpl.sections.length })} · {tpl.opts.todos ? t('tp2.withTodos') : t('tp2.noTodos')}</div>
                        </div>
                      </div>
                      {tpl.description && <div className="ds">{tpl.description}</div>}
                      <div className="acts">
                        {tpl.builtin
                          ? <span onClick={() => doCopy(tpl)}>{t('tp2.copy')}</span>
                          : <>
                              <span onClick={() => startEdit(tpl)}>{t('tp2.edit')}</span>
                              <span onClick={() => doCopy(tpl)}>{t('tp2.copy')}</span>
                              <span className="dg" onClick={() => doDelete(tpl)}>{t('tp2.del')}</span>
                            </>}
                        {tpl.builtin && <span onClick={() => startEdit(tpl)}>{t('tp2.restyle')}</span>}
                      </div>
                    </div>
                  ))}
                  <div className="newtpl" onClick={() => { setErr(null); setDraft(emptyDraft()) }}>
                    <div className="plus">＋</div>
                    {t('tp2.new')}
                  </div>
                </div>
              )}
              {err && <div className="callout warn" style={{ marginTop: 10 }}>{err}</div>}
              <div className="note" style={{ marginTop: 12, fontSize: 11.5 }}>
                {t('tp2.note')}
              </div>
            </div>
            <div className="m-ft">
              <button className="btn" onClick={onClose}>{t('tp2.close')}</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
