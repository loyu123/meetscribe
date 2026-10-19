// 轻量 fetch 封装：统一走 /api/v1，由 vite 代理到后端 5000 端口
const BASE = '/api/v1'

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
  const r = await fetch(BASE + path, { headers: { Accept: 'application/json' } })
  if (!r.ok) throw await errOf(r)
  return (await r.json()) as T
}

export async function postJSON<T>(path: string, body: unknown = {}): Promise<T> {
  const r = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw await errOf(r)
  return (await r.json()) as T
}

export async function putJSON<T>(path: string, body: unknown = {}): Promise<T> {
  const r = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw await errOf(r)
  return (await r.json()) as T
}
