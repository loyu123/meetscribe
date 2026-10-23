// 轻量 fetch 封装：统一走 /api/v1，由 vite 代理到后端 5000 端口
const BASE = '/api/v1'

/** P2-1：API 访问密钥（服务端启用 ASR_API_KEYS 后所有 /api 需要 Bearer 鉴权）。
 *  存于 localStorage('ms_api_key')，设置页可配置。 */
export function authHeaders(): Record<string, string> {
  const k = localStorage.getItem('ms_api_key')
  return k ? { Authorization: 'Bearer ' + k } : {}
}

export function setApiKey(key: string) {
  if (key.trim()) localStorage.setItem('ms_api_key', key.trim())
  else localStorage.removeItem('ms_api_key')
}

/** 非 2xx 时读取响应体中的 error 字段，避免后端错误信息被 "HTTP 500" 吞掉 */
async function errOf(r: Response): Promise<Error> {
  let msg = 'HTTP ' + r.status
  try {
    const body = await r.json()
    if (body && (body.error || body.message)) msg = String(body.error || body.message)
  } catch {
    /* 非 JSON 响应（如代理 502 HTML），保留 HTTP 状态码信息 */
  }
  return new Error(msg)
}

export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path, { headers: { Accept: 'application/json', ...authHeaders() } })
  if (!r.ok) throw await errOf(r)
  return (await r.json()) as T
}

export async function postJSON<T>(path: string, body: unknown = {}): Promise<T> {
  const r = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw await errOf(r)
  return (await r.json()) as T
}

export async function putJSON<T>(path: string, body: unknown = {}): Promise<T> {
  const r = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw await errOf(r)
  return (await r.json()) as T
}

/** 从 Content-Disposition 取文件名（后端目前用录音 id，兜底用调用方给的名称） */
function filenameOf(r: Response, fallback: string): string {
  const cd = r.headers.get('Content-Disposition') || ''
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd)
  if (!m || !m[1]) return fallback
  try {
    return decodeURIComponent(m[1])
  } catch {
    return m[1]
  }
}

/**
 * U3：文件下载（导出 TXT/MD/DOCX/SRT/VTT）。
 * 用 fetch 而非 <a href> 直连，失败时才能读到后端 JSON 里的 error 文案并提示用户，
 * 避免浏览器把错误 JSON 当成文件下载下来。
 */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const r = await fetch(BASE + path, { headers: { Accept: '*/*', ...authHeaders() } })
  if (!r.ok) throw await errOf(r)
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filenameOf(r, fallbackName)
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 3000)
}
