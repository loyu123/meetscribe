import { Routes, Route } from 'react-router-dom'
import Layout from './layout/Layout'
import Home from './pages/Home'
import NewTask from './pages/NewTask'
import JobProgress from './pages/JobProgress'
import MeetingDetail from './pages/MeetingDetail'
import Search from './pages/Search'
import Review from './pages/Review'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="new" element={<NewTask />} />
        <Route path="job/:id" element={<JobProgress />} />
        <Route path="m/:id" element={<MeetingDetail />} />
        {/* 兼容旧链接：转写已并入详情页第一个页签 */}
        <Route path="m/:id/transcript" element={<MeetingDetail />} />
        <Route path="search" element={<Search />} />
        <Route path="review" element={<Review />} />
        <Route path="*" element={
          <div style={{ padding: 60, textAlign: 'center', color: 'var(--ink-400)' }}>
            页面不存在，<a href="/" style={{ color: 'var(--primary)' }}>返回工作台</a>
          </div>
        } />
      </Route>
    </Routes>
  )
}
