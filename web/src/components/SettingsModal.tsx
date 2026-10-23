import { useEffect, useState } from 'react'
import { loadSettings, saveSettings, type AppSettings } from '../constants'
import { getGateway, saveGateway, testGateway, getSystemInfo, getMetrics, type GatewaySettings, type SystemInfo, type MetricsInfo } from '../api/settings'
import { getVoiceprints, deleteVoiceprint, type VoiceprintItem } from '../api/recordings'
import { setApiKey } from '../api/client'
import { t, useLang } from '../i18n'

// C1：运行时长格式化（d/h/m）
const fmtUptime = (s: number) => {
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  return d > 0 ? `${d}d${h}h` : h > 0 ? `${h}h${m}m` : `${m}m`
}

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const [s, setS] = useState<AppSettings>(() => loadSettings())
  const [lang, setLang] = useLang()
  const [gw, setGw] = useState<GatewaySettings | null>(null)
  const [sys, setSys] = useState<SystemInfo | null>(null)
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [llm, setLlm] = useState('')
  const [embed, setEmbed] = useState('')
  const [rerank, setRerank] = useState('')
  const [gwMsg, setGwMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [testing, setTesting] = useState(false)
  const [savingGw, setSavingGw] = useState(false)
  const [vps, setVps] = useState<VoiceprintItem[] | null>(null)
  const [metrics, setMetrics] = useState<MetricsInfo | null>(null)

  useEffect(() => {
    getGateway().then((g) => {
      setGw(g)
      setUrl(g.gateway_url)
      setLlm(g.llm_model)
      setEmbed(g.embed_model)
      setRerank(g.rerank_model)
    }).catch((e) => setGwMsg({ ok: false, text: t('c.loadFailed', { err: String(e instanceof Error ? e.message : e) }) }))
    getSystemInfo().then(setSys).catch(() => {})
    getVoiceprints().then(setVps).catch(() => setVps([]))
    getMetrics().then(setMetrics).catch(() => {})  // C1：非管理员 403 隐藏区块
  }, [])

  const delVp = async (id: string) => {
    if (!confirm(t('set.vpDelConfirm'))) return
    const r = await deleteVoiceprint(id)
    if (r.error) alert(r.error)
    setVps((l) => (l ?? []).filter((x) => x.id !== id))
  }

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
          {/* C1 系统状态（仅管理员可见，非管理员 403 自动隐藏） */}
          {metrics && (
            <>
              <label className="fld">{t('set.metricsTitle')}</label>
              <div className="metrics">
                <span className="mchip">⏱ {fmtUptime(metrics.uptime_s)}</span>
                <span className="mchip">{t('set.mQueue')}: {metrics.queue?.queued ?? 0} / {t('set.mRunning')}: {metrics.queue?.processing ?? 0}</span>
                <span className="mchip">{t('set.mToday')}: {metrics.jobs_today?.count ?? 0}{metrics.jobs_today?.failure_rate ? ` · ✕${metrics.jobs_today.failed}` : ''}</span>
                {metrics.reindex?.running && (
                  <span className="mchip warn">{t('set.mReindex')}: {metrics.reindex.done}/{metrics.reindex.total}</span>
                )}
                {metrics.segments?.need_review != null && (
                  <span className="mchip">{t('set.mReview')}: {metrics.segments.need_review}</span>
                )}
              </div>
              {metrics.recent_failures?.length > 0 && (
                <div className="metrics-fails">
                  {metrics.recent_failures.slice(0, 5).map((f, i) => (
                    <div key={i} className="mf-row">
                      <span className="k">{f.kind}</span>
                      <span className="v">{f.filename || f.job_id.slice(0, 8)}{f.detail ? ` — ${f.detail.slice(0, 80)}` : ''}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

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
          <input type="text" value={url} placeholder="http://192.168.8.174:18300/v1"
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
          <div style={{ fontSize: 11, color: 'var(--ink-400)', marginTop: 4, lineHeight: 1.6 }}>
            {t('set.hotwordsTip')}
          </div>

          <label className="fld">{t('set.speakers')}</label>
          <select value={s.speakers} onChange={(e) => setS({ ...s, speakers: e.target.value })}>
            <option value="">{t('set.autoSpk')}</option>
            {[2, 3, 4, 5, 6].map((n) => <option key={n} value={String(n)}>{t('home.spkN', { n })}</option>)}
          </select>

          <label className="fld">{t('set.apiQuota')}</label>
          <div style={{ fontSize: 12, color: 'var(--ink-500)', lineHeight: 1.8 }}>
            {t('set.quotaInfo')}
          </div>

          {/* P2-1：API 访问密钥（服务端启用鉴权后必填，随请求注入 Authorization） */}
          <label className="fld">{t('set.apiKey')}</label>
          <input type="password" defaultValue={localStorage.getItem('ms_api_key') || ''}
            placeholder={t('set.apiKeyPh')}
            onChange={(e) => setApiKey(e.target.value)} />
          <div style={{ fontSize: 11, color: 'var(--ink-400)', marginTop: 4, lineHeight: 1.6 }}>
            {t('set.apiKeyTip')}
          </div>

          {/* P0-3 安全检查清单 */}
          <label className="fld">{t('sec.checkTitle')}</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <span className={'sec-chip ' + (sys?.auth_configured ? 'ok' : 'off')}>🔒 {t('sec.chkAuth')} · {sys?.auth_configured ? t('sec.on') : t('sec.off')}</span>
            <span className={'sec-chip ' + (sys?.media_sign_enabled ? 'ok' : 'off')}>🎧 {t('sec.chkMedia')} · {sys?.media_sign_enabled ? t('sec.on') : t('sec.off')}</span>
            <span className={'sec-chip ' + (gw?.gateway_url ? 'ok' : 'off')}>☁ {t('sec.chkGateway')} · {gw?.gateway_url ? t('sec.on') : t('sec.off')}</span>
          </div>
          {sys && !sys.auth_configured && (
            <div style={{ fontSize: 11, color: 'var(--orange)', marginTop: 5, lineHeight: 1.6 }}>
              {t('sec.warnTitle')}{t('sec.warnBody')}
            </div>
          )}

          {/* P3-3 声纹库管理：仅存本机，可删除 */}
          <label className="fld">{t('set.vpTitle')}</label>
          <div style={{ fontSize: 11, color: 'var(--ink-400)', marginBottom: 6, lineHeight: 1.6 }}>
            {t('set.vpTip')}
          </div>
          {vps && vps.length === 0 && (
            <div style={{ fontSize: 12, color: 'var(--ink-500)' }}>{t('set.vpEmpty')}</div>
          )}
          {(vps ?? []).map((v) => (
            <div key={v.id} className="vp-item">
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {v.name}<span style={{ color: 'var(--ink-400)', fontSize: 11 }}> · ×{v.samples}</span>
              </span>
              <span className="chip k" style={{ cursor: 'pointer', flexShrink: 0 }} onClick={() => delVp(v.id)}>{t('tp2.del')}</span>
            </div>
          ))}

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
