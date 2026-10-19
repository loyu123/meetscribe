import { useLocation } from 'react-router-dom'

export default function Placeholder({ title }: { title: string }) {
  const { pathname } = useLocation()
  return (
    <div className="placeholder">
      <h2>{title}</h2>
      <p>路由 {pathname} 已就绪，此屏将在后续阶段接入对应后端接口实现。</p>
    </div>
  )
}
