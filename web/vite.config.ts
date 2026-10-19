import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import http from 'http'
import { execSync } from 'child_process'

// 后端转发：Windows 上 WSL 的 localhost 转发（wslrelay）偶发失效，导致
// http://localhost:5000 不可达。这里在请求时动态选择后端地址：
//   1) 先快速探测 localhost:5000（后端跑在本机 / relay 正常时的最优路径）
//   2) 失败则取 WSL 虚拟机 IP 直连（IP 每次重启会变，故按需刷新缓存）
// 注意：探测必须发生在「请求时」而非启动时——启动期 execSync 调 wsl.exe
// 在 vite 配置求值阶段会阻塞，导致 dev server 卡死。
const BACKEND_PORT = 5000
let cachedIp = ''
let ipAt = 0

function probeOnce(url: string, timeoutMs: number): boolean {
  try {
    const nullDev = process.platform === 'win32' ? 'NUL' : '/dev/null'
    const out = execSync(`curl -s --max-time ${Math.ceil(timeoutMs / 1000)} -o ${nullDev} -w "%{http_code}" "${url}"`,
      { timeout: timeoutMs, shell: true, stdio: ['ignore', 'pipe', 'ignore'] } as any).toString()
    return out.trim() === '200'
  } catch {
    return false
  }
}

let hostCache = ''
let hostAt = 0

function backendHost(): string {
  // 探测结果整体缓存 60 秒：正常时零开销；relay 失效时也只承担一次探测延迟
  const now = Date.now()
  if (hostCache && now - hostAt < 60_000) return hostCache
  let host = 'localhost'
  if (!probeOnce(`http://localhost:${BACKEND_PORT}/api/v1/stats`, 2500)) {
    if (!cachedIp || now - ipAt > 5 * 60_000) {
      try {
        const distro = process.env.ASR_WSL_DISTRO || 'Ubuntu-22.04'
        const out = execSync(`wsl -d ${distro} hostname -I`,
          { timeout: 8000, stdio: ['ignore', 'pipe', 'ignore'] } as any).toString()
        const ip = out.trim().split(/\s+/)[0]
        if (ip && /^(\d{1,3}\.){3}\d{1,3}$/.test(ip)) { cachedIp = ip; ipAt = now }
      } catch { /* WSL 不可用则沿用旧值 */ }
    }
    if (cachedIp) host = cachedIp
  }
  hostCache = host
  hostAt = now
  return host
}

function proxyToBackend(): Plugin {
  return {
    name: 'asr-api-proxy',
    configureServer(server) {
      server.middlewares.use('/api', (req: http.IncomingMessage, res: http.ServerResponse) => {
        // connect 的 use(prefix) 会剥离前缀，转发时需拼回完整路径
        console.log('[asr-proxy]', req.method, req.url)
        const host = backendHost()
        console.log('[asr-proxy] -> host:', host)
        const proxyReq = http.request({
          host,
          port: BACKEND_PORT,
          path: '/api' + (req.url ?? ''),
          method: req.method,
          headers: { ...req.headers, host: `${host}:${BACKEND_PORT}` },
        }, (pres: http.IncomingMessage) => {
          res.writeHead(pres.statusCode ?? 502, pres.headers as Record<string, string | string[] | undefined>)
          pres.pipe(res)
        })
        proxyReq.on('error', (e: Error) => {
          if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
          res.end(JSON.stringify({ error: '后端不可达（ASR 服务未运行？）: ' + e.message }))
        })
        req.pipe(proxyReq)
      })
    },
  }
}

// 纯前端 SPA，标准 fetch 对接后端 /api/v1；不依赖浏览器私有接口，方便后续 Tauri/Electron 套壳
export default defineConfig({
  plugins: [react(), proxyToBackend()],
  build: { outDir: 'dist' }
})
