import { useSyncExternalStore } from 'react'
import zh from './zh'
import en from './en'

export type Lang = 'zh' | 'en'
const DICT: Record<Lang, Record<string, string>> = { zh, en }
export type TKey = keyof typeof zh

let lang: Lang = ((): Lang => {
  try {
    const saved = localStorage.getItem('ms-lang')
    if (saved === 'zh' || saved === 'en') return saved
  } catch { /* localStorage 不可用时走浏览器语言 */ }
  return (navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en'
})()

const subs = new Set<() => void>()

/** 切换界面语言并持久化 */
export function setLang(l: Lang) {
  lang = l
  try { localStorage.setItem('ms-lang', l) } catch { /* ignore */ }
  document.title = l === 'zh' ? '聆语会议 MeetScribe' : 'MeetScribe'
  subs.forEach((f) => f())
}

export function getLang(): Lang { return lang }

function subscribe(f: () => void) {
  subs.add(f)
  return () => { subs.delete(f) }
}

/** 取词条（支持 {n} 占位参数） */
export function t(key: TKey, params?: Record<string, string | number>): string {
  let s: string = DICT[lang][key] ?? DICT.zh[key] ?? key
  if (params) for (const [k, v] of Object.entries(params)) s = s.replace(`{${k}}`, String(v))
  return s
}

/** React hook：返回 [当前语言, 切换函数]，语言变化触发重渲染 */
export function useLang(): [Lang, (l: Lang) => void] {
  const l = useSyncExternalStore(subscribe, getLang)
  return [l, setLang]
}

// 初始化页面标题
document.title = lang === 'zh' ? '聆语会议 MeetScribe' : 'MeetScribe'
