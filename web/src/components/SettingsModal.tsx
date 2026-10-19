import { useEffect, useState } from 'react'
import { loadSettings, saveSettings, type AppSettings } from '../constants'
import { getGateway, saveGateway, testGateway, type GatewaySettings } from '../api/settings'
import { t, useLang } from '../i18n'

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const [s, setS] = useState<AppSettings>(() => loadSettings())
  const [lang, setLang] = useLang()
  const [gw, setGw] = useState<GatewaySettings | null>(null)
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [llm, setLlm] = useState('')
  const [embed, setEmbed] = useState('')
  const [rerank, setRerank] = useState('')
  const [gwMsg, setGwMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [testing, setTesting] = useState(false)
  const [savingGw, setSavingGw] = useState(false)

  useEffect(() => {
    getGateway().then((g) => {
      setGw(g)
      setUrl(g.gateway_url)
      setLlm(g.llm_model)
      setEmbed(g.embed_model)
      setRerank(g.rerank_model)
    }).catch((e) => setGwMsg({ ok: false, text: t('c.loadFailed', { err: String(e instanceof Error ? e.message : e) }) }))
  }, [])

  const saveGw = async () => {
    setSavingGw(true); setGwMsg(null)
    try {
      const r = await saveGateway({
        gateway_url: url,
        gateway_token: token, // 空字符串 = 不修改现有密钥（后端约定）
        llm_model: llm,
        embed_model: embed,
        rerank_model: rerank,
      })
      setGw(r.settings)
      setToken('')
      setGwMsg({ ok: true, text: t('gw.saved') })
    } catch (e) {
      setGwMsg({ ok: false, text: t('c.saveFailed', { err: String(e instanceof Error ? e.message : e) }) })
    } finally { setSavingGw(false) }
  }

  const doTest = async () => {
    setTesting(true); setGwMsg(null)
    try {
      const r = await testGateway()
      setGwMsg({ ok: true, text: t('gw.testOk', { n: r.models.length, models: r.models.slice(0, 6).join(', ') }) })
    } catch (e) {
      setGwMsg({ ok: false, text: t('gw.testFail', { err: String(e instanceof Error ? e.message : e) }) })
    } finally { setTesting(false) }
  }

  const save = () => {
    saveSettings(s)
    onClose()
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="m-hd">{t('set.title')}</div>
        <div className="m-bd">
          <label className="fld">{t('set.lang')}</label>
          <select value={lang} onChange={(e) => setLang(e.target.value as 'zh' | 'en')}>
            <option value="zh">简体中文</option>
            <option value="en">English</option>
          </select>

          <label className="fld">{t('set.appearance')}</label>
          <select value={s.theme} onChange={(e) => setS({ ...s, theme: e.target.value })}>
            <option value="light">{t('set.light')}</option>
            <option value="dark">{t('set.dark')}</option>
            <option value="system">{t('set.system')}</option>
          </select>

          <label className="fld">{t('gw.section')}</label>
          <input type="text" value={url} placeholder="http://127.0.0.1:9997/v1"
            onChange={(e) => setUrl(e.target.value)} />
          <input type="password" value={token} style={{ marginTop: 7 }}
            placeholder={gw?.token_set ? t('gw.tokenKeep', { masked: gw.gateway_token_masked }) : t('gw.tokenPh')}
            onChange={(e) => setToken(e.target.value)} />
          <div className="gwrow">
            <div>
              <label className="fld">{t('gw.llm')}</label>
              <input type="text" value={llm} onChange={(e) => setLlm(e.target.value)} />
            </div>
            <div>
              <label className="fld">{t('gw.embed')}</label>
              <input type="text" value={embed} onChange={(e) => setEmbed(e.target.value)} />
            </div>
            <div>
              <label className="fld">{t('gw.rerank')}</label>
              <input type="text" value={rerank} onChange={(e) => setRerank(e.target.value)} />
            </div>
          </div>
          <div className="gwacts">
            <button className="btn-line" disabled={testing} onClick={doTest}>
              {testing ? t('gw.testing') : t('gw.test')}
            </button>
            <button className="btn-line" disabled={savingGw || !url} onClick={saveGw}>
              {savingGw ? t('tp2.saving') : t('gw.apply')}
            </button>
          </div>
          {gwMsg && (
            <div className={'callout' + (gwMsg.ok ? '' : ' warn')}
              style={gwMsg.ok ? { marginTop: 8, fontSize: 11.5, background: 'var(--green-50, #e7f6f0)', borderColor: '#bfe5d5', color: 'var(--green, #0f9d6b)' } : { marginTop: 8, fontSize: 11.5 }}>
              {gwMsg.text}
            </div>
          )}
          <div className="m-tip" style={{ marginTop: 8, fontSize: 11, color: 'var(--ink-400)' }}>
            {t('gw.note')}
          </div>

          <label className="fld">{t('set.model')}</label>
          <select value={s.model} onChange={(e) => setS({ ...s, model: e.target.value })}>
            <option value="paraformer">{t('new.modelPara')}</option>
            <option value="sensevoice">SenseVoice</option>
          </select>

          <label className="fld">{t('set.hotwords')}</label>
          <textarea rows={2} value={s.hotwords} placeholder={t('new.hotwordPh')}
            onChange={(e) => setS({ ...s, hotwords: e.target.value })} />

          <label className="fld">{t('set.speakers')}</label>
          <select value={s.speakers} onChange={(e) => setS({ ...s, speakers: e.target.value })}>
            <option value="">{t('set.autoSpk')}</option>
            {[2, 3, 4, 5, 6].map((n) => <option key={n} value={String(n)}>{t('home.spkN', { n })}</option>)}
          </select>

          <label className="fld">{t('set.apiQuota')}</label>
          <div style={{ fontSize: 12, color: 'var(--ink-500)', lineHeight: 1.8 }}>
            {t('set.quotaInfo')}
          </div>

          <div className="m-tip" style={{ marginTop: 12, fontSize: 11, color: 'var(--ink-400)' }}>
            {t('set.tip')}
          </div>
        </div>
        <div className="m-ft">
          <button className="btn" onClick={onClose}>{t('c.cancel')}</button>
          <button className="btn pri" onClick={save}>{t('c.save')}</button>
        </div>
      </div>
    </div>
  )
}
