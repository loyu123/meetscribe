import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from './Sidebar'
import Topbar from './Topbar'
import AskPanel from '../components/AskPanel'

export default function Layout() {
  const [navOpen, setNavOpen] = useState(false)
  const loc = useLocation()

  // D3：路由切换时自动收起移动端抽屉
  useEffect(() => { setNavOpen(false) }, [loc.pathname, loc.search])

  return (
    <div className="app">
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <div className={'scrim' + (navOpen ? ' show' : '')} onClick={() => setNavOpen(false)} />
      <div className="main-col">
        <Topbar onBurger={() => setNavOpen(true)} />
        <main className="content">
          <Outlet />
        </main>
      </div>
      <AskPanel />
    </div>
  )
}
