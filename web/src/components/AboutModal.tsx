import { getSystemInfo, type SystemInfo } from '../api/settings'
import { useEffect, useState } from 'react'
import { t, useLang } from '../i18n'
import { BUILD_SHA, BUILD_TIME, hardReload } from '../utils/build-info'

/** 「关于」弹层：品牌名片 + 技术栈 + 许可（开源后的项目第一入口） */
export default function AboutModal({ onClose }: { onClose: () => void }) {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [lang] = useLang()

  useEffect(() => {
    getSystemInfo().then(setInfo).catch(() => {})
  }, [])

  const ver = info?.version ?? '—'
  const rows: [string, string][] = [
    [t('ab.engine'), 'FunASR（Paraformer / SenseVoice）'],
    [t('ab.diarize'), 'CAM++'],
    [t('ab.ai'), t('ab.aiVal')],
    [t('ab.license'), 'Apache-2.0'],
    [t('ab.webBuild'), `${BUILD_SHA} · ${BUILD_TIME}`],
  ]

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal about" onClick={(e) => e.stopPropagation()}>
        <div className="ab-hd">
          <div className="logo">M</div>
          <div className="en">MeetScribe</div>
          <div className="zh">{t('ab.sub')}</div>
          <div className="ver"><span className="pill rec">v{ver} · web {BUILD_SHA}</span></div>
        </div>
        <div className="ab-bd">
          {rows.map(([k, v]) => (
            <div className="ab-row" key={k}><span className="k">{k}</span><span className="v">{v}</span></div>
          ))}
          <div className="ab-row">
            <span className="k">{t('ab.backend')}</span>
            <span className="v" style={{ color: info ? 'var(--green)' : 'var(--orange)' }}>
              {info ? t('um.running') : t('um.offline')}
            </span>
          </div>
        </div>
        <div className="ab-ft">
          <span>{lang === 'zh' ? '聆语会议' : 'MeetScribe'} · {t('ab.local')}</span>
          <span className="lnk" style={{ cursor: 'pointer' }} onClick={hardReload}>{t('ab.forceReload')}</span>
        </div>
      </div>
    </div>
  )
}
