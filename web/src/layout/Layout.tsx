import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import Topbar from './Topbar'
import AskPanel from '../components/AskPanel'

export default function Layout() {
  return (
    <div className="app">
      <Sidebar />
      <div className="main-col">
        <Topbar />
        <main className="content">
          <Outlet />
        </main>
      </div>
      <AskPanel />
    </div>
  )
}
