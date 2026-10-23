import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { installStaleBundleGuard } from './utils/build-info'
import './styles/tokens.css'
import './styles/global.css'

// U5：旧 chunk 失效时自动刷新一次，避免白屏/旧页面
installStaleBundleGuard()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)
