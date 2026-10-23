import { useCallback, useEffect, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { getRecordings, getStats, getFolders, createFolder, deleteFolder } from '../api/recordings'
import type { FolderItem } from '../api/recordings'
import { getSystemInfo, type SystemInfo } from '../api/settings'
import { folderColor, fmtBytes } from '../utils/format'
import { t, useLang, setLang } from '../i18n'
import SettingsModal from '../components/SettingsModal'
import AboutModal from '../components/AboutModal'

/** 细线条图标（1.7px 描边、圆角端点，风格统一），按 name 取形 */
const ICONS: Record<string, React.ReactNode> = {
  desk: <><rect x="3" y="3" width="7.5" height="7.5" rx="1.8" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.8" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.8" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.8" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20.5 20.5-4-4" /></>,
  quality: <><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12.3 2.4 2.4 4.6-5.2" /></>,
  folder: <path d="M21 17.5a1.8 1.8 0 0 1-1.8 1.8H4.8A1.8 1.8 0 0 1 3 17.5v-11a1.8 1.8 0 0 1 1.8-1.8h4.4l2 2.6h9a1.8 1.8 0 0 1 1.8 1.8z" />,
  folderPlus: <><path d="M21 17.5a1.8 1.8 0 0 1-1.8 1.8H4.8A1.8 1.8 0 0 1 3 17.5v-11a1.8 1.8 0 0 1 1.8-1.8h4.4l2 2.6h9a1.8 1.8 0 0 1 1.8 1.8z" /><path d="M12 10.5v5M9.5 13h5" /></>,
  trash: <><path d="M4 6.5h16" /><path d="M9.5 6.5V5A1.5 1.5 0 0 1 11 3.5h2A1.5 1.5 0 0 1 14.5 5v1.5" /><path d="m6.5 6.5.8 12a1.8 1.8 0 0 0 1.8 1.7h5.8a1.8 1.8 0 0 0 1.8-1.7l.8-12" /></>,
}

const Ico = ({ name, style }: { name: string; style?: React.CSSProperties }) => (
  <svg className="ico" style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    {ICONS[name]}
  </svg>
)

export default function Sidebar({ open, onClose }: { open?: boolean; onClose?: () => void }) {
  const nav = useNavigate()
  const loc = useLocation()
  const [lang] = useLang()
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [trashN, setTrashN] = useState(0)
  const [reviewN, setReviewN] = useState(0)
  const [folders, setFolders] = useState<FolderItem[]>([])
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [menu, setMenu] = useState(false)
  const [settings, setSettings] = useState(false)
  const [about, setAbout] = useState(false)
  const [sys, setSys] = useState<SystemInfo | null>(null)

  const sp = new URLSearchParams(loc.search)
  const curFolder = sp.get('folder')
  const curTrash = sp.get('trash') === '1'

  const load = useCallback(() => {
    getRecordings().then((rs) => {
      const c: Record<string, number> = { all: rs.length }
      for (const r of rs) {
        const f = r.folder ?? ''
        if (f) c[f] = (c[f] ?? 0) + 1
      }
      setCounts(c)
    }).catch(() => {})
    getRecordings({ deleted: true }).then((d) => setTrashN(d.length)).catch(() => {})
    getStats().then((s) => setReviewN(s.segments.need_review)).catch(() => {})
    getFolders().then(setFolders).catch(() => {})
    getSystemInfo().then(setSys).catch(() => setSys(null))
  }, [])

  useEffect(() => {
    load()
    const onChanged = () => load()
    window.addEventListener('recordings-changed', onChanged)
    return () => window.removeEventListener('recordings-changed', onChanged)
  }, [load])

  const goFolder = (f: string | null) => {
    const p = new URLSearchParams()
    if (f) p.set('folder', f)
    nav({ pathname: '/', search: p.toString() })
  }
  const goTrash = () => nav('/?trash=1')

  const doAdd = async () => {
    const n = newName.trim()
    if (!n) { setAdding(false); return }
    const r = await createFolder(n)
    if (r.error) { alert(r.error); return }
    setNewName(''); setAdding(false); load()
  }
  const doDel = async (f: FolderItem) => {
    const tip = f.count > 0
      ? (lang === 'zh'
          ? `删除文件夹「${f.name}」？其中 ${f.count} 条录音将移至「未归类」。`
          : `Delete folder "${f.name}"? ${f.count} recording(s) will move to Unfiled.`)
      : (lang === 'zh' ? `删除空文件夹「${f.name}」？` : `Delete empty folder "${f.name}"?`)
    if (!window.confirm(tip)) return
    await deleteFolder(f.name)
    load()
  }

  return (
    <aside className={'side' + (open ? ' mob-open' : '')}
      onClick={(e) => {
        // D3：移动端点击任一导航项后自动收起抽屉
        if (open && (e.target as HTMLElement).closest('.nav')) onClose?.()
      }}>
      <div className="brand">
        <span className="wave"><i /><i /><i /><i /><i /></span>
        {lang === 'zh' ? '聆语会议' : 'MeetScribe'}
      </div>

      <NavLink to="/" end className={({ isActive }) => 'nav' + (isActive && !curFolder && !curTrash ? ' on' : '')}>
        <Ico name="desk" /> {t('nav.workbench')}
      </NavLink>
      <NavLink to="/search" className={({ isActive }) => 'nav' + (isActive ? ' on' : '')}>
        <Ico name="search" /> {t('nav.search')}
      </NavLink>
      <NavLink to="/review" className={({ isActive }) => 'nav' + (isActive ? ' on' : '')}>
        <Ico name="quality" /> {t('nav.review')}{reviewN > 0 && <span className="badge" title={t('home.needReview')}>{reviewN > 99 ? '99+' : reviewN}</span>}
      </NavLink>

      <div className="sect">{t('nav.folders')}</div>
      <div className={'nav' + (!curTrash && curFolder === null ? ' on' : '')} style={{ cursor: 'pointer' }} onClick={() => goFolder(null)}>
        <Ico name="folder" /> {t('nav.allRecordings')}<span className="cnt">{counts.all ?? '·'}</span>
      </div>
      {folders.map((f) => (
        <div key={f.name} className={'nav' + (!curTrash && curFolder === f.name ? ' on' : '')} style={{ cursor: 'pointer' }} onClick={() => goFolder(f.name)}>
          <Ico name="folder" style={{ color: folderColor(f.name) }} /> {f.name}
          <span className="cnt">{f.count}</span>
          <span className="fdel" title={lang === 'zh' ? '删除文件夹' : 'Delete folder'} onClick={(e) => { e.stopPropagation(); doDel(f) }}>×</span>
        </div>
      ))}
      {adding ? (
        <div className="nav navadd">
          <input
            autoFocus
            value={newName}
            placeholder={lang === 'zh' ? '文件夹名称' : 'Folder name'}
            maxLength={30}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') doAdd(); if (e.key === 'Escape') { setAdding(false); setNewName('') } }}
            onClick={(e) => e.stopPropagation()}
          />
          <span className="ok" title={t('c.confirm')} onClick={(e) => { e.stopPropagation(); doAdd() }}>✓</span>
        </div>
      ) : (
        <div className="nav navadd" style={{ cursor: 'pointer' }} onClick={() => setAdding(true)}>
          <Ico name="folderPlus" /> {t('nav.newFolder')}<span className="cnt">＋</span>
        </div>
      )}

      <div className="sect">{t('nav.trash')}</div>
      <div className={'nav' + (curTrash ? ' on' : '')} style={{ cursor: 'pointer' }} onClick={goTrash}>
        <Ico name="trash" /> {t('nav.trashItem')}<span className={trashN > 0 ? 'del' : 'cnt'}>{trashN}</span>
      </div>

      {/* 用户条：头像菜单集中「设置 / 语言」等入口 */}
      <div className="user">
        <div className="avatar">A</div>
        <div className="uinfo">
          <span className="nm">admin</span>
          <span className="on" />
        </div>
        <div className="uacts">
          <span title={lang === 'zh' ? '账户菜单（含设置）' : 'Account menu'} style={{ cursor: 'pointer' }} onClick={() => setMenu((v) => !v)}>▾</span>
          <span className="grid" title={lang === 'zh' ? '工作区切换' : 'Workspace'}>⊞</span>
        </div>

        {menu && (
          <>
            <div style={{ position: 'fixed', inset: 0, zIndex: 39 }} onClick={() => setMenu(false)} />
            <div className="umenu v2" style={{ zIndex: 40 }}>
              {/* 头部：账户 + 后端状态 */}
              <div className="mh2">
                <div className="avatar">A</div>
                <div className="who">
                  <div className="n1">admin</div>
                  <div className="n2">{t('um.localAdmin')}</div>
                </div>
                <div className="st">
                  <b className={sys ? 'ok' : 'bad'}>{sys ? '● ' + t('um.running') : '● ' + t('um.offline')}</b>
                  <span>{t('um.backend')}</span>
                </div>
              </div>

              <div className="nm-body">
                <div className="mi" onClick={() => { setMenu(false); setLang(lang === 'zh' ? 'en' : 'zh') }}>
                  <span className="ic">🌐</span>{t('set.lang')}
                  <span className="desc">{lang === 'zh' ? '中文 → EN' : 'EN → 中文'}</span>
                </div>
                <div className="mi" onClick={() => { setMenu(false); setSettings(true) }}>
                  <span className="ic">⚙</span>{t('nav.settings')}
                  <span className="desc">{t('um.settingsDesc')}</span>
                </div>
                <div className="sep" />
                <div className="mi" onClick={() => { setMenu(false); setAbout(true) }}>
                  <span className="ic">ℹ</span>{t('um.about')}
                  <span className="desc">v{sys?.version ?? '…'}</span>
                </div>
                <div className="mi dg dim" title={t('um.signoutSoon')} onClick={(e) => e.stopPropagation()}>
                  <span className="ic">⏻</span>{t('um.signout')}
                  <span className="desc">{t('um.signoutSoon')}</span>
                </div>
              </div>

              {/* 系统信息条：录音 / 占用 / 版本 */}
              <div className="nmsys">
                <div className="s"><b>{sys ? sys.recordings : '—'}</b><span>{t('um.sysRec')}</span></div>
                <div className="s"><b>{sys ? fmtBytes(sys.storage_bytes) : '—'}</b><span>{t('um.sysStorage')}</span></div>
                <div className="s"><b>{sys ? 'v' + sys.version : '—'}</b><span>{t('um.sysVer')}</span></div>
              </div>
            </div>
          </>
        )}
      </div>

      {settings && <SettingsModal onClose={() => setSettings(false)} />}
      {about && <AboutModal onClose={() => setAbout(false)} />}
    </aside>
  )
}
